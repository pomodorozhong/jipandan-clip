from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import sherpa_onnx

from jipandan.core.srt import format_srt_timestamp

SAMPLE_RATE = 16_000
FEATURE_DIM = 80

PARAFORMER_REPO = "csukuangfj/sherpa-onnx-paraformer-zh-small-2024-03-09"
PARAFORMER_ALIASES: dict[str, str] = {
    "paraformer-zh-small": PARAFORMER_REPO,
    "sherpa-onnx-paraformer-zh-small-2024-03-09": PARAFORMER_REPO,
}

SILERO_VAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
)


def default_num_threads() -> int:
    cpus = os.cpu_count() or 4
    return max(1, min(cpus, 6))


def _models_cache_dir() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "jipandan" / "models"


def resolve_paraformer_repo(model_name: str) -> str:
    if model_name in PARAFORMER_ALIASES:
        return PARAFORMER_ALIASES[model_name]
    if "/" in model_name:
        return model_name
    local = Path(model_name)
    if local.is_dir():
        return str(local.resolve())
    raise ValueError(
        f"Unknown Paraformer model {model_name!r}. "
        f"Try one of: {', '.join(sorted(PARAFORMER_ALIASES))}."
    )


def resolve_paraformer_paths(model_name: str) -> tuple[str, str]:
    resolved = resolve_paraformer_repo(model_name)
    local = Path(resolved)
    if local.is_dir():
        return str(local / "model.int8.onnx"), str(local / "tokens.txt")
    return f"{resolved}/model.int8.onnx", f"{resolved}/tokens.txt"


def ensure_paraformer_files(model_name: str) -> tuple[Path, Path]:
    resolved = resolve_paraformer_repo(model_name)
    local = Path(resolved)
    if local.is_dir():
        paraformer = local / "model.int8.onnx"
        tokens = local / "tokens.txt"
        if not paraformer.is_file() or not tokens.is_file():
            raise FileNotFoundError(
                f"Paraformer model directory {local} must contain "
                "model.int8.onnx and tokens.txt."
            )
        return paraformer, tokens

    from huggingface_hub import hf_hub_download

    paraformer = Path(hf_hub_download(resolved, "model.int8.onnx"))
    tokens = Path(hf_hub_download(resolved, "tokens.txt"))
    return paraformer, tokens


def ensure_silero_vad() -> Path:
    path = _models_cache_dir() / "silero_vad.onnx"
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Silero VAD to {path}...")
    urlretrieve(SILERO_VAD_URL, path)
    return path


def describe_paraformer_call(
    *,
    model_name: str,
    num_threads: int | None = None,
) -> dict[str, object]:
    paraformer, tokens = resolve_paraformer_paths(model_name)
    return {
        "paraformer": paraformer,
        "tokens": tokens,
        "num_threads": num_threads if num_threads is not None else default_num_threads(),
        "sample_rate": SAMPLE_RATE,
        "feature_dim": FEATURE_DIM,
        "decoding_method": "greedy_search",
        "silero_vad": str(_models_cache_dir() / "silero_vad.onnx"),
    }


@dataclass
class _Segment:
    start: float
    duration: float
    text: str = ""

    @property
    def end(self) -> float:
        return self.start + self.duration


def transcribe_to_text(
    input_audio: Path,
    output_text: Path,
    model_name: str = "paraformer-zh-small",
    num_threads: int | None = None,
    output_format: str = "srt",
    progress_callback: Callable[[], None] | None = None,
) -> None:
    from jipandan.core.whisper import configure_progress_bars

    configure_progress_bars()
    paraformer_path, tokens_path = ensure_paraformer_files(model_name)
    threads = num_threads if num_threads is not None else default_num_threads()
    vad_path = ensure_silero_vad()

    recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(paraformer_path),
        tokens=str(tokens_path),
        num_threads=threads,
        sample_rate=SAMPLE_RATE,
        feature_dim=FEATURE_DIM,
        decoding_method="greedy_search",
        debug=False,
    )

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(vad_path)
    config.silero_vad.threshold = 0.2
    config.silero_vad.min_silence_duration = 0.25
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.max_speech_duration = 5
    config.sample_rate = SAMPLE_RATE
    window_size = config.silero_vad.window_size

    ffmpeg_cmd = [
        "ffmpeg",
        "-i",
        str(input_audio),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-",
    ]
    process = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    frames_per_read = SAMPLE_RATE * 5
    buffer: np.ndarray = np.array([], dtype=np.float32)
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=100)
    segment_list: list[_Segment] = []
    last_progress_at = 0.0

    def maybe_report_progress() -> None:
        nonlocal last_progress_at
        if progress_callback is None:
            return
        now = time.monotonic()
        if now - last_progress_at >= 0.2:
            last_progress_at = now
            progress_callback()

    is_eof = False
    while not is_eof:
        data = process.stdout.read(frames_per_read * 2) if process.stdout else b""
        if not data:
            vad.flush()
            is_eof = True
        else:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
            buffer = np.concatenate([buffer, samples])
            while len(buffer) > window_size:
                vad.accept_waveform(buffer[:window_size])
                buffer = buffer[window_size:]
                maybe_report_progress()

        streams: list = []
        segments: list[_Segment] = []
        while not vad.empty():
            segment = _Segment(
                start=vad.front.start / SAMPLE_RATE,
                duration=len(vad.front.samples) / SAMPLE_RATE,
            )
            segments.append(segment)
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, vad.front.samples)
            streams.append(stream)
            vad.pop()

        for stream in streams:
            recognizer.decode_stream(stream)

        for segment, stream in zip(segments, streams, strict=True):
            segment.text = stream.result.text.strip()
            if segment.text:
                segment_list.append(segment)

        maybe_report_progress()

    if process.stdout:
        process.stdout.close()
    process.wait()

    output_text.parent.mkdir(parents=True, exist_ok=True)
    with output_text.open("w", encoding="utf-8") as f:
        if output_format == "srt":
            for idx, segment in enumerate(segment_list, start=1):
                f.write(f"{idx}\n")
                f.write(
                    f"{format_srt_timestamp(segment.start)} --> "
                    f"{format_srt_timestamp(segment.end)}\n"
                )
                f.write(f"{segment.text}\n\n")
        else:
            for segment in segment_list:
                f.write(
                    f"{segment.start:08.3f} "
                    f"{segment.end:08.3f} "
                    f"{segment.text}\n"
                )
