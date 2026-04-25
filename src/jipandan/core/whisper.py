from pathlib import Path

import mlx_whisper


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
    transcribe_kwargs = {
        "temperature": temperature,
        "compression_ratio_threshold": entropy_thold,
    }
    if language:
        transcribe_kwargs["language"] = language
    if max_context <= 0:
        transcribe_kwargs["condition_on_previous_text"] = False

    # mlx-whisper expects a local model path or HF repo.
    # Keep short names like "large-v3" convenient by mapping to mlx-community.
    model_repo = _resolve_model_name(model_name)
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
