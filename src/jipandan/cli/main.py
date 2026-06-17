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
from jipandan.core.transcribe import default_model_for_engine
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
        "--engine",
        choices=("whisper", "paraformer"),
        default="whisper",
        help="Transcription backend (default: whisper).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (default: large-v3 for whisper, paraformer-zh-small for paraformer).",
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
        help="Entropy threshold for fallback decoding (Whisper only, default: 3.0).",
    )
    parser.add_argument(
        "--num-threads",
        type=int,
        default=None,
        help="CPU threads for Paraformer (default: auto).",
    )
    args = parser.parse_args()
    if args.model is None:
        args.model = default_model_for_engine(args.engine)

    configure_progress_bars()

    app = JipandanApp(
        audio=args.audio,
        srt_path=args.srt,
        clip_dir=args.clip_dir,
        resume=args.resume,
        engine=args.engine,
        model=args.model,
        language=args.language,
        temperature=args.temperature,
        max_context=args.max_context,
        entropy_thold=args.entropy_thold,
        num_threads=args.num_threads,
    )
    app.run()


if __name__ == "__main__":
    main()
