"""Framework-independent, revisioned session operations for the local GUI."""

from __future__ import annotations

import copy
import hashlib
import logging
import math
import os
import shutil
import sys
import uuid
import threading
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, Callable

from jipandan.core.ffmpeg import ExportOptions, probe_duration_seconds
from jipandan.core.models import (
    ClipCandidate,
    ConcurrentSessionChange,
    MIN_CLIP_DURATION_SECONDS,
    Session,
)
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.web.waveform import MAX_BUCKETS, MAX_WINDOW_MS, MIN_BUCKETS, WaveformCache
from jipandan.web.preview import PreviewJobs

logger = logging.getLogger(__name__)


class SessionConflict(Exception):
    pass


class SessionNotReady(Exception):
    pass


class InvalidEdit(ValueError):
    pass


def _time_ms(value: str) -> int:
    return round(srt_time_to_seconds(value.replace(".", ",")) * 1000)


def clip_payload(candidate: ClipCandidate) -> dict:
    return {
        **asdict(candidate),
        "clip_id": candidate.clip_id,
        "start_ms": _time_ms(candidate.start),
        "end_ms": _time_ms(candidate.end),
        "original_start_ms": _time_ms(candidate.original_start),
        "original_end_ms": _time_ms(candidate.original_end),
    }


class SessionService:
    def __init__(self, clip_dir: Path | None = None, upload_dir: Path | None = None,
                 preview_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.audio: Path | None = None
        self.srt: Path | None = None
        self.session: Session | None = None
        self.duration_ms: int | None = None
        self.default_clip_dir = (clip_dir or Path("clip")).resolve()
        if upload_dir is None:
            base = Path.home() / ("Library/Application Support/Jipandan" if sys.platform == "darwin" else ".local/share/jipandan")
            upload_dir = base / "uploads"
        self.upload_dir = upload_dir
        self._undo: list[tuple[str, dict[str, ClipCandidate]]] = []
        self._waveforms = WaveformCache()
        self._previews = PreviewJobs((preview_dir or Path("tmp/web-previews")).resolve())

    def start_preview(
        self, clip_id: str, expected_revision: int, *, mode: str,
        start_threshold_db: float, stop_threshold_db: float, title: str,
    ) -> dict:
        if mode not in {"as_is", "trim_edges", "trim_all"}:
            raise InvalidEdit("Choose an export mode")
        if not title.strip():
            raise InvalidEdit("Export title cannot be empty")
        for value in (start_threshold_db, stop_threshold_db):
            if not math.isfinite(value) or not -90 <= value <= -5:
                raise InvalidEdit("Thresholds must be between -90 and -5 dB")
        with self._lock:
            session = self._check_revision(expected_revision)
            candidate = session.get_candidate(clip_id)
            if candidate is None:
                raise InvalidEdit("Clip not found")
            options = ExportOptions(mode=mode, start_threshold_db=start_threshold_db,
                                    stop_threshold_db=stop_threshold_db)
            try:
                job = self._previews.start(session.audio, candidate, session.revision, options, title.strip())
            except ValueError as exc:
                raise InvalidEdit(str(exc)) from exc
            return self._preview_payload(job)

    def _preview_payload(self, job) -> dict:
        session = self.session
        candidate = session.get_candidate(job.candidate.clip_id) if session else None
        stale = self._previews.is_stale(job, self.audio, candidate)
        clip_dir = session.clip_dir if session else self.default_clip_dir
        return job.snapshot(
            stale=stale,
            proposed_filename=self._previews.proposed_filename(job, clip_dir),
        )

    def preview(self, job_id: str) -> dict:
        with self._lock:
            job = self._previews.get(job_id)
            if job is None:
                raise InvalidEdit("Preview not found")
            return self._preview_payload(job)

    def preview_audio(self, job_id: str) -> Path:
        with self._lock:
            job = self._previews.get(job_id)
            if job is None:
                raise InvalidEdit("Preview not found")
            if self._previews.is_stale(job, self.audio,
                                       self.session.get_candidate(job.candidate.clip_id) if self.session else None):
                raise SessionConflict("Preview is stale; wait for the updated render")
            with job.lock:
                if job.state != "completed" or not job.output.is_file():
                    raise SessionNotReady("Preview is not ready")
            return job.output

    def waveform(self, clip_id: str, start_ms: int, end_ms: int, buckets: int) -> dict:
        with self._lock:
            session = self._ready()
            if session.get_candidate(clip_id) is None:
                raise InvalidEdit("Clip not found")
            if (
                start_ms < 0 or end_ms <= start_ms
                or end_ms - start_ms > MAX_WINDOW_MS
                or self.duration_ms is None or end_ms > self.duration_ms
            ):
                raise InvalidEdit("Waveform window must be within the audio and at most 120 seconds")
            if not MIN_BUCKETS <= buckets <= MAX_BUCKETS:
                raise InvalidEdit("Waveform resolution is out of range")
            audio = session.audio
        return self._waveforms.get(audio, start_ms, end_ms, buckets)

    def import_audio(self, filename: str, source: BinaryIO) -> dict:
        name = Path(filename).name
        if not name or name in {".", ".."} or Path(name).suffix.lower() not in {
            ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"
        }:
            raise InvalidEdit("Choose a supported audio file")
        job_dir = self.upload_dir / uuid.uuid4().hex
        job_dir.mkdir(parents=True, exist_ok=False)
        temporary = job_dir / f".{name}.upload"
        destination = job_dir / name
        try:
            with temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            return self.open_audio(destination)
        except Exception:
            shutil.rmtree(job_dir)
            raise

    def open_audio(self, path: Path) -> dict:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file() or resolved.suffix.lower() not in {
            ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"
        }:
            raise InvalidEdit("Choose a supported audio file")
        duration = probe_duration_seconds(resolved)
        if not math.isfinite(duration) or duration <= 0:
            raise InvalidEdit("Audio has no valid duration")
        srt = resolved.with_suffix(".srt")
        session_path = resolved.with_suffix(".jipandan.json")
        if session_path.exists():
            session = Session.load(session_path)
            session.audio = resolved
            session.srt = srt
        elif srt.exists():
            session = Session.from_srt(resolved, srt, self.default_clip_dir)
            session.save()
        else:
            session = None
        with self._lock:
            self.audio = resolved
            self.srt = srt
            self.session = session
            self.duration_ms = round(duration * 1000)
            self._undo.clear()
            return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            session = self.session
            counts = {name: 0 for name in ("pending", "group1", "group2", "exported", "skipped")}
            if session is not None:
                for candidate in session.candidates:
                    counts[candidate.status] += 1
            return {
                "audio": str(self.audio) if self.audio else None,
                "audio_name": self.audio.name if self.audio else None,
                "duration_ms": self.duration_ms,
                "srt": str(self.srt) if self.srt else None,
                "srt_exists": bool(self.srt and self.srt.exists()),
                "session_path": str(session.session_path) if session else None,
                "clip_dir": str(session.clip_dir) if session else str(self.default_clip_dir),
                "needs_transcription": bool(self.audio and session is None),
                "revision": session.revision if session else None,
                "candidates": [clip_payload(c) for c in session.candidates] if session else [],
                "counts": counts,
                "can_undo": bool(self._undo),
                "merge_preview": self.merge_preview() if session and self.srt and self.srt.exists() else None,
            }

    def _ready(self) -> Session:
        if self.session is None:
            raise SessionNotReady("Open audio with an SRT or transcribe it first")
        return self.session

    def _check_revision(self, expected_revision: int) -> Session:
        session = self._ready()
        if expected_revision != session.revision:
            raise SessionConflict("Session changed; reload before editing")
        return session

    def _mutate(
        self, expected_revision: int, operation: Callable[[Session], object],
        *, undo_ids: list[str] | None = None,
    ) -> tuple[dict, object]:
        with self._lock:
            current = self._check_revision(expected_revision)
            draft = copy.deepcopy(current)
            before = {
                clip_id: copy.deepcopy(candidate)
                for clip_id in (undo_ids or [])
                if (candidate := current.get_candidate(clip_id)) is not None
            }
            result = operation(draft)
            try:
                draft.save()
            except ConcurrentSessionChange as exc:
                self.session = Session.load(current.session_path)
                self._undo.clear()
                raise SessionConflict(str(exc)) from exc
            self.session = draft
            if before:
                self._undo.append((str(result), before))
                self._undo = self._undo[-50:]
            return self.snapshot(), result

    def patch_clip(
        self, clip_id: str, expected_revision: int, *,
        status: str | None = None, title: str | None = None,
        start_ms: int | None = None, end_ms: int | None = None,
    ) -> dict:
        if all(value is None for value in (status, title, start_ms, end_ms)):
            raise InvalidEdit("No clip change provided")
        if status is not None and status not in {"pending", "group1", "group2", "skipped"}:
            raise InvalidEdit("Invalid status")
        if title is not None and not title.strip():
            raise InvalidEdit("Title cannot be empty")

        def change(session: Session) -> str:
            candidate = session.get_candidate(clip_id)
            if candidate is None:
                raise InvalidEdit("Clip not found")
            if status is not None:
                candidate.status = status
            if title is not None:
                candidate.title = title.strip()
                candidate.last_export_title = candidate.title
            if start_ms is not None or end_ms is not None:
                start = start_ms if start_ms is not None else _time_ms(candidate.start)
                end = end_ms if end_ms is not None else _time_ms(candidate.end)
                if start < 0 or end - start < round(MIN_CLIP_DURATION_SECONDS * 1000):
                    raise InvalidEdit("Clip bounds need at least 10 ms of positive duration")
                if self.duration_ms is not None and end > self.duration_ms:
                    raise InvalidEdit("Clip end exceeds audio duration")
                candidate.start = seconds_to_ffmpeg_timestamp(start / 1000)
                candidate.duration = f"{(end - start) / 1000:.3f}"
            return clip_id

        snapshot, _ = self._mutate(expected_revision, change, undo_ids=[clip_id])
        self._prewarm_grouped_clip(clip_id)
        return snapshot

    def _prewarm_grouped_clip(self, clip_id: str) -> None:
        """Queue the default render for a grouped clip without delaying its edit."""
        with self._lock:
            session = self.session
            if session is None or session.audio is None:
                return
            candidate = session.get_candidate(clip_id)
            if candidate is None or candidate.status not in {"group1", "group2"}:
                return
            audio = session.audio
            revision = session.revision
            candidate = copy.deepcopy(candidate)
        try:
            self._previews.start(
                audio, candidate, revision,
                ExportOptions(mode="trim_edges", start_threshold_db=-40, stop_threshold_db=-50),
                candidate.title,
            )
        except Exception:
            logger.exception("Could not prewarm export preview for clip %s", clip_id)

    def duplicate(self, clip_id: str, expected_revision: int) -> dict:
        def change(session: Session) -> str:
            duplicate = session.duplicate_candidate(clip_id)
            if duplicate is None:
                raise InvalidEdit("Clip not found")
            return duplicate.clip_id

        snapshot, result = self._mutate(expected_revision, change)
        snapshot["created_clip_id"] = result
        return snapshot

    def bulk_skip(self, clip_ids: list[str], expected_revision: int) -> dict:
        if not clip_ids:
            raise InvalidEdit("Select at least one clip")
        if len(set(clip_ids)) != len(clip_ids):
            raise InvalidEdit("Clip IDs must be unique")

        def change(session: Session) -> list[str]:
            if any(session.get_candidate(clip_id) is None for clip_id in clip_ids):
                raise InvalidEdit("Clip not found")
            changed = [
                clip_id for clip_id in clip_ids
                if session.get_candidate(clip_id).status == "pending"
            ]
            session.bulk_skip(changed)
            return changed

        snapshot, changed = self._mutate(expected_revision, change, undo_ids=clip_ids)
        snapshot["changed_clip_ids"] = changed
        return snapshot

    def undo(self, expected_revision: int) -> dict:
        with self._lock:
            self._check_revision(expected_revision)
            if not self._undo:
                raise InvalidEdit("Nothing to undo")
            label, before = self._undo[-1]

            def restore(session: Session) -> str:
                for clip_id, old in before.items():
                    position = session._find_position(clip_id)
                    if position is not None:
                        session.candidates[position] = copy.deepcopy(old)
                return label

            snapshot, _ = self._mutate(expected_revision, restore)
            self._undo.pop()
            snapshot["can_undo"] = bool(self._undo)
            return snapshot

    def merge_preview(self) -> dict | None:
        with self._lock:
            if self.session is None or self.srt is None or not self.srt.exists():
                return None
            session = self.session
            changes = session.srt_merge_preview()
            fingerprint = hashlib.sha256(self.srt.read_bytes()).hexdigest()
            unknown_text_change = (
                session.srt_fingerprint is None
                and session.session_path.exists()
                and self.srt.stat().st_mtime_ns > session.session_path.stat().st_mtime_ns
            )
            return {
                **changes,
                "affected_clip_ids": [
                    c.clip_id for c in session.candidates
                    if c.index in set(changes["removed"] + changes["timing_changed"] + changes["text_changed"])
                ],
                "unknown_original_text_clip_ids": [
                    c.clip_id for c in session.candidates if c.suffix == 0 and c.source_text is None
                ],
                "srt_fingerprint": fingerprint,
                "file_changed": (
                    session.srt_fingerprint is not None
                    and session.srt_fingerprint != fingerprint
                ) or unknown_text_change,
                "text_change_unverified": unknown_text_change,
            }

    def apply_merge(
        self, expected_revision: int, srt_fingerprint: str,
        remove_indexes: list[int],
    ) -> dict:
        with self._lock:
            self._check_revision(expected_revision)
            preview = self.merge_preview()
            if preview is None or preview["srt_fingerprint"] != srt_fingerprint:
                raise SessionConflict("SRT changed; review it again")
            if len(set(remove_indexes)) != len(remove_indexes) or not set(remove_indexes) <= set(preview["removed"]):
                raise InvalidEdit("Remove indexes must be listed in the merge preview")

            def change(session: Session) -> list[str]:
                return session.merge_with_srt(remove_missing_indexes=set(remove_indexes))

            snapshot, warnings = self._mutate(expected_revision, change)
            snapshot["merge_warnings"] = warnings
            return snapshot
