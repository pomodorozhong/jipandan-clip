"""Framework-independent, revisioned session operations for the local GUI."""

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
import threading
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, Callable

from jipandan.core.clip_features import compute_clip_features, likely_keep_scores
from jipandan.core.ffmpeg import ExportOptions, probe_duration_seconds, publish_prebuilt_clip
from jipandan.core.leading_silence import detect_leading_silence_start
from jipandan.core.paths import AppPaths, default_export_dir, get_app_paths, resolve_export_dir
from jipandan.core.srt import parse_srt, segment_scores_path
from jipandan.core.whisper import describe_transcribe_call
from jipandan.core.models import (
    ClipCandidate,
    ConcurrentSessionChange,
    MIN_CLIP_DURATION_SECONDS,
    Session,
)
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.web.waveform import MAX_BUCKETS, MAX_WINDOW_MS, MIN_BUCKETS, WaveformCache
from jipandan.web.preview import PreviewJobs
from jipandan.web.transcription import TranscriptionJob, TranscriptionJobs
from jipandan.web.clip_transcription import transcribe_clips

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


LEADING_SILENCE_BATCH_SIZE = 25
# Used when this audio was never transcribed in the GUI, so no job settings exist.
DEFAULT_CLIP_TRANSCRIPTION_SETTINGS = {
    "model_name": "large-v3", "language": None, "temperature": 0.0, "max_context": 0, "entropy_thold": 3.0,
}


def clip_payload(candidate: ClipCandidate, likely_keep: float | None = None) -> dict:
    return {
        **asdict(candidate),
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
        self.duration_ms: int | None = None
        self._clip_dir_override = clip_dir.expanduser().resolve() if clip_dir else None
        self.upload_dir = (upload_dir or self.paths.uploads_dir).expanduser().resolve()
        self._undo: list[tuple[str, dict[str, ClipCandidate], str | None]] = []
        self._waveforms = WaveformCache()
        self._leading_silence_job: dict[str, object] | None = None
        self._clip_features_job: dict[str, object] | None = None
        self._clip_transcription_job: dict[str, object] | None = None
        self._clip_transcription_process: subprocess.Popen | None = None
        # Re-transcribed titles awaiting review, keyed by clip ID. They live
        # outside the session so a long run never bumps its revision.
        self._title_suggestions: dict[str, str] = {}
        self._suggestion_dir = (
            (transcription_dir or self.paths.transcription_dir).expanduser().resolve() / "clip-suggestions"
        )
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

            def change(session: Session) -> str:
                session.clip_dir = selected
                if not any(directory.resolve() == selected for directory in session.export_dirs):
                    session.export_dirs.append(selected)
                return "Change export directory"

            snapshot, _ = self._mutate(expected_revision, change)
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
        scores = segment_scores_path(job.output)
        with self._lock:
            if destination.exists() or job.audio.with_suffix(".jipandan.json").exists():
                raise SessionConflict("An SRT or session was created while transcription ran")
            try:
                with job.output.open("rb") as source, staged.open("wb") as target:
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(staged, destination)
                if scores.is_file():
                    shutil.copyfile(scores, segment_scores_path(destination))
                session = Session.from_srt(job.audio, destination, self._new_session_clip_dir(job.audio))
                session.save()
            finally:
                staged.unlink(missing_ok=True)
            if self.audio == job.audio:
                self.srt = destination
                self.session = session
                self._undo.clear()
            return len(entries)

    def close(self) -> None:
        self._transcriptions.close()
        self.cancel_clip_transcription()

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

    def publish_export(self, job_id: str, expected_revision: int) -> dict:
        """Publish exactly the reviewed preview and persist its resulting clip state."""
        with self._lock:
            current = self._check_revision(expected_revision)
            job = self._previews.get(job_id)
            if job is None:
                raise InvalidEdit("Preview not found")
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
            draft = copy.deepcopy(current)
            exported = draft.get_candidate(job.candidate.clip_id)
            exported.status = "exported"
            exported.title = job.title
            exported.last_export_title = job.title
            exported.last_export_mode = job.options.mode
            exported.last_export_start_threshold_db = job.options.start_threshold_db
            exported.last_export_stop_threshold_db = job.options.stop_threshold_db
            exported.last_export_path = str(output)
            try:
                draft.save()
            except Exception as exc:
                output.unlink(missing_ok=True)
                if isinstance(exc, ConcurrentSessionChange):
                    self.session = Session.load(current.session_path)
                    self._undo.clear()
                    raise SessionConflict(str(exc)) from exc
                raise
            self.session = draft
            result = self.snapshot()
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
        if sys.platform == "darwin":
            try:
                subprocess.run(["open", "-R", str(output)], check=True, capture_output=True, text=True)
                subprocess.run(
                    ["open", "-a", "/System/Library/CoreServices/Finder.app"],
                    check=True, capture_output=True, text=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                logger.warning("Could not reveal exported file in Finder: %s", exc)
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
            clips = [
                (candidate.clip_id, candidate.original_start, _time_ms(candidate.original_start),
                 _time_ms(candidate.end), candidate.start == candidate.original_start)
                for candidate in session.candidates
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

                    def apply_proposals(draft: Session) -> str:
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
                            candidate.start = seconds_to_ffmpeg_timestamp(proposed_start / 1000)
                            candidate.duration = f"{(end - proposed_start) / 1000:.3f}"
                            changed.append(candidate_id)
                        if position == len(clips):
                            draft.leading_silence_detection_complete = True
                        return "Detect leading silence"

                    if eligible_ids or position == len(clips):
                        snapshot, _ = self._mutate(
                            session.revision, apply_proposals, undo_ids=eligible_ids,
                            undo_group=f"leading-silence:{job_id}",
                        )
                        del snapshot
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

                def apply_features(draft: Session) -> str:
                    for candidate in draft.candidates:
                        features = measured.get((candidate.original_start, candidate.original_end))
                        if candidate.peak_db is None and features is not None:
                            candidate.peak_db = features.peak_db
                            candidate.mid_share_db = features.mid_share_db
                            candidate.bass_share_db = features.bass_share_db
                    draft.clip_features_complete = True
                    return "Measure clip audio"

                self._mutate(session.revision, apply_features)
                job["progress"] = job["total"]
                job["state"] = "completed"
        except Exception as exc:
            logger.exception("Clip feature measurement failed")
            with self._lock:
                job = current_job()
                if job is not None:
                    job["state"] = "failed"
                    job["error"] = str(exc)

    def _suggestion_path(self, audio: Path) -> Path:
        key = hashlib.sha256(str(audio).encode("utf-8")).hexdigest()[:16]
        return self._suggestion_dir / f"{key}.json"

    def _load_title_suggestions(self, audio: Path) -> dict[str, str]:
        try:
            data = json.loads(self._suggestion_path(audio).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("audio") != str(audio):
            return {}
        suggestions = data.get("suggestions")
        return {str(key): value for key, value in suggestions.items() if isinstance(value, str)} \
            if isinstance(suggestions, dict) else {}

    def _save_title_suggestions(self) -> None:
        if self.audio is None:
            return
        destination = self._suggestion_path(self.audio)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.",
            suffix=".tmp", delete=False,
        ) as handle:
            json.dump({"audio": str(self.audio), "suggestions": self._title_suggestions}, handle, ensure_ascii=False)
        os.replace(handle.name, destination)

    def _drop_title_suggestion(self, clip_id: str) -> None:
        if self._title_suggestions.pop(clip_id, None) is not None:
            self._save_title_suggestions()

    def dismiss_title_suggestion(self, clip_id: str) -> dict:
        with self._lock:
            self._ready()
            self._drop_title_suggestion(clip_id)
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
                        if candidate is not None and candidate.title != text:
                            self._title_suggestions[clip_id] = text
                            self._save_title_suggestions()
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
        session_path = resolved.with_suffix(".jipandan.json")
        if session_path.exists():
            session = Session.load(session_path)
            session.audio = resolved
            session.srt = srt
        elif srt.exists():
            session = Session.from_srt(resolved, srt, self._new_session_clip_dir(resolved))
            session.save()
        else:
            session = None
        with self._lock:
            self.audio = resolved
            self.srt = srt
            self.session = session
            self.duration_ms = round(duration * 1000)
            self._undo.clear()
            self._title_suggestions = self._load_title_suggestions(resolved)
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
                "srt_fingerprint": session.srt_fingerprint if session else None,
                "leading_silence_detection_complete": (
                    session.leading_silence_detection_complete if session else False
                ),
                "clip_features_complete": session.clip_features_complete if session else False,
                "needs_transcription": bool(self.audio and session is None),
                "transcription": self._transcriptions.latest(self.audio),
                "revision": session.revision if session else None,
                "candidates": [
                    {**clip_payload(candidate, score),
                     "suggested_title": self._title_suggestions.get(candidate.clip_id)}
                    for candidate, score in zip(session.candidates, likely_keep_scores(session.candidates))
                ] if session else [],
                "counts": counts,
                "can_undo": bool(self._undo),
                "merge_preview": self.merge_preview() if session and self.srt and self.srt.exists() else None,
            }

    def event_snapshot(self) -> dict:
        with self._lock:
            return {
                "revision": self.session.revision if self.session else None,
                "transcription": self._transcriptions.latest(self.audio),
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
        *, undo_ids: list[str] | None = None, undo_group: str | None = None,
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
                if undo_group is not None and self._undo and self._undo[-1][2] == undo_group:
                    label, grouped_before, group_id = self._undo[-1]
                    for clip_id, candidate in before.items():
                        grouped_before.setdefault(clip_id, candidate)
                    self._undo[-1] = (label, grouped_before, group_id)
                else:
                    self._undo.append((str(result), before, undo_group))
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
        if title is not None:
            with self._lock:
                if self._title_suggestions.get(clip_id) == title.strip():
                    self._drop_title_suggestion(clip_id)
                    snapshot = self.snapshot()
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
            label, before, _ = self._undo[-1]

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
