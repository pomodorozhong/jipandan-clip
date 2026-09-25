"""Isolated Whisper entry point for the local web transcription queue."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jipandan.core.whisper import transcribe_to_text


def main() -> None:
    audio, output, settings_path = map(Path, sys.argv[1:4])
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    print("Loading model and transcribing audio…", flush=True)
    transcribe_to_text(audio, output, **settings)
    print("Transcript validated and ready.", flush=True)


if __name__ == "__main__":
    main()
