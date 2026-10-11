"""Isolated Whisper entry point that re-transcribes individual clip spans.

Reads a JSON request (audio, settings, clips) and prints one
``RESULT_PREFIX``-tagged JSON line per finished clip so the supervisor can
report progress while the model stays loaded for the whole batch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RESULT_PREFIX = "JIPANDAN_CLIP_RESULT "
SAMPLE_RATE = 16_000
# Whisper cuts words at hard boundaries; a little context on each side helps.
PADDING_MS = 200


def decode_span(audio: Path, start_ms: int, end_ms: int):
    import numpy as np

    start = max(0, start_ms - PADDING_MS)
    duration = end_ms + PADDING_MS - start
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{start / 1000:.3f}", "-t", f"{duration / 1000:.3f}",
         "-i", str(audio), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        check=True, stdout=subprocess.PIPE,
    ).stdout
    return np.frombuffer(raw[: len(raw) // 4 * 4], np.float32)


def main() -> None:
    from jipandan.core.whisper import configure_progress_bars, describe_transcribe_call

    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    audio = Path(request["audio"])
    settings = request["settings"]
    configure_progress_bars()
    import mlx_whisper

    model_repo, kwargs = describe_transcribe_call(
        model_name=settings["model_name"], language=settings.get("language"),
        temperature=settings["temperature"], max_context=0,
        entropy_thold=settings["entropy_thold"],
    )
    kwargs["verbose"] = None
    print(f"Whisper model repository: {model_repo}", file=sys.stderr, flush=True)
    for clip in request["clips"]:
        samples = decode_span(audio, clip["start_ms"], clip["end_ms"])
        text = ""
        if samples.size:
            result = mlx_whisper.transcribe(
                samples, path_or_hf_repo=model_repo,
                initial_prompt=clip.get("prompt") or None, **kwargs,
            )
            text = "".join(str(segment.get("text", "")) for segment in result.get("segments", [])).strip()
        print(f"{RESULT_PREFIX}{json.dumps({'clip_id': clip['clip_id'], 'text': text}, ensure_ascii=False)}",
              flush=True)


if __name__ == "__main__":
    main()
