import argparse
import os
from pathlib import Path

# Fallback only when the web driver is not launched via `jipandan serve`
# (which injects exact xterm CSS cell dimensions for Sixel scaling).
if os.environ.get("TEXTUAL_DRIVER") == "textual.drivers.web_driver:WebDriver":
    if "TEXTUAL_CELL_WIDTH" not in os.environ:
        os.environ["TEXTUAL_CELL_WIDTH"] = "8"
    if "TEXTUAL_CELL_HEIGHT" not in os.environ:
        os.environ["TEXTUAL_CELL_HEIGHT"] = "16"

# Configure tqdm/Hugging Face before Textual starts (stderr has no real fd in TUIs).
from jipandan.core.whisper import configure_progress_bars
from jipandan.tui.app import JipandanApp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive TUI for transcribing and clipping audio."
    )
    parser.add_argument("audio", type=Path, help="Input audio file path.")
    parser.add_argument(
        "--srt",
        type=Path,
        default=None,
        help="Subtitle file path (default: {audio_stem}.srt).",
    )
    parser.add_argument(
        "--clip-dir",
        type=Path,
        default=Path("clip"),
        help="Directory for exported clips (default: clip).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load existing session and merge with SRT if present.",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="Whisper model name for transcription (default: large-v3).",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code for transcription, e.g. en, zh (default: auto-detect).",
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

    configure_progress_bars()

    app = JipandanApp(
        audio=args.audio,
        srt_path=args.srt,
        clip_dir=args.clip_dir,
        resume=args.resume,
        model=args.model,
        language=args.language,
        temperature=args.temperature,
        max_context=args.max_context,
        entropy_thold=args.entropy_thold,
    )
    app.run()


if __name__ == "__main__":
    main()
