"""Framework-independent session operations for the local GUI.

The open recording is held in memory as a Session and persisted to its
RecordingStore: every change is one transaction of new clip state plus events.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
import threading
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

from jipandan.core.clip_features import (
    CLIP_FEATURES_VERSION,
    LIKELY_KEEP_VERSION,
    compute_clip_features,
    likely_keep_scores,
)
from jipandan.core.ffmpeg import ExportOptions, probe_duration_seconds, publish_prebuilt_clip
from jipandan.core.leading_silence import detect_leading_silence_start
from jipandan.core.paths import AppPaths, default_export_dir, get_app_paths, resolve_export_dir
from jipandan.core.candidates import candidates_srt_path, is_candidates_srt
from jipandan.core.snap_points import KINDS as SNAP_KINDS, load_snap_points, snap_points_path
from jipandan.core.review_rounds import (
    DEFAULT_SIZE, MAX_SIZE, MIN_SIZE, RANDOM_SHARE, STAT_EVENTS, clip_times, closing_statuses, effective_clips,
    in_pool, pick_round, set_order_key, unprocessed,
)
from jipandan.core.round_files import (
    RoundHistory, audio_sha256, build_round_file, build_update_file, file_kind, imported_round, in_round, match_clips,
    parse_round_file, round_file_path, update_file_path, write_round_file,
)
from jipandan.core.review_rounds import overview as round_overview
from jipandan.core.srt import parse_srt, segment_scores_path
from jipandan.core.whisper import describe_transcribe_call
from jipandan.core.models import ClipCandidate, MIN_CLIP_DURATION_SECONDS, Session
from jipandan.core.store import RecordingStore, StoreConflict, store_path, utc_now
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.web.waveform import MAX_BUCKETS, MAX_WINDOW_MS, MIN_BUCKETS, WaveformCache
from jipandan.web.preview import PreviewJobs
from jipandan.web.transcription import TranscriptionJob, TranscriptionJobs
from jipandan.web.clip_transcription import transcribe_clips
from jipandan.web.review_log import MAX_CLIENT_EVENTS, clean_client_event, clean_context

logger = logging.getLogger(__name__)


class SessionConflict(Exception):
    pass


class SessionNotReady(Exception):
    pass


class InvalidEdit(ValueError):
    pass


class RevealUnavailable(Exception):
    pass


def _time_ms(value: str) -> int:
    return round(srt_time_to_seconds(value.replace(".", ",")) * 1000)


def _view_start_ms(event: dict) -> float:
    """When a view began; a view without a start time was logged as it ended."""
    if "start" in event:
        return datetime.fromisoformat(event["start"]).timestamp() * 1000
    return datetime.fromisoformat(event["t"]).timestamp() * 1000 - event.get("dwell_ms", 0)


def _copy_sidecars(source_srt: Path, destination_srt: Path) -> None:
    """Copy an SRT's segment scores and snap points to sit beside ``destination_srt``."""
    for path in (segment_scores_path, snap_points_path):
        if path(source_srt).is_file():
            shutil.copyfile(path(source_srt), path(destination_srt))


# Events that open and close a review round, or a review set from before rounds.
ROUND_EVENTS = ("review-round", "review-round-complete", "review-set", "review-set-complete")
# Where a new session's clips come from: transcript lines, or the generated candidates SRT.
CLIP_SOURCE_LINES = "lines"
CLIP_SOURCE_GENERATED = "generated"
LEADING_SILENCE_BATCH_SIZE = 25
# Used when this audio was never transcribed in the GUI, so no job settings exist.
DEFAULT_CLIP_TRANSCRIPTION_SETTINGS = {
    "model_name": "large-v3", "language": None, "temperature": 0.0, "max_context": 0, "entropy_thold": 3.0,
}


def clip_payload(candidate: ClipCandidate, likely_keep: float | None = None) -> dict:
    return {
        **asdict(candidate),
        "export_state": candidate.export_state,
        "likely_keep": likely_keep,
        "clip_id": candidate.clip_id,
        "start_ms": _time_ms(candidate.start),
        "end_ms": _time_ms(candidate.end),
        "original_start_ms": _time_ms(candidate.original_start),
        "original_end_ms": _time_ms(candidate.original_end),
    }


class SessionService:
    def __init__(self, clip_dir: Path | None = None, upload_dir: Path | None = None,
                 preview_dir: Path | None = None, transcription_dir: Path | None = None,
                 *, app_paths: AppPaths | None = None) -> None:
        self._lock = threading.RLock()
        self.paths = app_paths or get_app_paths()
        self.audio: Path | None = None
        self.srt: Path | None = None
        self.session: Session | None = None
        self.store: RecordingStore | None = None
        self.duration_ms: int | None = None
        self._clip_dir_override = clip_dir.expanduser().resolve() if clip_dir else None
        self.upload_dir = (upload_dir or self.paths.uploads_dir).expanduser().resolve()
        self._waveforms = WaveformCache()
        self._rounds: list[dict] = []
        self._leading_silence_job: dict[str, object] | None = None
        self._clip_features_job: dict[str, object] | None = None
        self._clip_transcription_job: dict[str, object] | None = None
        self._clip_transcription_process: subprocess.Popen | None = None
        # Snapshot parts reused while their inputs are unchanged; a full snapshot of a
        # 5,000-clip recording is otherwise rebuilt on every key press.
        self._payload_cache: dict[str, tuple[ClipCandidate, dict]] = {}
        # Clips the latest change touched, for delta responses.
        self._last_changed: set[str] = set()
        self._score_cache: tuple[tuple, list[float | None]] | None = None
        self._merge_preview_cache: tuple[tuple, dict] | None = None
        # Re-transcribed titles awaiting review, keyed by clip ID; mirrored in the store.
        # They are not clip state, so a long run never bumps the revision.
        self._title_suggestions: dict[str, str] = {}
        self._previews = PreviewJobs((preview_dir or self.paths.preview_dir).expanduser().resolve())
        self._transcriptions = TranscriptionJobs(
            (transcription_dir or self.paths.transcription_dir).expanduser().resolve(),
            self._publish_transcription,
            log_root=self.paths.transcription_log_dir,
        )

    @property
    def default_clip_dir(self) -> Path:
        if self._clip_dir_override is not None:
            return self._clip_dir_override
        if self.audio is not None:
            return self._new_session_clip_dir(self.audio)
        return self.paths.fallback_export_dir.resolve()

    def _new_session_clip_dir(self, audio: Path) -> Path:
        if self._clip_dir_override is not None:
            return self._clip_dir_override
        return default_export_dir(audio, paths=self.paths)

    def set_export_dir(self, path: str, expected_revision: int | None = None) -> dict:
        """Set the export directory for the active session and future sessions."""

        try:
            selected = resolve_export_dir(path)
        except OSError as exc:
            raise InvalidEdit(str(exc)) from exc

        with self._lock:
            if self.session is None:
                self._clip_dir_override = selected
                return self.snapshot()
            if expected_revision is None:
                raise InvalidEdit("A session revision is required to change its export directory")
            if self.session.clip_dir.resolve() == selected:
                self._clip_dir_override = selected
                return self.snapshot()

            self._check_revision(expected_revision)

            def change(session: Session) -> None:
                session.clip_dir = selected
                if not any(directory.resolve() == selected for directory in session.export_dirs):
                    session.export_dirs.append(selected)

            snapshot, _ = self._mutate(change, [{"type": "export-dir", "to": str(selected)}])
            self._clip_dir_override = selected
            return snapshot

    def default_export_dir_for_current_audio(self) -> dict:
        with self._lock:
            if self.audio is None:
                raise InvalidEdit("Open an audio session before choosing a default export directory")
            return {"clip_dir": str(default_export_dir(self.audio, paths=self.paths))}

    def pick_export_dir(self) -> dict:
        """Open the macOS folder picker and return its selected directory."""

        if sys.platform != "darwin":
            raise InvalidEdit("The native folder picker is only available on macOS")
        script = (
            'set chosenFolder to choose folder with prompt "Choose Jipandan export directory"\n'
            "POSIX path of chosenFolder"
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise InvalidEdit(f"Could not open the macOS folder picker: {exc}") from exc
        if result.returncode != 0:
            if "User canceled" in result.stderr or "-128" in result.stderr:
                return {"path": None, "cancelled": True}
            detail = result.stderr.strip() or "osascript failed"
            raise InvalidEdit(f"Could not choose an export directory: {detail}")
        try:
            selected = resolve_export_dir(result.stdout.strip())
        except OSError as exc:
            raise InvalidEdit(str(exc)) from exc
        return {"path": str(selected), "cancelled": False}

    def start_transcription(self, audio: str, settings: dict) -> dict:
        with self._lock:
            if self.audio is None or str(self.audio) != audio:
                raise SessionConflict("Opened audio changed; reload before transcribing")
            if self.session is not None or (self.srt and self.srt.exists()):
                raise SessionNotReady("This audio already has an SRT or saved session")
            language = settings.get("language") or None
            if language is not None and not re.fullmatch(r"[A-Za-z-]{2,16}", language):
                raise InvalidEdit("Use a short language code such as en or zh")
            try:
                describe_transcribe_call(
                    model_name=settings["model_name"], language=language,
                    temperature=settings["temperature"], max_context=settings["max_context"],
                    entropy_thold=settings["entropy_thold"],
                )
            except (ValueError, KeyError) as exc:
                raise InvalidEdit(str(exc)) from exc
            settings = {**settings, "language": language}
            try:
                return self._transcriptions.start(self.audio, settings)
            except ValueError as exc:
                raise SessionNotReady(str(exc)) from exc

    def transcription(self, job_id: str) -> dict:
        with self._lock:
            job = self._transcriptions.get(job_id)
            if job is None or job["audio"] != str(self.audio):
                raise InvalidEdit("Transcription job not found")
            return job

    def retry_transcription(self, job_id: str) -> dict:
        previous = self.transcription(job_id)
        if previous["state"] not in {"failed", "cancelled"}:
            raise SessionNotReady("Only failed or cancelled jobs can be retried")
        return self.start_transcription(previous["audio"], previous["settings"])

    def cancel_transcription(self, job_id: str) -> dict:
        self.transcription(job_id)
        return self._transcriptions.cancel(job_id)

    def _publish_transcription(self, job: TranscriptionJob) -> int:
        entries = parse_srt(job.output)
        if not entries or len({entry.index for entry in entries}) != len(entries):
            raise ValueError("Transcription did not produce a valid SRT")
        for entry in entries:
            if srt_time_to_seconds(entry.end) <= srt_time_to_seconds(entry.start):
                raise ValueError("Transcription contains invalid clip times")
        destination = job.audio.with_suffix(".srt")
        staged = destination.with_name(f".{destination.name}.{job.id}.tmp")
        generated = job.settings.get("clip_source", CLIP_SOURCE_LINES) == CLIP_SOURCE_GENERATED
        candidates = candidates_srt_path(job.output)
        if generated and not candidates.is_file():
            raise ValueError(
                "No generated clips were saved because voice activity detection failed; "
                "see run.log, or transcribe again with clips from transcript lines"
            )
        with self._lock:
            if destination.exists() or store_path(job.audio).exists():
                raise SessionConflict("An SRT or session was created while transcription ran")
            try:
                with job.output.open("rb") as source, staged.open("wb") as target:
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(staged, destination)
                _copy_sidecars(job.output, destination)
                if candidates.is_file():
                    shutil.copyfile(candidates, candidates_srt_path(destination))
                    _copy_sidecars(candidates, candidates_srt_path(destination))
                source_srt = candidates_srt_path(destination) if generated else destination
                session = Session.from_srt(job.audio, source_srt, self._new_session_clip_dir(job.audio))
                store = RecordingStore(store_path(job.audio))
                store.create(session, load_snap_points(source_srt, session.srt_fingerprint))
            finally:
                staged.unlink(missing_ok=True)
            if self.audio == job.audio:
                self._replace_recording(session, store, source_srt)
            else:
                store.close()
            return len(session.candidates)

    def close(self) -> None:
        self._transcriptions.close()
        self.cancel_clip_transcription()
        with self._lock:
            if self.store is not None:
                self.store.close()
                self.store = None

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
            session = self._ready()
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

    def publish_export(
        self, job_id: str, expected_revision: int, context: object = None, export_all: str | None = None,
    ) -> dict:
        """Publish exactly the reviewed preview and persist its resulting clip state.

        ``export_all`` names the Export all run the export belongs to; the run's exports
        undo together as one step, leaving the exported files in place.
        """
        with self._lock:
            job = self._previews.get(job_id)
            if job is None:
                raise InvalidEdit("Preview not found")
            current = self._ready()
            candidate = current.get_candidate(job.candidate.clip_id)
            if self._previews.is_stale(job, self.audio, candidate):
                raise SessionConflict("Preview is stale; wait for the updated render")
            with job.lock:
                if job.state != "completed" or not job.output.is_file():
                    raise SessionNotReady("Preview is not ready")
            try:
                output = publish_prebuilt_clip(
                    job.output, current.audio, job.candidate, current.clip_dir, job.title,
                )
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                raise SessionNotReady(f"Could not export clip: {exc}") from exc
            def mark_exported(draft: Session) -> None:
                exported = draft.editable(job.candidate.clip_id)
                exported.status = "exported"
                exported.title = job.title
                exported.last_export_title = job.title
                exported.last_export_mode = job.options.mode
                exported.last_export_start_threshold_db = job.options.start_threshold_db
                exported.last_export_stop_threshold_db = job.options.stop_threshold_db
                exported.last_export_path = str(output)
                exported.last_export_snapshot = exported.export_snapshot()

            try:
                result, _ = self._mutate(mark_exported, [{
                    "type": "export", "clip": job.candidate.clip_id, "mode": job.options.mode,
                    "start_threshold_db": job.options.start_threshold_db,
                    "stop_threshold_db": job.options.stop_threshold_db,
                    "title": job.title, "path": str(output), **clean_context(context),
                    **({"export_all": export_all} if export_all else {}),
                }], label="Export all" if export_all else None,
                    undo_group=f"export-all:{export_all}" if export_all else None, undoable=bool(export_all))
            except Exception:
                output.unlink(missing_ok=True)
                raise
            result["output_path"] = str(output)
            return result

    def reveal_export(self, clip_id: str) -> None:
        with self._lock:
            session = self._ready()
            candidate = session.get_candidate(clip_id)
            if candidate is None or not candidate.last_export_path:
                raise InvalidEdit("This clip has no saved export")
            output = Path(candidate.last_export_path).resolve()
            allowed_dirs = session.export_dirs or [session.clip_dir]
            if not any(output.is_relative_to(directory.resolve()) for directory in allowed_dirs) or not output.is_file():
                raise InvalidEdit("Exported file is unavailable")
        self._reveal(output)

    def _reveal(self, output: Path) -> None:
        """Show ``output`` in Finder, or open its folder elsewhere."""
        if sys.platform == "darwin":
            try:
                subprocess.run(["open", "-R", str(output)], check=True, capture_output=True, text=True)
                subprocess.run(
                    ["open", "-a", "/System/Library/CoreServices/Finder.app"],
                    check=True, capture_output=True, text=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                logger.warning("Could not reveal file in Finder: %s", exc)
                raise RevealUnavailable("Could not open Finder from the local server") from exc
        else:
            try:
                subprocess.Popen(["xdg-open", str(output.parent)])
            except OSError as exc:
                raise RevealUnavailable("Could not open the export folder") from exc

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

    def snap_points(self) -> dict[str, list[int]]:
        """Return the recording's clip edge snap points by kind; sessions made before #58 have none."""
        with self._lock:
            self._ready()
            store = self.store
            return {kind: store.snap_points(kind) if store is not None else [] for kind in SNAP_KINDS}

    def leading_silence_detection_status(self) -> dict | None:
        with self._lock:
            job = self._leading_silence_job
            if job is None or job["audio"] != str(self.audio):
                return None
            return {key: value for key, value in job.items() if key != "audio"}

    def start_leading_silence_detection(self) -> dict:
        with self._lock:
            session = self._ready()
            if session.leading_silence_detection_complete:
                return {
                    "id": "completed", "state": "completed", "progress": 0,
                    "total": 0, "adjusted": 0, "error": None,
                }

            existing = self._leading_silence_job
            if (
                existing is not None
                and existing["audio"] == str(session.audio)
                and existing["state"] in {"queued", "running"}
            ):
                return {key: value for key, value in existing.items() if key != "audio"}

            job: dict[str, object] = {
                "id": uuid.uuid4().hex,
                "audio": str(session.audio),
                "srt_fingerprint": session.srt_fingerprint,
                "state": "queued",
                "progress": 0,
                "total": len(session.candidates),
                "adjusted": 0,
                "error": None,
            }
            # While a review round is open its clips go first, in the order the app shows them,
            # so the clips being reviewed are trimmed before the rest of the session.
            roles = self._round_roles
            seed = str(self._open_round["seed"]) if self._open_round else ""
            ordered = sorted(session.candidates, key=lambda candidate: (
                (0, set_order_key(seed, candidate.index)) if str(candidate.index) in roles else (1, 0.0),
                candidate.index, candidate.suffix,
            ))
            clips = [
                (candidate.clip_id, candidate.original_start, _time_ms(candidate.original_start),
                 _time_ms(candidate.end), candidate.start == candidate.original_start)
                for candidate in ordered
            ]
            self._leading_silence_job = job
            threading.Thread(
                target=self._run_leading_silence_detection,
                args=(str(job["id"]), session.audio, session.srt_fingerprint, clips),
                name="jipandan-leading-silence",
                daemon=True,
            ).start()
            return {key: value for key, value in job.items() if key != "audio"}

    def _run_leading_silence_detection(
        self,
        job_id: str,
        audio: Path,
        srt_fingerprint: str | None,
        clips: list[tuple[str, str, int, int, bool]],
    ) -> None:
        proposals: dict[str, tuple[str, int]] = {}
        try:
            with self._lock:
                job = self._leading_silence_job
                if job is None or job["id"] != job_id:
                    return
                job["state"] = "running"

            for position, (clip_id, original_start, start_ms, end_ms, unchanged) in enumerate(clips, 1):
                if unchanged:
                    proposed_start = detect_leading_silence_start(audio, start_ms, end_ms)
                    if proposed_start is not None and proposed_start > start_ms:
                        proposals[clip_id] = (original_start, proposed_start)

                batch_finished = (
                    position % LEADING_SILENCE_BATCH_SIZE == 0 or position == len(clips)
                )
                with self._lock:
                    job = self._leading_silence_job
                    if job is None or job["id"] != job_id:
                        return
                    job["progress"] = position
                    if not batch_finished:
                        continue

                    session = self.session
                    if (
                        self.audio != audio or session is None
                        or session.srt_fingerprint != srt_fingerprint
                    ):
                        job["state"] = "cancelled"
                        return

                    eligible_ids = [
                        candidate_id for candidate_id, (candidate_original, proposed_start) in proposals.items()
                        if (candidate := session.get_candidate(candidate_id)) is not None
                        and candidate.start == candidate.original_start == candidate_original
                        and _time_ms(candidate.end) - proposed_start >= 10
                    ]
                    changed: list[str] = []

                    def apply_proposals(draft: Session) -> None:
                        for candidate_id, (candidate_original, proposed_start) in proposals.items():
                            candidate = draft.get_candidate(candidate_id)
                            if (
                                candidate is None or candidate.start != candidate.original_start
                                or candidate.original_start != candidate_original
                            ):
                                continue
                            end = _time_ms(candidate.end)
                            if proposed_start <= _time_ms(candidate.original_start) or end - proposed_start < 10:
                                continue
                            candidate = draft.editable(candidate_id)
                            candidate.start = seconds_to_ffmpeg_timestamp(proposed_start / 1000)
                            candidate.duration = f"{(end - proposed_start) / 1000:.3f}"
                            changed.append(candidate_id)
                        if position == len(clips):
                            draft.leading_silence_detection_complete = True

                    if eligible_ids or position == len(clips):
                        # A background run the owner did not start: logged, but never an Undo step.
                        self._mutate(
                            apply_proposals, [{"type": "detect-silence", "job": job_id, "clips": changed}],
                            label="Detect leading silence", undo_group=f"leading-silence:{job_id}", undoable=False,
                        )
                    job["adjusted"] = int(job["adjusted"]) + len(changed)
                    proposals.clear()
                    if position == len(clips):
                        job["state"] = "completed"
        except Exception as exc:
            logger.exception("Leading silence detection failed")
            with self._lock:
                job = self._leading_silence_job
                if job is not None and job["id"] == job_id:
                    job["state"] = "failed"
                    job["error"] = str(exc)

    def clip_features_status(self) -> dict | None:
        with self._lock:
            job = self._clip_features_job
            if job is None or job["audio"] != str(self.audio):
                return None
            return {key: value for key, value in job.items() if key != "audio"}

    def start_clip_features(self) -> dict:
        """Measure loudness and tone for clips that lack them, in the background."""
        with self._lock:
            session = self._ready()
            if session.clip_features_complete:
                return {"id": "completed", "state": "completed", "progress": 0, "total": 0, "error": None}
            existing = self._clip_features_job
            if (
                existing is not None
                and existing["audio"] == str(session.audio)
                and existing["state"] in {"queued", "running"}
            ):
                return {key: value for key, value in existing.items() if key != "audio"}
            spans = {
                (candidate.original_start, candidate.original_end): (
                    _time_ms(candidate.original_start) / 1000, _time_ms(candidate.original_end) / 1000,
                )
                for candidate in session.candidates if candidate.peak_db is None
            }
            job: dict[str, object] = {
                "id": uuid.uuid4().hex, "audio": str(session.audio), "state": "queued",
                "progress": 0, "total": len(spans), "error": None,
            }
            self._clip_features_job = job
            threading.Thread(
                target=self._run_clip_features,
                args=(str(job["id"]), session.audio, session.srt_fingerprint, spans),
                name="jipandan-clip-features", daemon=True,
            ).start()
            return {key: value for key, value in job.items() if key != "audio"}

    def _run_clip_features(
        self, job_id: str, audio: Path, srt_fingerprint: str | None,
        spans: dict[tuple[str, str], tuple[float, float]],
    ) -> None:
        def current_job() -> dict[str, object] | None:
            job = self._clip_features_job
            return job if job is not None and job["id"] == job_id else None

        def report(finished: int) -> bool:
            with self._lock:
                job = current_job()
                if job is None:
                    return False
                job["progress"] = finished
                return True

        try:
            with self._lock:
                job = current_job()
                if job is None:
                    return
                job["state"] = "running"
            keys = list(spans)
            measured = dict(zip(keys, compute_clip_features(
                audio, [spans[key] for key in keys], progress=report,
            )))
            with self._lock:
                job = current_job()
                if job is None:
                    return
                session = self.session
                if self.audio != audio or session is None or session.srt_fingerprint != srt_fingerprint:
                    job["state"] = "cancelled"
                    return

                def apply_features(draft: Session) -> None:
                    for position, candidate in enumerate(draft.candidates):
                        features = measured.get((candidate.original_start, candidate.original_end))
                        if candidate.peak_db is None and features is not None:
                            candidate = draft.candidates[position] = copy.copy(candidate)
                            candidate.peak_db = features.peak_db
                            candidate.mid_share_db = features.mid_share_db
                            candidate.bass_share_db = features.bass_share_db
                    draft.clip_features_complete = True
                    draft.clip_features_version = CLIP_FEATURES_VERSION

                # Measurements are not review decisions: saved without an event or undo step.
                self._save_measurements(apply_features)
                job["progress"] = job["total"]
                job["state"] = "completed"
        except Exception as exc:
            logger.exception("Clip feature measurement failed")
            with self._lock:
                job = current_job()
                if job is not None:
                    job["state"] = "failed"
                    job["error"] = str(exc)

    def _set_title_suggestion(self, clip_id: str, title: str | None) -> None:
        if title is None:
            if self._title_suggestions.pop(clip_id, None) is None:
                return
        else:
            self._title_suggestions[clip_id] = title
        if self.store is not None:
            self.store.set_suggestion(clip_id, title)

    def dismiss_title_suggestion(self, clip_id: str) -> dict:
        with self._lock:
            self._ready()
            self._set_title_suggestion(clip_id, None)
            return self.snapshot()

    def clip_transcription_status(self) -> dict | None:
        with self._lock:
            job = self._clip_transcription_job
            if job is None or job["audio"] != str(self.audio):
                return None
            return {key: value for key, value in job.items() if key != "audio"}

    def start_clip_transcription(self, clip_ids: list[str]) -> dict:
        """Re-run Whisper on each clip's own audio to suggest a better title."""
        with self._lock:
            session = self._ready()
            existing = self._clip_transcription_job
            if existing is not None and existing["state"] in {"queued", "running"}:
                raise SessionNotReady("Clips are already being re-transcribed")
            if not clip_ids:
                raise InvalidEdit("Choose at least one clip to re-transcribe")
            positions = {candidate.clip_id: position for position, candidate in enumerate(session.candidates)}
            missing = [clip_id for clip_id in clip_ids if clip_id not in positions]
            if missing:
                raise InvalidEdit(f"Clip not found: {missing[0]}")
            clips = []
            for clip_id in dict.fromkeys(clip_ids):
                position = positions[clip_id]
                candidate = session.candidates[position]
                # The neighbouring title primes Whisper's script and vocabulary
                # without anchoring it to this clip's possibly wrong text.
                previous = session.candidates[position - 1].title if position > 0 else None
                clips.append({
                    "clip_id": clip_id, "start_ms": _time_ms(candidate.start),
                    "end_ms": _time_ms(candidate.end), "prompt": previous,
                })
            latest = self._transcriptions.latest(session.audio)
            settings = {**DEFAULT_CLIP_TRANSCRIPTION_SETTINGS, **(latest["settings"] if latest else {})}
            job: dict[str, object] = {
                "id": uuid.uuid4().hex, "audio": str(session.audio), "state": "queued",
                "progress": 0, "total": len(clips), "clip_ids": [clip["clip_id"] for clip in clips],
                "error": None,
            }
            self._clip_transcription_job = job
            threading.Thread(
                target=self._run_clip_transcription,
                args=(str(job["id"]), session.audio, settings, clips),
                name="jipandan-clip-transcription", daemon=True,
            ).start()
            return {key: value for key, value in job.items() if key != "audio"}

    def cancel_clip_transcription(self) -> dict | None:
        with self._lock:
            job = self._clip_transcription_job
            if job is not None and job["state"] in {"queued", "running"}:
                job["state"] = "cancelled"
                process = self._clip_transcription_process
                if process is not None and process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        return self.clip_transcription_status()

    def _run_clip_transcription(self, job_id: str, audio: Path, settings: dict, clips: list[dict]) -> None:
        def current_job() -> dict[str, object] | None:
            job = self._clip_transcription_job
            return job if job is not None and job["id"] == job_id else None

        def register(process: subprocess.Popen) -> None:
            with self._lock:
                self._clip_transcription_process = process
                job = current_job()
                if job is None or job["state"] == "cancelled":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

        try:
            with self._lock:
                job = current_job()
                if job is None or job["state"] == "cancelled":
                    return
                job["state"] = "running"
            log = self.paths.transcription_log_dir / f"clips-{job_id}.log"
            for clip_id, text in transcribe_clips(audio, settings, clips, log, register):
                with self._lock:
                    job = current_job()
                    if job is None or job["state"] != "running":
                        return
                    if self.audio == audio and text and self.session is not None:
                        candidate = self.session.get_candidate(clip_id)
                        old = self._title_suggestions.get(clip_id)
                        if candidate is not None and candidate.title != text and old != text:
                            self._set_title_suggestion(clip_id, text)
                            # One run of suggestions undoes together.
                            if self.store is not None:
                                self.store.record_suggestion(
                                    clip_id, old, text, {"type": "suggest-title", "job": job_id},
                                    label="Re-transcribe titles", undo_group=f"clip-transcription:{job_id}",
                                )
                    job["progress"] = int(job["progress"]) + 1
            with self._lock:
                job = current_job()
                if job is not None and job["state"] == "running":
                    job["state"] = "completed"
        except Exception as exc:
            logger.exception("Clip re-transcription failed")
            with self._lock:
                job = current_job()
                if job is not None and job["state"] != "cancelled":
                    job["state"] = "failed"
                    job["error"] = str(exc)
        finally:
            with self._lock:
                self._clip_transcription_process = None

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
        database = store_path(resolved)
        legacy = resolved.with_suffix(".jipandan.json")
        if not database.exists() and legacy.exists():
            raise InvalidEdit(
                f"{legacy.name} was saved by an older version of Jipandan. "
                "Move or delete it to start a fresh session from the SRT."
            )
        store: RecordingStore | None = None
        session: Session | None = None
        try:
            if database.exists():
                store = RecordingStore(database)
                session = store.load()
                # A session made from generated clips keeps following their SRT.
                if is_candidates_srt(session.srt):
                    srt = candidates_srt_path(srt)
                session.audio, session.srt = resolved, srt
            elif srt.exists():
                session = Session.from_srt(resolved, srt, self._new_session_clip_dir(resolved))
                store = RecordingStore(database)
                store.create(session, load_snap_points(srt, session.srt_fingerprint))
        except StoreConflict as exc:
            if store is not None:
                store.close()
            raise InvalidEdit(str(exc)) from exc
        with self._lock:
            self.audio = resolved
            self.duration_ms = round(duration * 1000)
            self._replace_recording(session, store, srt)
            return self.snapshot()

    @property
    def _open_round(self) -> dict | None:
        """The round being reviewed, or None between rounds."""
        last = self._rounds[-1] if self._rounds else None
        return last if last and not last["completed"] else None

    @property
    def _round_roles(self) -> dict[str, str]:
        """Round role ("top" or "random") by SRT index, while a round is open."""
        current = self._open_round
        return current["roles"] if current else {}

    def _round_summary(self, session: Session | None) -> dict | None:
        current = self._open_round
        if current is None or session is None:
            return None
        return {
            "number": current["number"], "size": current["size"], "random_share": current["random_share"],
            "seed": current["seed"], "started": current.get("started"),
            "unprocessed": unprocessed(current["roles"], [(c.index, c.status) for c in session.candidates]),
        }

    def review_rounds(self, size: int = DEFAULT_SIZE, random_share: float = RANDOM_SHARE) -> dict:
        """Return earlier rounds and estimates for a next round of ``size`` clips with ``random_share`` random."""
        size = min(MAX_SIZE, max(MIN_SIZE, size))
        random_share = min(1.0, max(0.0, random_share))
        with self._lock:
            session = self._ready()
            scores = self._scores(session)
            clips = [(c.clip_id, c.index, c.status, score) for c, score in zip(session.candidates, scores)]
            events = self.store.events(kinds=STAT_EVENTS) if self.store is not None else []
            rounds = list(self._rounds)
            watched = [item["written_seq"] for item in rounds if item.get("file_version") == 2]
            changed = self.store.changed_after(min(watched)) if watched else []
        result = round_overview(rounds, clips, events, size, random_share)
        for summary, item in zip(result["rounds"], rounds):
            summary["file_version"] = item.get("file_version", 1 if item.get("file") else None)
            summary["unsaved_changes"] = self._unsaved_changes(item, changed)
        return result

    def start_round(self, size: int, random_share: float) -> dict:
        """Open the next review round: the top clips no round has taken yet, plus a random share of them."""
        if not MIN_SIZE <= size <= MAX_SIZE:
            raise InvalidEdit(f"A round holds {MIN_SIZE} to {MAX_SIZE} clips")
        if not 0 <= random_share <= 1:
            raise InvalidEdit("The random share is between 0 and 1")
        with self._lock:
            session = self._ready()
            if self._open_round is not None:
                return self.snapshot()
            if not session.clip_features_complete:
                raise SessionNotReady("Likely keep scores are still being measured")
            scores = self._scores(session)
            effective = effective_clips(self._rounds, [(c.clip_id, c.index, c.status, None) for c in session.candidates])
            allowed = in_pool(self._rounds, [(index, status) for _, index, status, _ in effective])
            pool = [(c.clip_id, c.index, score) for c, score in zip(session.candidates, scores) if c.index in allowed]
            if not pool:
                raise InvalidEdit("Every clip has been reviewed or is in an earlier round")
            picked = pick_round(pool, size, random_share=round(random_share, 2))
            picked.update(number=len(self._rounds) + 1, total=len(session.candidates),
                          score_version=LIKELY_KEEP_VERSION, started=utc_now())
            rounds = [*self._rounds, picked]
            self.store.save_review_rounds(rounds, {
                "type": "review-round", **{key: picked[key] for key in (
                    "number", "size", "pool", "total", "random_share", "seed", "score_version", "sampling",
                    "random_chance", "top", "random")},
            })
            self._rounds = rounds
            return self.snapshot()

    def complete_round(self) -> dict:
        """Close the open round, early if some of its clips are not yet exported or rejected, and write its file.

        Earlier rounds whose clips changed since their files were written get an update file too.
        """
        sha = self._audio_sha256()
        with self._lock:
            session = self._ready()
            current = self._open_round
            if current is None:
                raise InvalidEdit("No review round is open")
            left = unprocessed(current["roles"], [(c.index, c.status) for c in session.candidates])
            completed = {"t": utc_now(), "unprocessed": left}
            closed = closing_statuses(current["roles"], [(c.clip_id, c.index, c.status) for c in session.candidates])
            finished = {**current, "completed": completed, "closed_status": closed,
                        **self._write_round_file(session, {**current, "completed": completed}, sha, ending=True)}
            rounds, updates = self._write_updates(session, sha, [*self._rounds[:-1], finished], exclude=current["number"])
            self.store.save_review_rounds(rounds, {"type": "review-round-complete", "number": current["number"],
                                                   "file": finished.get("file"), "updates": updates, **completed})
            self._rounds = rounds
            return self.snapshot()

    def _audio_sha256(self) -> str | None:
        """The open recording's SHA-256, kept in the session until the audio file changes; None if unreadable."""
        with self._lock:
            session = self._ready()
            audio, store = session.audio, self.store
            cached = store.audio_hash() if store is not None else None
        try:
            stat = audio.stat()
            key = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            if cached and all(cached.get(name) == value for name, value in key.items()):
                return str(cached["sha256"])
            digest = audio_sha256(audio)
        except OSError as exc:
            logger.warning("Could not hash the recording for its round file: %s", exc)
            return None
        with self._lock:
            if self.store is store and store is not None:
                store.save_audio_hash({**key, "sha256": digest})
        return digest

    def _round_seqs(self, item: dict) -> tuple[int, int]:
        """Where a finished round starts and ends in the review history.

        A round opens with its ``review-round`` event and closes just before its ``review-round-complete``
        event (``review-set`` and ``review-set-complete`` for a review set from before rounds); a round
        missing them is placed by its start and end times.
        """
        start = end = None
        for event in self.store.events(kinds=ROUND_EVENTS):
            if event.get("number", 1 if event["type"].startswith("review-set") else None) != item["number"]:
                continue
            if event["type"] in ("review-round", "review-set") and start is None:
                start = event["seq"] - 1
            elif event["type"] in ("review-round-complete", "review-set-complete") and end is None:
                end = event["seq"] - 1
        if start is None:
            start = self.store.seq_at(item["started"]) if item.get("started") else 0
        return start, end if end is not None else self.store.seq_at(item["completed"]["t"])

    def _write_round_file(self, session: Session, item: dict, sha: str | None, *, ending: bool = False) -> dict:
        """Write a finished round's file beside the recording, as the round's part of the review history.

        ``ending`` marks a round being closed now, which ends at the latest event. Returns the round's
        file fields (``file``, ``file_version``, ``written_seq``), or nothing if the file could not be written.
        """
        if sha is None:
            return {}
        start_seq, end_seq = self._round_seqs(item)
        if ending:
            end_seq = self.store.last_seq()
        roles = item["roles"]
        then = self.store.clips_at(start_seq)
        clips = {c.clip_id: asdict(c) for c in session.candidates if in_round(roles, c.clip_id)}
        clips.update({clip_id: clip for clip_id, clip in then.items() if in_round(roles, clip_id)})
        start = {clip_id: clip for clip_id, clip in clips.items() if clip is not None}
        scores = {c.clip_id: score for c, score in zip(session.candidates, self._scores(session))}
        changes, events = self.store.history(start_seq, end_seq)
        # Views delivered after the round ended still count for the part made while it was open,
        # as in its summary; before #106 the last views of a round could arrive late.
        _, late = self.store.history(end_seq, self.store.last_seq())
        ended = datetime.fromisoformat(item["completed"]["t"]).timestamp() * 1000
        events += [event for event in late if event["type"] == "view" and _view_start_ms(event) < ended]
        recording = {"name": session.audio.name, "sha256": sha, "duration_ms": self.duration_ms}
        path = round_file_path(session.audio, item["number"])
        try:
            write_round_file(path, build_round_file(
                item, recording, self._round_source(session), start, scores, changes, events, start_seq, end_seq))
        except OSError as exc:
            logger.warning("Could not write the round file %s: %s", path, exc)
            return {}
        return {"file": path.name, "file_version": 2, "written_seq": end_seq}

    @staticmethod
    def _round_source(session: Session) -> dict:
        return {"clip_source": CLIP_SOURCE_GENERATED if is_candidates_srt(session.srt) else CLIP_SOURCE_LINES,
                "srt_sha256": session.srt_fingerprint, "features_version": session.clip_features_version}

    @staticmethod
    def _unsaved_changes(item: dict, changed: list[tuple[int, list[str]]]) -> int | None:
        """How many changes touched a finished round's clips since its files were written; None without a
        current-format file, as for rounds imported from another project."""
        if not item.get("completed") or item.get("imported") or item.get("file_version") != 2:
            return None
        return sum(1 for seq, clip_ids in changed
                   if seq > item["written_seq"] and any(in_round(item["roles"], clip_id) for clip_id in clip_ids))

    def _write_updates(
        self, session: Session, sha: str | None, rounds: list[dict], *, exclude: int | None = None,
        only: int | None = None,
    ) -> tuple[list[dict], list[str]]:
        """Write an update file for each finished round in ``rounds`` changed since its files were written.

        Returns the rounds with their new update files recorded, and the names written. A round that
        could not be updated keeps its changes unsaved, to be written next time.
        """
        if sha is None:
            return rounds, []
        watched = [item["written_seq"] for item in rounds if item.get("file_version") == 2 and not item.get("imported")]
        if not watched:
            return rounds, []
        changed = self.store.changed_after(min(watched))
        last = self.store.last_seq()
        result, names = [], []
        for item in rounds:
            if item["number"] in (exclude,) or (only is not None and item["number"] != only) \
                    or not self._unsaved_changes(item, changed):
                result.append(item)
                continue
            changes, events = self.store.history(item["written_seq"], last)
            update = len(item.get("updates") or []) + 1
            path = update_file_path(session.audio, item["number"], update)
            try:
                write_round_file(path, build_update_file(item, sha, update, item["written_seq"], last, changes, events))
            except OSError as exc:
                logger.warning("Could not write the update file %s: %s", path, exc)
                result.append(item)
                continue
            names.append(path.name)
            result.append({**item, "updates": [*(item.get("updates") or []), path.name], "written_seq": last})
        return result, names

    def _finished_round(self, number: int) -> dict:
        item = next((item for item in self._rounds if item["number"] == number), None)
        if item is None or not item["completed"]:
            raise InvalidEdit("That round is not finished")
        return item

    def save_round_file(self, number: int) -> dict:
        """Bring a finished round's files up to date.

        A round with no file, or only a file of an older format, gets a file in the current format,
        built from the review history as it was when the round ended; changes to its clips since then
        go into an update file.
        """
        sha = self._audio_sha256()
        with self._lock:
            session = self._ready()
            item = self._finished_round(number)
            if item.get("imported"):
                return self.snapshot()
            rounds = list(self._rounds)
            position = rounds.index(item)
            written = None
            if item.get("file_version") != 2:
                fields = self._write_round_file(session, item, sha)
                if not fields:
                    raise InvalidEdit("The round file could not be written beside the recording")
                written = {**fields, "replaces": item.get("file")}
                rounds[position] = {**item, **fields}
            rounds, updates = self._write_updates(session, sha, rounds, only=number)
            if written is None and not updates:
                return self.snapshot()
            self.store.save_review_rounds(rounds, {"type": "round-file", "number": number,
                                                   "file": (written or {}).get("file"),
                                                   "replaces": (written or {}).get("replaces"), "updates": updates})
            self._rounds = rounds
            return self.snapshot()

    def reveal_round_file(self, number: int) -> None:
        with self._lock:
            session = self._ready()
            name = self._finished_round(number).get("file")
            path = session.audio.with_name(name) if name else None
            if path is None or not path.is_file():
                raise InvalidEdit("The round file is no longer beside the recording")
        self._reveal(path)

    def import_round_files(self, files: list[tuple[str, object]]) -> dict:
        """Add finished rounds from round files of this recording, given as (file name, parsed JSON).

        Clips are matched by time, so the files' clips are skipped by later rounds and their decisions
        count toward the estimates; the clips here stay Unsorted, as their exports are not carried over.
        Of several copies of one round, the one in the newest format is used. Update files are left
        for datasets: a round counts what it found while it was open.
        """
        sha = self._audio_sha256()
        with self._lock:
            session = self._ready()
            if self._open_round is not None:
                raise InvalidEdit("End the open round before importing round files")
            rounds = list(self._rounds)
            imported, skipped = [], []
            parsed: list[tuple[str, int, dict]] = []
            order = {name: position for position, (name, _) in enumerate(files)}
            for name, raw in files:
                if file_kind(raw) == "update":
                    skipped.append({"file": name, "reason": "update files are read by jipandan-dataset, not imported"})
                    continue
                try:
                    version = raw.get("version") if isinstance(raw, dict) else None
                    parsed.append((name, version, parse_round_file(raw)))
                except ValueError as exc:
                    skipped.append({"file": name, "reason": str(exc)})
            newest: dict[str, int] = {}
            for _, version, data in parsed:
                newest[data["round"]["seed"]] = max(newest.get(data["round"]["seed"], 0), version)
            for name, version, data in parsed:
                if sha is None or data["recording"]["sha256"] != sha:
                    skipped.append({"file": name, "reason": "it is from a different recording"})
                    continue
                if version < newest[data["round"]["seed"]]:
                    skipped.append({"file": name, "reason": "a newer copy of this round is in the import"})
                    continue
                if any(item["seed"] == data["round"]["seed"] for item in rounds):
                    skipped.append({"file": name, "reason": "this round is already here"})
                    continue
                history = RoundHistory(data)
                # Like a new round's pool: clips an earlier round left unfinished can still be matched.
                effective = effective_clips(rounds, [(c.clip_id, c.index, c.status, None) for c in session.candidates])
                taken = {index for _, index, status, _ in effective if status != "pending"}
                matches = match_clips(history.file_clips(), [
                    (c.index, _time_ms(c.original_start), _time_ms(c.original_end))
                    for c in session.candidates if c.index not in taken
                ])
                if not matches:
                    skipped.append({"file": name, "reason": "none of its clips match a clip here"})
                    continue
                item = imported_round(history, matches, len(rounds) + 1, name)
                rounds.append(item)
                imported.append({"file": name, "number": item["number"], "from_number": data["round"]["number"],
                                 "matched": len(matches), "unmatched": item["imported"]["unmatched"]})
            if imported:
                self.store.save_review_rounds(rounds, {"type": "review-round-import", "rounds": imported})
                self._rounds = rounds
            skipped.sort(key=lambda entry: order[entry["file"]])
            return {**self.snapshot(), "round_import": {"imported": imported, "skipped": skipped}}

    def _clip_source_srts(self) -> dict[str, Path]:
        """The saved SRTs a new session for the open audio can start from, by clip source."""
        if self.audio is None:
            return {}
        lines = self.audio.with_suffix(".srt")
        sources = {CLIP_SOURCE_LINES: lines, CLIP_SOURCE_GENERATED: candidates_srt_path(lines)}
        return {source: path for source, path in sources.items() if path.is_file()}

    def _clip_sources(self) -> list[str]:
        return list(self._clip_source_srts())

    def start_over(self, expected_revision: int, clip_source: str) -> dict:
        """Replace the open session with a fresh one from a saved SRT, keeping the old one as a backup.

        Decisions, edits, and the review log start empty; exported files and the export directory stay.
        Finished rounds' changes not yet in their files are written to update files first.
        """
        sha = self._audio_sha256()
        with self._lock:
            old = self._check_revision(expected_revision)
            srt = self._clip_source_srts().get(clip_source)
            if srt is None:
                raise InvalidEdit("That transcript is not saved beside the recording")
            rounds, updates = self._write_updates(old, sha, list(self._rounds))
            if updates:
                self.store.save_review_rounds(rounds, {"type": "round-update", "updates": updates})
            database = store_path(old.audio)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = database.with_name(f"{database.name}.{stamp}.bak")
            session = Session.from_srt(old.audio, srt, old.clip_dir)
            self.cancel_clip_transcription()
            # Running jobs check their job id and stop once it is gone.
            self._leading_silence_job = None
            self._clip_features_job = None
            self.store.backup(backup)
            self.store.close()
            for path in (database, database.with_name(f"{database.name}-wal"),
                         database.with_name(f"{database.name}-shm")):
                path.unlink(missing_ok=True)
            store = RecordingStore(database)
            store.create(session, load_snap_points(srt, session.srt_fingerprint))
            self._replace_recording(session, store, srt)
            return {**self.snapshot(), "start_over_backup": str(backup)}

    def _replace_recording(self, session: Session | None, store: RecordingStore | None, srt: Path) -> None:
        if self.store is not None and self.store is not store:
            self.store.close()
        self.srt = srt
        self.session = session
        self.store = store
        self._title_suggestions = store.suggestions() if store is not None else {}
        self._rounds = self._with_closing_statuses(session, store) if store is not None else []
        self._payload_cache.clear()
        self._score_cache = None
        self._merge_preview_cache = None

    @staticmethod
    def _with_closing_statuses(session: Session | None, store: RecordingStore) -> list[dict]:
        """The store's rounds, after saving how each round finished before #103 left its clips.

        Rounds finished before then saved no statuses; they are read back from the review history
        as of each round's end, once, so later decisions stop changing those rounds' results.
        """
        rounds = store.review_rounds()
        missing = [item for item in rounds
                   if item.get("completed") and "closed_status" not in item and not item.get("imported")]
        if session is None or not missing:
            return rounds
        for item in missing:
            then = store.statuses_at(item["completed"]["t"])
            clips = [(c.clip_id, c.index, then.get(c.clip_id, c.status) if c.clip_id in then else c.status)
                     for c in session.candidates]
            item["closed_status"] = closing_statuses(item["roles"], [clip for clip in clips if clip[2] is not None])
        store.save_review_rounds(rounds, {"type": "review-round-outcomes", "rounds": [item["number"] for item in missing]})
        return rounds

    def _scores(self, session: Session) -> list[float | None]:
        signals = tuple(
            (c.clip_id, c.peak_db, c.mid_share_db, c.bass_share_db, c.no_speech_prob) for c in session.candidates
        )
        if self._score_cache is None or self._score_cache[0] != signals:
            self._score_cache = (signals, likely_keep_scores(session.candidates))
        return self._score_cache[1]

    def _clip_payloads(self, session: Session) -> list[dict]:
        scores = self._scores(session)
        cache = self._payload_cache
        payloads = [self._payload(candidate, score) for candidate, score in zip(session.candidates, scores)]
        if len(cache) > len(payloads) + 100:
            current = {c.clip_id for c in session.candidates}
            for clip_id in [key for key in cache if key not in current]:
                del cache[clip_id]
        return payloads

    def _payload(self, candidate: ClipCandidate, score: float | None) -> dict:
        cached = self._payload_cache.get(candidate.clip_id)
        if cached is None or cached[0] is not candidate:
            cached = self._payload_cache[candidate.clip_id] = (candidate, clip_payload(candidate))
        return {**cached[1], "likely_keep": score, "suggested_title": self._title_suggestions.get(candidate.clip_id),
                "round_role": self._round_roles.get(str(candidate.index))}

    def _counts(self, session: Session | None) -> dict[str, int]:
        counts = {name: 0 for name in ("pending", "group1", "group2", "exported", "rejected")}
        for candidate in session.candidates if session else []:
            counts[candidate.status] += 1
        return counts

    def _delta(self) -> dict:
        """Only what the latest change touched, for fast updates of a loaded session."""
        with self._lock:
            session = self._ready()
            scores = dict(zip((c.clip_id for c in session.candidates), self._scores(session)))
            present = {c.clip_id: c for c in session.candidates}
            return {
                "delta": True,
                "revision": session.revision,
                "counts": self._counts(session),
                "can_undo": bool(self.store and self.store.can_undo()),
                "clips": [self._payload(present[i], scores[i]) for i in sorted(self._last_changed) if i in present],
                "removed": sorted(i for i in self._last_changed if i not in present),
            }

    def snapshot(self) -> dict:
        with self._lock:
            session = self.session
            counts = self._counts(session)
            return {
                "audio": str(self.audio) if self.audio else None,
                "audio_name": self.audio.name if self.audio else None,
                "duration_ms": self.duration_ms,
                "srt": str(self.srt) if self.srt else None,
                "srt_exists": bool(self.srt and self.srt.exists()),
                "session_path": str(self.store.path) if session and self.store else None,
                "clip_dir": str(session.clip_dir) if session else str(self.default_clip_dir),
                "srt_fingerprint": session.srt_fingerprint if session else None,
                "leading_silence_detection_complete": (
                    session.leading_silence_detection_complete if session else False
                ),
                "clip_features_complete": session.clip_features_complete if session else False,
                "likely_keep_version": LIKELY_KEEP_VERSION,
                "needs_transcription": bool(self.audio and session is None),
                "transcription": self._latest_transcription(),
                "revision": session.revision if session else None,
                "candidates": self._clip_payloads(session) if session else [],
                "counts": counts,
                "can_undo": bool(self.store and self.store.can_undo()),
                "merge_preview": self.merge_preview() if session and self.srt and self.srt.exists() else None,
                "clip_sources": self._clip_sources(),
                "review_round": self._round_summary(session),
                "rounds_done": sum(1 for item in self._rounds if item["completed"]),
            }

    def event_snapshot(self) -> dict:
        with self._lock:
            return {
                "revision": self.session.revision if self.session else None,
                "transcription": self._latest_transcription(),
            }

    def _latest_transcription(self) -> dict | None:
        """Return this audio's latest transcription job, unless it finished and its transcript is gone."""
        job = self._transcriptions.latest(self.audio)
        # A completed job always opened a session, so with none left its SRT and session were removed,
        # and showing it would hide the form for transcribing again.
        if job is not None and job["state"] == "completed" and self.session is None:
            return None
        return job

    def _ready(self) -> Session:
        if self.session is None:
            raise SessionNotReady("Open audio with an SRT or transcribe it first")
        return self.session

    def _check_revision(self, expected_revision: int) -> Session:
        """Guard changes that depend on what the client saw, such as an SRT merge."""
        session = self._ready()
        if expected_revision != session.revision:
            raise SessionConflict("Session changed; reload before editing")
        return session

    def _commit(self, save: Callable[[RecordingStore, Session], object], draft: Session) -> object:
        store = self.store
        if store is None:
            raise SessionNotReady("Open audio with an SRT or transcribe it first")
        try:
            result = save(store, draft)
        except StoreConflict as exc:
            # Another process wrote to this recording: adopt its state.
            self.session = store.load()
            raise SessionConflict(str(exc)) from exc
        self.session = draft
        return result

    @staticmethod
    def _changed_clips(current: Session, draft: Session) -> dict[str, ClipCandidate | None]:
        """Each clip the change added, removed, or modified, mapped to its prior state."""
        before = {c.clip_id: c for c in current.candidates}
        after = {c.clip_id: c for c in draft.candidates}
        changed = {}
        for clip_id in before.keys() | after.keys():
            old, new = before.get(clip_id), after.get(clip_id)
            # Drafts share untouched clips, so identity rules most out cheaply.
            if old is not new and old != new:
                changed[clip_id] = old
        return changed

    def _mutate(
        self, operation: Callable[[Session], object], events: list[dict] | None = None, *,
        label: str | None = None, undo_group: str | None = None, undoable: bool | None = None,
        undoes: list[int] | None = None, delta: bool = False,
    ) -> tuple[dict, object]:
        """Apply ``operation`` to a copy of the session and save it with ``events``.

        ``events`` may be filled in by ``operation``. The change is undoable when it
        has a label (by default) and actually changed a clip. With ``delta`` the
        response holds only the touched clips instead of the full snapshot.
        """
        with self._lock:
            current = self._ready()
            draft = current.copy_for_edit()
            result = operation(draft)
            before = self._changed_clips(current, draft)
            self._last_changed = set(before)
            if not before and not events:
                return (self._delta() if delta else self.snapshot()), result
            undo = bool(before) and (undoable if undoable is not None else label is not None)
            self._commit(lambda store, d: store.commit(
                d, before, list(events or []), label=label, undo_group=undo_group, undoable=undo, undoes=undoes,
            ), draft)
            return (self._delta() if delta else self.snapshot()), result

    def _save_measurements(self, operation: Callable[[Session], None]) -> None:
        with self._lock:
            current = self._ready()
            draft = current.copy_for_edit()
            operation(draft)
            changed = set(self._changed_clips(current, draft))
            self._commit(lambda store, d: store.update_clips(d, changed), draft)

    def record_review_events(self, events: list[object]) -> int:
        """Store clip views and preview waits reported by the browser; returns how many were new.

        Events already stored under the same ``id`` are skipped, so the browser can send a batch again.
        """
        if len(events) > MAX_CLIENT_EVENTS:
            raise InvalidEdit(f"Send at most {MAX_CLIENT_EVENTS} events at a time")
        with self._lock:
            self._ready()
            cleaned = [event for raw in events if (event := clean_client_event(raw, self.audio)) is not None]
            if self.store is None:
                return len(cleaned)
            return self.store.append_events(cleaned)

    def patch_clip(
        self, clip_id: str, expected_revision: int, *,
        status: str | None = None, title: str | None = None,
        start_ms: int | None = None, end_ms: int | None = None,
        context: object = None, delta: bool = False,
    ) -> dict:
        if all(value is None for value in (status, title, start_ms, end_ms)):
            raise InvalidEdit("No clip change provided")
        if status is not None and status not in {"pending", "group1", "group2", "rejected"}:
            raise InvalidEdit("Invalid status")
        if title is not None and not title.strip():
            raise InvalidEdit("Title cannot be empty")

        events: list[dict] = []
        logged = clean_context(context)

        def change(session: Session) -> None:
            events.clear()
            candidate = session.editable(clip_id)
            if candidate is None:
                raise InvalidEdit("Clip not found")
            if status is not None and status != candidate.status:
                events.append({"type": "status", "clip": clip_id, "from": candidate.status, "to": status, **logged})
            if title is not None and title.strip() != candidate.title:
                events.append({"type": "title", "clip": clip_id, "from": candidate.title, "to": title.strip(), **logged})
            if start_ms is not None or end_ms is not None:
                events.append({
                    "type": "trim", "clip": clip_id,
                    "from_ms": [_time_ms(candidate.start), _time_ms(candidate.end)],
                    "to_ms": [start_ms if start_ms is not None else _time_ms(candidate.start),
                              end_ms if end_ms is not None else _time_ms(candidate.end)],
                    **logged,
                })
            if status is not None:
                candidate.status = status
            if title is not None:
                candidate.title = title.strip()
            if start_ms is not None or end_ms is not None:
                start = start_ms if start_ms is not None else _time_ms(candidate.start)
                end = end_ms if end_ms is not None else _time_ms(candidate.end)
                if start < 0 or end - start < round(MIN_CLIP_DURATION_SECONDS * 1000):
                    raise InvalidEdit("Clip bounds need at least 10 ms of positive duration")
                if self.duration_ms is not None and end > self.duration_ms:
                    raise InvalidEdit("Clip end exceeds audio duration")
                candidate.start = seconds_to_ffmpeg_timestamp(start / 1000)
                candidate.duration = f"{(end - start) / 1000:.3f}"

        with self._lock:
            snapshot, _ = self._mutate(change, events, label=clip_id, delta=delta)
            if title is not None and self._title_suggestions.get(clip_id) == title.strip():
                self._set_title_suggestion(clip_id, None)
                self._last_changed = {clip_id}
                snapshot = self._delta() if delta else self.snapshot()
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

    def duplicate(self, clip_id: str, expected_revision: int, context: object = None, delta: bool = False) -> dict:
        def change(session: Session) -> str:
            duplicate = session.duplicate_candidate(clip_id)
            if duplicate is None:
                raise InvalidEdit("Clip not found")
            return duplicate.clip_id

        events: list[dict] = []

        def change_and_log(session: Session) -> str:
            created = change(session)
            events.append({"type": "duplicate", "clip": clip_id, "created": created, **clean_context(context)})
            return created

        snapshot, result = self._mutate(change_and_log, events, label=clip_id, delta=delta)
        snapshot["created_clip_id"] = result
        return snapshot

    def bulk_reject(
        self, clip_ids: list[str], expected_revision: int, context: object = None, delta: bool = False,
    ) -> dict:
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
            session.bulk_reject(changed)
            return changed

        events: list[dict] = []

        def change_and_log(session: Session) -> list[str]:
            changed = change(session)
            if changed:
                events.append({"type": "bulk-reject", "clips": changed, **clean_context(context)})
            return changed

        snapshot, changed = self._mutate(change_and_log, events, label="Reject clips", delta=delta)
        snapshot["changed_clip_ids"] = changed
        return snapshot

    def undo(self, expected_revision: int, context: object = None, delta: bool = False) -> dict:
        """Revert the latest change the owner made or started (an Export all run counts as one).

        Only the fields the change set go back, so later edits by background runs survive.
        """
        with self._lock:
            self._ready()
            target = self.store.undo_target() if self.store is not None else None
            if target is None:
                raise InvalidEdit("Nothing to undo")

            def restore(session: Session) -> None:
                by_id = {c.clip_id: c for c in session.candidates}
                for clip_id, old in target.restored.items():
                    if old is None:
                        by_id.pop(clip_id, None)
                    elif clip_id in target.fields and clip_id in by_id:
                        clip = copy.deepcopy(by_id[clip_id])
                        for name in target.fields[clip_id]:
                            setattr(clip, name, copy.deepcopy(getattr(old, name)))
                        by_id[clip_id] = clip
                    else:
                        by_id[clip_id] = copy.deepcopy(old)
                session.candidates = sorted(by_id.values(), key=lambda c: (c.index, c.suffix))

            # A suggestion replaced or accepted since stays as it is.
            for clip_id, (old, new) in target.suggestions.items():
                if self._title_suggestions.get(clip_id) == new:
                    self._set_title_suggestion(clip_id, old)

            # Record what each clip went back to, so training sees the corrected decision.
            return self._mutate(restore, [{
                "type": "undo", "label": target.label, "targets": target.seqs,
                "restored": {clip_id: old.status if old else None for clip_id, old in target.restored.items()},
                **clean_context(context),
            }], undoable=False, undoes=target.seqs, delta=delta)[0]

    def merge_preview(self) -> dict | None:
        with self._lock:
            if self.session is None or self.srt is None or not self.srt.exists():
                return None
            session = self.session
            stat = self.srt.stat()
            # Depends only on the SRT file and the session's source entries, which change rarely.
            key = (str(self.srt), stat.st_mtime_ns, stat.st_size, session.srt_fingerprint,
                   tuple((c.clip_id, c.original_start, c.original_end, c.source_text) for c in session.candidates))
            if self._merge_preview_cache is not None and self._merge_preview_cache[0] == key:
                return self._merge_preview_cache[1]
            changes = session.srt_merge_preview()
            fingerprint = hashlib.sha256(self.srt.read_bytes()).hexdigest()
            preview = {
                **changes,
                "affected_clip_ids": [
                    c.clip_id for c in session.candidates
                    if c.index in set(changes["removed"] + changes["timing_changed"] + changes["text_changed"])
                ],
                "unknown_original_text_clip_ids": [
                    c.clip_id for c in session.candidates if c.suffix == 0 and c.source_text is None
                ],
                "srt_fingerprint": fingerprint,
                "file_changed": session.srt_fingerprint != fingerprint,
                # Every stored recording keeps its SRT fingerprint and source text.
                "text_change_unverified": False,
            }
            self._merge_preview_cache = (key, preview)
            return preview

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

            # Undoable as a whole, which replaces the old backup copy of the session file.
            snapshot, warnings = self._mutate(change, [{
                "type": "merge-srt", "srt_fingerprint": srt_fingerprint, "removed": sorted(remove_indexes),
            }], label="Merge SRT changes")
            snapshot["merge_warnings"] = warnings
            return snapshot
