"""Durable, bounded transcription jobs with isolated Whisper processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


@dataclass
class TranscriptionJob:
    id: str
    audio: Path
    settings: dict
    directory: Path
    state: str = "queued"
    phase: str = "Waiting to start"
    error: str | None = None
    entry_count: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def output(self) -> Path:
        return self.directory / "transcript.srt"

    @property
    def log(self) -> Path:
        return self.directory / "run.log"

    def payload(self) -> dict:
        return {
            "id": self.id, "audio": str(self.audio), "settings": self.settings,
            "state": self.state, "phase": self.phase, "error": self.error,
            "entry_count": self.entry_count, "created_at": self.created_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }

    def snapshot(self) -> dict:
        try:
            with self.log.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 8192))
                lines = handle.read().decode("utf-8", errors="replace").splitlines()[-20:]
        except FileNotFoundError:
            lines = []
        return {
            **self.payload(),
            "log_tail": lines,
            "log_file": str(self.log.resolve()),
        }


class TranscriptionJobs:
    def __init__(self, root: Path, publish: Callable[[TranscriptionJob], int]) -> None:
        self.root = root
        self._publish = publish
        self._jobs: dict[str, TranscriptionJob] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jipandan-transcribe")
        self._load_jobs()

    def _write(self, job: TranscriptionJob) -> None:
        job.directory.mkdir(parents=True, exist_ok=True)
        temporary = job.directory / ".job.json.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(job.payload(), handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, job.directory / "job.json")

    def _load_jobs(self) -> None:
        if not self.root.exists():
            return
        for path in self.root.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = TranscriptionJob(
                    id=data["id"], audio=Path(data["audio"]), settings=data["settings"],
                    directory=path.parent, state=data["state"], phase=data["phase"],
                    error=data.get("error"), entry_count=data.get("entry_count"),
                    created_at=data["created_at"], started_at=data.get("started_at"),
                    finished_at=data.get("finished_at"),
                )
                if job.id != path.parent.name:
                    continue
                if job.state in {"queued", "running"}:
                    job.state = "failed"
                    job.phase = "Interrupted"
                    job.error = "The server stopped before transcription finished. Retry to start a new job."
                    job.finished_at = time.time()
                    self._write(job)
                self._jobs[job.id] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def latest(self, audio: Path | None) -> dict | None:
        with self._lock:
            matches = [job for job in self._jobs.values() if job.audio == audio]
            return max(matches, key=lambda job: job.created_at).snapshot() if matches else None

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None

    def start(self, audio: Path, settings: dict) -> dict:
        with self._lock:
            if any(job.audio == audio and job.state in {"queued", "running"}
                   for job in self._jobs.values()):
                raise ValueError("A transcription is already running for this audio")
            job_id = uuid.uuid4().hex
            job = TranscriptionJob(job_id, audio, settings, self.root / job_id)
            self._write(job)
            self._jobs[job_id] = job
            self._executor.submit(self._run, job)
            return job.snapshot()

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state in {"queued", "running"} and job.phase != "Saving transcript":
                job.state = "cancelled"
                job.phase = "Cancelled"
                job.finished_at = time.time()
                self._write(job)
                process = self._processes.get(job_id)
                if process is not None and process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            return job.snapshot()

    def _run_process(self, job: TranscriptionJob) -> int:
        settings_path = job.directory / "settings.json"
        settings_path.write_text(json.dumps(job.settings), encoding="utf-8")
        with job.log.open("w", encoding="utf-8") as log:
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(f"[{started}] Transcription job {job.id} started", file=log, flush=True)
            print(f"Audio file: {job.audio}", file=log, flush=True)
            print(f"Settings file: {settings_path}", file=log, flush=True)
            process = subprocess.Popen(
                [sys.executable, "-u", "-m", "jipandan.web.transcribe_worker",
                 str(job.audio), str(job.output), str(settings_path)],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            with self._lock:
                self._processes[job.id] = process
                if job.state == "cancelled":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            try:
                return process.wait()
            finally:
                with self._lock:
                    self._processes.pop(job.id, None)

    def _run(self, job: TranscriptionJob) -> None:
        with self._lock:
            if job.state == "cancelled":
                return
            job.state = "running"
            job.phase = "Transcribing"
            job.started_at = time.time()
            self._write(job)
        try:
            code = self._run_process(job)
            if code != 0:
                lines = job.snapshot()["log_tail"]
                detail = next((line for line in reversed(lines)
                               if any(marker in line for marker in (
                                   "Error:", "Exception:", "ValueError:", "No Metal device",
                               ))), "")
                raise RuntimeError(
                    f"Whisper exited with status {code}. "
                    f"{detail[:300] if detail else 'See the job log for details.'}"
                )
            if not job.output.is_file():
                raise RuntimeError("Whisper finished without a transcript")
            with self._lock:
                if job.state == "cancelled":
                    return
                job.phase = "Saving transcript"
                self._write(job)
            entry_count = self._publish(job)
            with self._lock:
                job.entry_count = entry_count
                job.state = "completed"
                job.phase = "Ready for review"
                job.finished_at = time.time()
                self._write(job)
        except Exception as exc:
            try:
                with job.log.open("a", encoding="utf-8") as log:
                    failed = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    print(
                        f"\n[{failed}] Supervisor failure: {type(exc).__name__}: {exc}",
                        file=log,
                        flush=True,
                    )
                    traceback.print_exception(exc, file=log)
                    log.flush()
                    os.fsync(log.fileno())
            except OSError:
                pass
            with self._lock:
                if job.state != "cancelled":
                    job.state = "failed"
                    job.phase = "Failed"
                    job.error = str(exc) or "Transcription failed"
                    job.finished_at = time.time()
                    self._write(job)

    def close(self) -> None:
        with self._lock:
            active = [job.id for job in self._jobs.values() if job.state in {"queued", "running"}]
        for job_id in active:
            self.cancel(job_id)
        self._executor.shutdown(wait=False, cancel_futures=True)
