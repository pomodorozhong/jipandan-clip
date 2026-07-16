import argparse
import time
from pathlib import Path

from jipandan.core.whisper import transcribe_to_text


def _format_elapsed(elapsed_seconds: float) -> str:
    minutes, seconds = divmod(elapsed_seconds, 60)
    if minutes >= 1:
        return f"{int(minutes)}m {seconds:.2f}s"
    return f"{seconds:.2f}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio to timestamped text.")
    parser.add_argument("input", type=Path, help="Input audio file path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output transcript file path (default: input path with output extension).",
    )
    parser.add_argument(
        "--output-format",
        choices=("txt", "srt"),
        default="srt",
        help="Output format (default: srt).",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="Whisper model name (default: large-v3).",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code, e.g. en, zh (default: auto-detect).",
    )
    parser.add_argument(
        "-tp",
        "--temperature",
        type=float,
        default=0.0,
        help=(
            "Sampling temperature (default: 0.0). "
            "At 0.0, mlx uses the Whisper fallback ladder on failed windows."
        ),
    )
    parser.add_argument(
        "-mc",
        "--max-context",
        type=int,
        default=0,
        help=(
            "If <= 0, disable conditioning on previous text "
            "(default: 0; recommended for long/silent audio)."
        ),
    )
    parser.add_argument(
        "-et",
        "--entropy-thold",
        type=float,
        default=2.4,
        help=(
            "Compression-ratio threshold for decode fallback "
            "(mlx compression_ratio_threshold; default: 2.4)."
        ),
    )
    args = parser.parse_args()
    if args.output is None:
        args.output = args.input.with_suffix(f".{args.output_format}")

    print("Arguments:")
    for key, value in vars(args).items():
        print(f"  {key}: {value}")

    start = time.perf_counter()
    transcribe_to_text(
        input_audio=args.input,
        output_text=args.output,
        model_name=args.model,
        language=args.language,
        temperature=args.temperature,
        max_context=args.max_context,
        entropy_thold=args.entropy_thold,
        output_format=args.output_format,
    )
    elapsed = time.perf_counter() - start
    print(f"Wrote transcript to: {args.output}")
    print(f"Elapsed time: {_format_elapsed(elapsed)}")


if __name__ == "__main__":
    main()
