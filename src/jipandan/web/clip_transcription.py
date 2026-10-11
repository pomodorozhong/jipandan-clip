"""Run the clip re-transcription worker and stream its per-clip results."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator

from jipandan.web.clip_transcribe_worker import RESULT_PREFIX


def transcribe_clips(
    audio: Path,
    settings: dict,
    clips: list[dict],
    log_path: Path,
    on_process: Callable[[subprocess.Popen], None],
) -> Iterator[tuple[str, str]]:
    """Yield ``(clip_id, text)`` as Whisper finishes each clip span."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jipandan-clip-transcribe-") as directory:
        request = Path(directory) / "request.json"
        request.write_text(json.dumps(
            {"audio": str(audio), "settings": settings, "clips": clips}, ensure_ascii=False,
        ), encoding="utf-8")
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", "-m", "jipandan.web.clip_transcribe_worker", str(request)],
                stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                start_new_session=True,
            )
            on_process(process)
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    if line.startswith(RESULT_PREFIX):
                        result = json.loads(line[len(RESULT_PREFIX):])
                        yield str(result["clip_id"]), str(result["text"])
                    else:
                        log.write(line)
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                code = process.wait()
        if code != 0:
            lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            detail = lines[-1][:300] if lines else "See the log for details."
            raise RuntimeError(f"Whisper exited with status {code}. {detail}")
