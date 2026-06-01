import argparse
import os
from pathlib import Path

# textual-image probes cell size at import time; set defaults for textual serve.
if os.environ.get("TEXTUAL_DRIVER") == "textual.drivers.web_driver:WebDriver":
    os.environ.setdefault("TEXTUAL_CELL_WIDTH", "8")
    os.environ.setdefault("TEXTUAL_CELL_HEIGHT", "16")

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
        help="Sampling temperature for transcription (default: 0.0).",
    )
    parser.add_argument(
        "-mc",
        "--max-context",
        type=int,
        default=0,
        help="Maximum context tokens between segments (default: 0).",
    )
    parser.add_argument(
        "-et",
        "--entropy-thold",
        type=float,
        default=3.0,
        help="Entropy threshold for fallback decoding (default: 3.0).",
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
