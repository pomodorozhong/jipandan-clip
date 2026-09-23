from __future__ import annotations

import os
import math
import tempfile
import threading
from pathlib import Path

from jipandan.core.srt import parse_srt, srt_time_to_seconds

# Textual (and other TUIs) expose stderr.fileno() == -1. tqdm then tries to
# create a multiprocessing lock for progress bars, which crashes with
# "bad value(s) in fds_to_keep" when Hugging Face downloads models from a
# background worker thread.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

_PROGRESS_BARS_CONFIGURED = False


def configure_progress_bars() -> None:
    """Configure tqdm locks before mlx/Hugging Face run in a TUI subprocess."""
    global _PROGRESS_BARS_CONFIGURED
    if _PROGRESS_BARS_CONFIGURED:
        return
    _PROGRESS_BARS_CONFIGURED = True

    try:
        import tqdm

        tqdm.tqdm.set_lock(threading.RLock())
    except ImportError:
        pass

    try:
        from huggingface_hub.utils import tqdm as hf_tqdm

        hf_tqdm.set_lock(threading.RLock())
    except ImportError:
        pass


def describe_transcribe_call(
    *,
    model_name: str,
    language: str | None,
    temperature: float,
    max_context: int,
    entropy_thold: float,
) -> tuple[str, dict[str, object]]:
    """Return (resolved_model_repo, kwargs) passed to mlx_whisper.transcribe()."""
    if not model_name.strip():
        raise ValueError("Model is required")
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("Temperature must be a nonnegative finite number")
    if not math.isfinite(entropy_thold) or entropy_thold <= 0:
        raise ValueError("Entropy threshold must be a positive finite number")
    if max_context < 0:
        raise ValueError("Max context must be nonnegative")
    transcribe_kwargs: dict[str, object] = {
        "verbose": True,
        "temperature": temperature,
        "compression_ratio_threshold": entropy_thold,
    }
    if language:
        transcribe_kwargs["language"] = language
    if max_context <= 0:
        transcribe_kwargs["condition_on_previous_text"] = False
    model_repo = _resolve_model_name(model_name)
    return model_repo, transcribe_kwargs


def transcribe_to_text(
    input_audio: Path,
    output_text: Path,
    model_name: str = "mlx-community/whisper-large-v3-mlx",
    language: str | None = None,
    temperature: float = 0.0,
    max_context: int = 64,
    entropy_thold: float = 3.0,
    output_format: str = "srt",
) -> None:
    configure_progress_bars()
    import mlx_whisper

    model_repo, transcribe_kwargs = describe_transcribe_call(
        model_name=model_name,
        language=language,
        temperature=temperature,
        max_context=max_context,
        entropy_thold=entropy_thold,
    )
    result = mlx_whisper.transcribe(
        str(input_audio),
        path_or_hf_repo=model_repo,
        **transcribe_kwargs,
    )
    segments = result.get("segments", [])

    output_text.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_text.parent,
            prefix=f".{output_text.name}.", suffix=".tmp", delete=False,
        ) as f:
            temporary_path = Path(f.name)
            if not segments:
                raise ValueError("Transcription returned no segments")
            for segment in segments:
                start = float(segment["start"])
                end = float(segment["end"])
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                    raise ValueError("Transcription contains invalid segment times")
                if not str(segment["text"]).strip():
                    raise ValueError("Transcription contains an empty segment")
            if output_format == "srt":
                for idx, segment in enumerate(segments, start=1):
                    f.write(f"{idx}\n")
                    f.write(
                        f"{_format_srt_timestamp(float(segment['start']))} --> "
                        f"{_format_srt_timestamp(float(segment['end']))}\n"
                    )
                    f.write(f"{segment['text'].strip()}\n\n")
            else:
                for segment in segments:
                    f.write(
                        f"{float(segment['start']):08.3f} "
                        f"{float(segment['end']):08.3f} "
                        f"{segment['text'].strip()}\n"
                    )
            f.flush()
            os.fsync(f.fileno())
        if output_format == "srt":
            parsed = parse_srt(temporary_path)
            if len(parsed) != len(segments) or any(
                srt_time_to_seconds(entry.end) <= srt_time_to_seconds(entry.start)
                for entry in parsed
            ):
                raise ValueError("Transcription produced an invalid SRT")
        os.replace(temporary_path, output_text)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _resolve_model_name(model_name: str) -> str:
    if "/" in model_name:
        return model_name
    if Path(model_name).exists():
        return model_name
    return f"mlx-community/whisper-{model_name}-mlx"
