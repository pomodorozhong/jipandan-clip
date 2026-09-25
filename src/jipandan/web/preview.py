"""Queued render jobs and persistent waveform-backed export preview cache."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from jipandan.core.ffmpeg import ExportOptions, export_basename, probe_duration_seconds, render_export_preview
from jipandan.core.models import ClipCandidate
from jipandan.core.srt import srt_time_to_seconds
from jipandan.core.waveform_envelope import build_envelope_from_audio_slice

PREVIEW_CACHE_VERSION = 2
PREVIEW_WAVEFORM_BUCKETS = 400
logger = logging.getLogger(__name__)


@dataclass
class PreviewJob:
    id: str
    audio: Path
    source_identity: tuple[int, int]
    candidate: ClipCandidate
    session_revision: int
    options: ExportOptions
    title: str
    cache_key: str
    output: Path
    state: str = "queued"
    duration_ms: int | None = None
    waveform: dict | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self, *, stale: bool, proposed_filename: str) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "clip_id": self.candidate.clip_id,
                "session_revision": self.session_revision,
                "start_ms": round(srt_time_to_seconds(self.candidate.start.replace(".", ",")) * 1000),
                "end_ms": round(srt_time_to_seconds(self.candidate.end.replace(".", ",")) * 1000),
                "mode": self.options.mode,
                "start_threshold_db": self.options.start_threshold_db,
                "stop_threshold_db": self.options.stop_threshold_db,
                "title": self.title,
                "clip_title": self.candidate.title,
                "proposed_filename": proposed_filename,
                "state": self.state,
                "duration_ms": self.duration_ms,
                "waveform": copy.deepcopy(self.waveform),
                "error": self.error,
                "stale": stale,
            }


class PreviewJobs:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache_root = root / "cache"
        self.jobs_root = root / "jobs"
        self._jobs: dict[str, PreviewJob] = {}
        self._jobs_by_key: dict[str, str] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jipandan-preview")

    def start(
        self, audio: Path, candidate: ClipCandidate, revision: int,
        options: ExportOptions, title: str,
    ) -> PreviewJob:
        identity = self.source_identity(audio)
        normalized_title = title.strip()
        cache_key = self._cache_key(audio, identity, candidate, options)
        with self._lock:
            existing_id = self._jobs_by_key.get(cache_key)
            if existing_id is not None:
                existing = self._jobs.get(existing_id)
                if existing is not None:
                    with existing.lock:
                        reusable = existing.state in {"queued", "running"} or (
                            existing.state == "completed" and existing.output.is_file()
                        )
                        if reusable:
                            # The title affects the proposed export filename, not the rendered
                            # audio or waveform. Reuse the render and update its export label.
                            existing.title = normalized_title
                            return existing

            job_id = uuid.uuid4().hex
            job = PreviewJob(
                job_id, audio, identity, copy.deepcopy(candidate), revision, options, normalized_title,
                cache_key, self.jobs_root / job_id / "preview.mp3",
            )
            cached = self._load_cached_job(job)
            if cached is not None:
                self._jobs[job_id] = cached
                self._jobs_by_key[cache_key] = job_id
                return cached

            self._jobs[job_id] = job
            self._jobs_by_key[cache_key] = job_id
        self._executor.submit(self._render, job)
        return job

    @staticmethod
    def source_identity(audio: Path) -> tuple[int, int]:
        stat = audio.stat()
        return stat.st_size, stat.st_mtime_ns

    @staticmethod
    def _cache_key(
        audio: Path, identity: tuple[int, int], candidate: ClipCandidate,
        options: ExportOptions,
    ) -> str:
        inputs = {
            "version": PREVIEW_CACHE_VERSION,
            "audio": str(audio.resolve()),
            "source_size": identity[0],
            "source_mtime_ns": identity[1],
            "clip_id": candidate.clip_id,
            "clip_start": candidate.start,
            "clip_duration": candidate.duration,
            "clip_title": candidate.title,
            "original_start": candidate.original_start,
            "mode": options.mode,
            "start_threshold_db": float(options.start_threshold_db),
            "stop_threshold_db": float(options.stop_threshold_db),
        }
        encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_cached_job(self, job: PreviewJob) -> PreviewJob | None:
        cache_dir = self.cache_root / job.cache_key
        output = cache_dir / "preview.mp3"
        metadata_path = cache_dir / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            duration_ms = metadata["duration_ms"]
            waveform = metadata["waveform"]
            if (
                metadata.get("version") != PREVIEW_CACHE_VERSION
                or metadata.get("key") != job.cache_key
                or not isinstance(duration_ms, int) or duration_ms <= 0
                or (waveform is not None and not self._valid_waveform(waveform))
                or not output.is_file() or output.stat().st_size == 0
            ):
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        job.output = output
        job.state = "completed"
        job.duration_ms = duration_ms
        job.waveform = waveform
        return job

    @staticmethod
    def _valid_waveform(waveform: object) -> bool:
        if not isinstance(waveform, dict):
            return False
        mins, maxs = waveform.get("mins"), waveform.get("maxs")
        if not isinstance(mins, list) or not isinstance(maxs, list) or not mins or len(mins) != len(maxs):
            return False
        try:
            return all(math.isfinite(float(value)) for value in mins + maxs)
        except (TypeError, ValueError):
            return False

    def get(self, job_id: str) -> PreviewJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    @staticmethod
    def is_stale(job: PreviewJob, audio: Path | None, candidate: ClipCandidate | None) -> bool:
        if audio != job.audio or candidate is None:
            return True
        try:
            return (
                PreviewJobs.source_identity(audio) != job.source_identity
                or candidate.start != job.candidate.start
                or candidate.duration != job.candidate.duration
                or candidate.title != job.candidate.title
            )
        except OSError:
            return True

    @staticmethod
    def proposed_filename(job: PreviewJob, clip_dir: Path) -> str:
        basename = export_basename(job.audio, job.candidate.filename_token, job.title)
        name = f"{basename}.mp3"
        number = 2
        while (clip_dir / name).exists():
            name = f"{basename} ({number}).mp3"
            number += 1
        return name

    def _render(self, job: PreviewJob) -> None:
        work_dir = job.output.parent
        completed = False
        with job.lock:
            job.state = "running"
        try:
            work_dir.mkdir(parents=True, exist_ok=False)
            render_export_preview(job.audio, job.candidate, job.options, job.output)
            try:
                seconds = probe_duration_seconds(job.output)
            except (subprocess.CalledProcessError, ValueError) as exc:
                raise RuntimeError(
                    "The selected thresholds removed all playable audio. Lower them and retry"
                ) from exc
            if not math.isfinite(seconds) or seconds <= 0:
                raise RuntimeError("The selected silence settings produced no playable audio")
            duration_ms = round(seconds * 1000)
            try:
                envelope = build_envelope_from_audio_slice(
                    job.output, 0, duration_ms / 1000, PREVIEW_WAVEFORM_BUCKETS,
                )
                waveform = {
                    "start_ms": 0,
                    "end_ms": duration_ms,
                    "mins": np.nan_to_num(envelope.mins, nan=0, posinf=0, neginf=0).round(4).tolist(),
                    "maxs": np.nan_to_num(envelope.maxs, nan=0, posinf=0, neginf=0).round(4).tolist(),
                }
            except (OSError, subprocess.CalledProcessError, ValueError):
                logger.exception("Could not build waveform for preview %s", job.id)
                waveform = None
            self._publish_cache(job, duration_ms, waveform)
            with job.lock:
                job.duration_ms = duration_ms
                job.waveform = waveform
                job.state = "completed"
            completed = True
        except Exception as exc:
            with job.lock:
                job.error = str(exc) or "Preview rendering failed"
                job.state = "failed"
        finally:
            # Keep this job's immutable media path available for its audio response. It is
            # hard-linked to the cache, so it does not duplicate the media data.
            if not completed:
                shutil.rmtree(work_dir, ignore_errors=True)

    def _publish_cache(self, job: PreviewJob, duration_ms: int, waveform: dict | None) -> None:
        cache_dir = self.cache_root / job.cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_audio_path = cache_dir / "preview.mp3"
        staged_cache_audio = cache_dir / f".preview-{job.id}.tmp.mp3"
        cache_metadata_path = cache_dir / "metadata.json"
        staged_cache_metadata = cache_dir / f".metadata-{job.id}.tmp.json"
        try:
            os.link(job.output, staged_cache_audio)
            os.replace(staged_cache_audio, cache_audio_path)
            with staged_cache_metadata.open("w", encoding="utf-8") as handle:
                json.dump({
                    "version": PREVIEW_CACHE_VERSION,
                    "key": job.cache_key,
                    "duration_ms": duration_ms,
                    "waveform": waveform,
                }, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged_cache_metadata, cache_metadata_path)
        finally:
            staged_cache_audio.unlink(missing_ok=True)
            staged_cache_metadata.unlink(missing_ok=True)
