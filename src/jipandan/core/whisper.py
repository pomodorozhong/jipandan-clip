from __future__ import annotations

import os
import threading
from pathlib import Path

# Textual (and other TUIs) expose stderr.fileno() == -1. tqdm then tries to
# create a multiprocessing lock for progress bars, which crashes with
# "bad value(s) in fds_to_keep" when Hugging Face downloads models from a
# background worker thread.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

_PROGRESS_BARS_CONFIGURED = False

# mlx_whisper / openai-whisper defaults that matter for long raw audio.
DEFAULT_COMPRESSION_RATIO_THRESHOLD = 2.4
DEFAULT_NO_SPEECH_THRESHOLD = 0.6
DEFAULT_HALLUCINATION_SILENCE_THRESHOLD = 2.0
DEFAULT_TEMPERATURE_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


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


def _temperature_for_transcribe(temperature: float) -> float | tuple[float, ...]:
    """Use Whisper's temperature fallback ladder when starting at 0.0."""
    if temperature <= 0:
        return DEFAULT_TEMPERATURE_FALLBACK
    return temperature


def describe_transcribe_call(
    *,
    model_name: str,
    language: str | None,
    temperature: float,
    max_context: int,
    entropy_thold: float,
    word_timestamps: bool = True,
    no_speech_threshold: float = DEFAULT_NO_SPEECH_THRESHOLD,
    hallucination_silence_threshold: float | None = DEFAULT_HALLUCINATION_SILENCE_THRESHOLD,
) -> tuple[str, dict[str, object]]:
    """Return (resolved_model_repo, kwargs) passed to mlx_whisper.transcribe()."""
    # Note: entropy_thold maps to mlx's compression_ratio_threshold (legacy CLI name
    # from whisper.cpp). Whisper's own default is 2.4, not 3.0.
    transcribe_kwargs: dict[str, object] = {
        "verbose": True,
        "temperature": _temperature_for_transcribe(temperature),
        "compression_ratio_threshold": entropy_thold,
        "no_speech_threshold": no_speech_threshold,
        "word_timestamps": word_timestamps,
    }
    if language:
        transcribe_kwargs["language"] = language
    if max_context <= 0:
        # Avoid prompt feedback loops / timestamp drift on long files with silence.
        transcribe_kwargs["condition_on_previous_text"] = False
    if word_timestamps and hallucination_silence_threshold is not None:
        # Skip long silent gaps when word timing looks like a hallucination.
        # Requires word_timestamps=True in mlx_whisper.
        transcribe_kwargs["hallucination_silence_threshold"] = (
            hallucination_silence_threshold
        )
    model_repo = _resolve_model_name(model_name)
    return model_repo, transcribe_kwargs


def transcribe_to_text(
    input_audio: Path,
    output_text: Path,
    model_name: str = "mlx-community/whisper-large-v3-mlx",
    language: str | None = None,
    temperature: float = 0.0,
    max_context: int = 0,
    entropy_thold: float = DEFAULT_COMPRESSION_RATIO_THRESHOLD,
    word_timestamps: bool = True,
    no_speech_threshold: float = DEFAULT_NO_SPEECH_THRESHOLD,
    hallucination_silence_threshold: float | None = DEFAULT_HALLUCINATION_SILENCE_THRESHOLD,
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
        word_timestamps=word_timestamps,
        no_speech_threshold=no_speech_threshold,
        hallucination_silence_threshold=hallucination_silence_threshold,
    )
    result = mlx_whisper.transcribe(
        str(input_audio),
        path_or_hf_repo=model_repo,
        **transcribe_kwargs,
    )
    segments = result.get("segments", [])

    output_text.parent.mkdir(parents=True, exist_ok=True)
    with output_text.open("w", encoding="utf-8") as f:
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
