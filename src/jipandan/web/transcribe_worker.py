"""Isolated Whisper entry point for the local web transcription queue."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jipandan.core.whisper import transcribe_to_text


def main() -> None:
    audio, output, settings_path = map(Path, sys.argv[1:4])
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{started}] Transcription worker started", flush=True)
    print(f"Audio file: {audio}", flush=True)
    print(f"Settings: {json.dumps(settings, ensure_ascii=False, sort_keys=True)}", flush=True)
    print("Loading model and transcribing audio…", flush=True)
    transcribe_to_text(audio, output, **settings)
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{finished}] Transcript validated and ready: {output}", flush=True)


if __name__ == "__main__":
    main()
