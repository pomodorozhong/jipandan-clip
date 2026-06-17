from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

TranscribeEngine = Literal["whisper", "paraformer"]

DEFAULT_MODELS: dict[TranscribeEngine, str] = {
    "whisper": "large-v3",
    "paraformer": "paraformer-zh-small",
}


def normalize_engine(engine: str) -> TranscribeEngine:
    value = engine.strip().lower()
    if value in ("whisper", "mlx", "mlx-whisper"):
        return "whisper"
    if value in ("paraformer", "sherpa", "sherpa-onnx"):
        return "paraformer"
    raise ValueError(
        f"Unknown transcribe engine {engine!r}. Choose whisper or paraformer."
    )


def default_model_for_engine(engine: str) -> str:
    return DEFAULT_MODELS[normalize_engine(engine)]


def describe_transcribe_call(
    *,
    engine: str = "whisper",
    model_name: str | None = None,
    language: str | None = None,
    temperature: float = 0.0,
    max_context: int = 0,
    entropy_thold: float = 3.0,
    num_threads: int | None = None,
) -> tuple[TranscribeEngine, str, dict[str, object]]:
    normalized = normalize_engine(engine)
    model = model_name or default_model_for_engine(normalized)
    if normalized == "whisper":
        from jipandan.core import whisper

        repo, kwargs = whisper.describe_whisper_call(
            model_name=model,
            language=language,
            temperature=temperature,
            max_context=max_context,
            entropy_thold=entropy_thold,
        )
        return normalized, repo, kwargs
    from jipandan.core import sherpa_paraformer

    kwargs = sherpa_paraformer.describe_paraformer_call(
        model_name=model,
        num_threads=num_threads,
    )
    return normalized, model, kwargs


def transcribe_to_text(
    input_audio: Path,
    output_text: Path,
    *,
    engine: str = "whisper",
    model_name: str | None = None,
    language: str | None = None,
    temperature: float = 0.0,
    max_context: int = 0,
    entropy_thold: float = 3.0,
    num_threads: int | None = None,
    output_format: str = "srt",
    progress_callback: Callable[[], None] | None = None,
) -> None:
    normalized = normalize_engine(engine)
    model = model_name or default_model_for_engine(normalized)
    if normalized == "whisper":
        from jipandan.core import whisper

        whisper.transcribe_to_text(
            input_audio=input_audio,
            output_text=output_text,
            model_name=model,
            language=language,
            temperature=temperature,
            max_context=max_context,
            entropy_thold=entropy_thold,
            output_format=output_format,
        )
        return
    from jipandan.core import sherpa_paraformer

    sherpa_paraformer.transcribe_to_text(
        input_audio=input_audio,
        output_text=output_text,
        model_name=model,
        num_threads=num_threads,
        output_format=output_format,
        progress_callback=progress_callback,
    )
