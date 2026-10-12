import copy
import hashlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Literal

from jipandan.core.srt import (
    compute_duration,
    load_segment_scores,
    parse_srt,
    srt_time_to_ffmpeg,
    srt_time_to_seconds,
    seconds_to_ffmpeg_timestamp,
)
from jipandan.core.paths import default_export_dir

# "unsure" records a deliberate "can't decide", distinct from a clip nobody reviewed yet.
ClipStatus = Literal["pending", "group1", "group2", "exported", "rejected", "unsure"]

# When an operation collapses a clip to zero duration (start == end), the end is
# pushed out by this many seconds so the clip remains usable.
ZERO_DURATION_BUMP_SECONDS = 1.0
MIN_CLIP_DURATION_SECONDS = 0.01


@dataclass
class ClipCandidate:
    index: int
    title: str
    original_start: str
    original_end: str
    start: str
    duration: str
    status: ClipStatus = "pending"
    # 0 for the original SRT-derived clip, 2+ for duplicates ("144-2", "144-3", ...).
    suffix: int = 0
    source_text: str | None = None
    # Persist the last export settings used for this clip (if any).
    last_export_title: str | None = None
    last_export_mode: str | None = None
    last_export_start_threshold_db: float | None = None
    last_export_stop_threshold_db: float | None = None
    last_export_path: str | None = None
    last_export_snapshot: dict | None = None
    # Review-ordering signals measured on the original SRT span.
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    peak_db: float | None = None
    mid_share_db: float | None = None
    bass_share_db: float | None = None

    def export_snapshot(self) -> dict:
        """The clip and render settings that a saved file must match."""
        return {
            "title": self.title,
            "start_ms": round(srt_time_to_seconds(self.start.replace(".", ",")) * 1000),
            "end_ms": round(srt_time_to_seconds(self.end.replace(".", ",")) * 1000),
            "mode": self.last_export_mode,
            "start_threshold_db": self.last_export_start_threshold_db if self.last_export_mode != "as_is" else None,
            "stop_threshold_db": self.last_export_stop_threshold_db if self.last_export_mode != "as_is" else None,
        }

    @property
    def export_state(self) -> str:
        if not self.last_export_path:
            return "none"
        if self.last_export_snapshot is None:
            return "unknown"
        return "matching" if self.last_export_snapshot == self.export_snapshot() else "changed"

    @property
    def clip_id(self) -> str:
        if self.suffix == 0:
            return str(self.index)
        return f"{self.index}-{self.suffix}"

    @property
    def filename_token(self) -> str:
        if self.suffix == 0:
            return f"{self.index:04d}"
        return f"{self.index:04d}-{self.suffix}"

    @property
    def end(self) -> str:
        end_seconds = srt_time_to_seconds(self.start.replace(".", ",")) + float(self.duration)
        return seconds_to_ffmpeg_timestamp(end_seconds)

    def start_offset_seconds(self) -> float:
        return srt_time_to_seconds(self.start.replace(".", ",")) - srt_time_to_seconds(
            self.original_start.replace(".", ",")
        )

    def end_offset_seconds(self) -> float:
        return srt_time_to_seconds(self.end.replace(".", ",")) - srt_time_to_seconds(
            self.original_end.replace(".", ",")
        )


_CLIP_CANDIDATE_FIELD_NAMES = {f.name for f in fields(ClipCandidate)}
_SCORE_FIELD_NAMES = ("avg_logprob", "no_speech_prob", "peak_db", "mid_share_db", "bass_share_db")


def _carried_scores(prior: ClipCandidate, fresh: ClipCandidate) -> dict[str, float | None]:
    """Keep measured signals only while the original SRT span is unchanged."""
    if (prior.original_start, prior.original_end) != (fresh.original_start, fresh.original_end):
        return {name: getattr(fresh, name) for name in _SCORE_FIELD_NAMES}
    return {
        name: getattr(fresh, name) if getattr(fresh, name) is not None else getattr(prior, name)
        for name in _SCORE_FIELD_NAMES
    }


def clip_candidate_from_dict(item: dict) -> ClipCandidate:
    """Build a candidate from stored JSON, ignoring unknown keys."""
    return ClipCandidate(
        **{key: value for key, value in item.items() if key in _CLIP_CANDIDATE_FIELD_NAMES}
    )


@dataclass
class Session:
    """The current state of one recording's review, held in memory.

    Persistence lives in jipandan.core.store; ``revision`` mirrors the store's.
    """

    audio: Path
    srt: Path
    clip_dir: Path
    export_dirs: list[Path] = field(default_factory=list)
    candidates: list[ClipCandidate] = field(default_factory=list)
    revision: int = 0
    srt_fingerprint: str | None = None
    leading_silence_detection_complete: bool = False
    clip_features_complete: bool = False
    clip_features_version: int | None = None

    @classmethod
    def from_srt(
        cls,
        audio: Path,
        srt_path: Path,
        clip_dir: Path | None = None,
    ) -> "Session":
        entries = parse_srt(srt_path)
        if not entries:
            raise ValueError(f"No valid subtitle entries found in {srt_path}")

        fingerprint = hashlib.sha256(srt_path.read_bytes()).hexdigest()
        scores = load_segment_scores(srt_path, fingerprint)
        candidates = []
        for entry in entries:
            start = srt_time_to_ffmpeg(entry.start)
            segment = scores.get(entry.index, {})
            candidates.append(
                ClipCandidate(
                    index=entry.index,
                    title=entry.text,
                    original_start=start,
                    original_end=srt_time_to_ffmpeg(entry.end),
                    start=start,
                    duration=compute_duration(entry.start, entry.end),
                    source_text=entry.text,
                    avg_logprob=segment.get("avg_logprob"),
                    no_speech_prob=segment.get("no_speech_prob"),
                )
            )
        resolved_audio = audio.resolve()
        resolved_clip_dir = (clip_dir or default_export_dir(resolved_audio)).resolve()
        return cls(
            audio=resolved_audio,
            srt=srt_path.resolve(),
            clip_dir=resolved_clip_dir,
            export_dirs=[resolved_clip_dir],
            candidates=candidates,
            srt_fingerprint=fingerprint,
        )

    def srt_merge_preview(self) -> dict[str, list[int]]:
        """Describe SRT changes without changing the saved session."""
        fresh = Session.from_srt(self.audio, self.srt, self.clip_dir)
        current = {c.index: c for c in self.candidates if c.suffix == 0}
        incoming = {c.index: c for c in fresh.candidates}
        return {
            "added": sorted(incoming.keys() - current.keys()),
            "removed": sorted(current.keys() - incoming.keys()),
            "timing_changed": sorted(
                index for index in current.keys() & incoming.keys()
                if (current[index].original_start, current[index].original_end)
                != (incoming[index].original_start, incoming[index].original_end)
            ),
            "text_changed": sorted(
                index for index in current.keys() & incoming.keys()
                if current[index].source_text is not None
                and current[index].source_text != incoming[index].source_text
            ),
        }

    def merge_with_srt(
        self, *, remove_missing: bool = False, remove_missing_indexes: set[int] | None = None
    ) -> list[str]:
        """Refresh candidates from SRT, preserving status, finetuned times, and duplicates.

        Removed entries stay recoverable through the store's undo history.
        """
        warnings: list[str] = []
        fresh = Session.from_srt(self.audio, self.srt, self.clip_dir)
        existing_by_index: dict[int, list[ClipCandidate]] = {}
        for candidate in self.candidates:
            existing_by_index.setdefault(candidate.index, []).append(candidate)
        merged: list[ClipCandidate] = []

        for fresh_candidate in fresh.candidates:
            group = existing_by_index.pop(fresh_candidate.index, None)
            if group is None:
                merged.append(fresh_candidate)
                continue
            for prior in group:
                unchanged_bounds = (
                    prior.start == prior.original_start
                    and prior.end == prior.original_end
                )
                merged_start = fresh_candidate.start if unchanged_bounds else prior.start
                merged_duration = fresh_candidate.duration if unchanged_bounds else prior.duration
                merged_title = (
                    fresh_candidate.title
                    if prior.source_text is not None and prior.title == prior.source_text
                    else prior.title
                )
                if prior.suffix == 0:
                    merged.append(
                        ClipCandidate(
                            index=fresh_candidate.index,
                            title=merged_title,
                            original_start=fresh_candidate.original_start,
                            original_end=fresh_candidate.original_end,
                            start=merged_start,
                            duration=merged_duration,
                            status=prior.status,
                            suffix=0,
                            source_text=fresh_candidate.source_text,
                            last_export_title=prior.last_export_title,
                            last_export_mode=prior.last_export_mode,
                            last_export_start_threshold_db=prior.last_export_start_threshold_db,
                            last_export_stop_threshold_db=prior.last_export_stop_threshold_db,
                            last_export_path=prior.last_export_path,
                            last_export_snapshot=copy.deepcopy(prior.last_export_snapshot),
                            **_carried_scores(prior, fresh_candidate),
                        )
                    )
                else:
                    merged.append(
                        ClipCandidate(
                            index=fresh_candidate.index,
                            title=merged_title,
                            original_start=fresh_candidate.original_start,
                            original_end=fresh_candidate.original_end,
                            start=merged_start,
                            duration=merged_duration,
                            status=prior.status,
                            suffix=prior.suffix,
                            source_text=fresh_candidate.source_text,
                            last_export_title=prior.last_export_title,
                            last_export_mode=prior.last_export_mode,
                            last_export_start_threshold_db=prior.last_export_start_threshold_db,
                            last_export_stop_threshold_db=prior.last_export_stop_threshold_db,
                            last_export_path=prior.last_export_path,
                            last_export_snapshot=copy.deepcopy(prior.last_export_snapshot),
                            **_carried_scores(prior, fresh_candidate),
                        )
                    )

        fresh_indices = {candidate.index for candidate in fresh.candidates}
        removed_indices = [index for index in existing_by_index if index not in fresh_indices]
        if removed_indices:
            removed = set(removed_indices) if remove_missing else (remove_missing_indexes or set())
            if removed:
                warnings.append(f"Removed {len(removed & set(removed_indices))} SRT entries.")
            for index, group in existing_by_index.items():
                if index not in removed:
                    merged.extend(group)
            merged.sort(key=lambda candidate: (candidate.index, candidate.suffix))
            kept = len(set(removed_indices) - removed)
            if kept:
                warnings.append(f"Kept {kept} entries absent from SRT.")

        added = [
            candidate.index
            for candidate in fresh.candidates
            if candidate.index not in {c.index for c in self.candidates}
        ]
        if added:
            warnings.append(f"Added {len(added)} new candidates from SRT.")

        self.candidates = merged
        self.srt_fingerprint = fresh.srt_fingerprint
        self.leading_silence_detection_complete = False
        self.clip_features_complete = False
        self.clip_features_version = None
        return warnings

    def copy_for_edit(self) -> "Session":
        """A copy that shares unchanged clips; edit clips through ``editable``.

        Copying only what a change touches keeps edits fast on recordings with
        thousands of clips, and lets callers spot changed clips by identity.
        """
        draft = copy.copy(self)
        draft.candidates = list(self.candidates)
        draft.export_dirs = list(self.export_dirs)
        return draft

    def editable(self, clip_id: str) -> ClipCandidate | None:
        """Replace the clip with a private copy and return it for editing."""
        position = self._find_position(clip_id)
        if position is None:
            return None
        self.candidates[position] = copy.copy(self.candidates[position])
        return self.candidates[position]

    def get_candidate(self, clip_id: str) -> ClipCandidate | None:
        for candidate in self.candidates:
            if candidate.clip_id == clip_id:
                return candidate
        return None

    def _find_position(self, clip_id: str) -> int | None:
        for position, candidate in enumerate(self.candidates):
            if candidate.clip_id == clip_id:
                return position
        return None

    def duplicate_candidate(self, clip_id: str) -> ClipCandidate | None:
        """Duplicate the clip identified by clip_id, inserted immediately after it."""
        position = self._find_position(clip_id)
        if position is None:
            return None
        source = self.candidates[position]
        existing_suffixes = {
            candidate.suffix
            for candidate in self.candidates
            if candidate.index == source.index
        }
        new_suffix = 2
        while new_suffix in existing_suffixes:
            new_suffix += 1
        # The duplicate has no exported file yet; demote "exported" to "pending".
        duplicate_status: ClipStatus = (
            "pending" if source.status == "exported" else source.status
        )
        duplicate = ClipCandidate(
            index=source.index,
            title=source.title,
            original_start=source.original_start,
            original_end=source.original_end,
            start=source.start,
            duration=source.duration,
            status=duplicate_status,
            suffix=new_suffix,
            source_text=source.source_text,
            last_export_title=source.last_export_title,
            last_export_mode=source.last_export_mode,
            last_export_start_threshold_db=source.last_export_start_threshold_db,
            last_export_stop_threshold_db=source.last_export_stop_threshold_db,
            **{name: getattr(source, name) for name in _SCORE_FIELD_NAMES},
        )
        last_sibling_position = position
        for offset in range(position + 1, len(self.candidates)):
            if self.candidates[offset].index == source.index:
                last_sibling_position = offset
            else:
                break
        self.candidates.insert(last_sibling_position + 1, duplicate)
        return duplicate

    @staticmethod
    def _ensure_nonzero_duration(candidate: ClipCandidate) -> None:
        """When start == end, push the end out by ``ZERO_DURATION_BUMP_SECONDS``."""
        if float(candidate.duration) <= 0.0:
            candidate.duration = f"{ZERO_DURATION_BUMP_SECONDS:.3f}"

    def set_trim_offsets(
        self,
        clip_id: str,
        start_offset_seconds: float,
        end_offset_seconds: float,
    ) -> None:
        """Set clip bounds from original SRT times plus signed offsets in seconds."""
        candidate = self.get_candidate(clip_id)
        if candidate is None:
            return
        original_start = srt_time_to_seconds(candidate.original_start.replace(".", ","))
        original_end = srt_time_to_seconds(candidate.original_end.replace(".", ","))
        new_start = max(0.0, original_start + start_offset_seconds)
        new_end = max(0.0, original_end + end_offset_seconds)
        if new_start > new_end:
            new_start = new_end
        candidate.start = seconds_to_ffmpeg_timestamp(new_start)
        candidate.duration = f"{max(0.0, new_end - new_start):.3f}"
        self._ensure_nonzero_duration(candidate)

    def nudge_start(self, clip_id: str, delta_seconds: float) -> None:
        candidate = self.get_candidate(clip_id)
        if candidate is None:
            return
        start_seconds = srt_time_to_seconds(candidate.start.replace(".", ","))
        end_seconds = start_seconds + float(candidate.duration)
        latest_start = max(0.0, end_seconds - MIN_CLIP_DURATION_SECONDS)
        nudged_start = start_seconds + delta_seconds
        nudged_start = max(0.0, min(latest_start, nudged_start))
        candidate.start = seconds_to_ffmpeg_timestamp(nudged_start)
        candidate.duration = f"{max(0.0, end_seconds - nudged_start):.3f}"
        self._ensure_nonzero_duration(candidate)

    def nudge_end(self, clip_id: str, delta_seconds: float) -> None:
        candidate = self.get_candidate(clip_id)
        if candidate is None:
            return
        duration = max(
            MIN_CLIP_DURATION_SECONDS,
            float(candidate.duration) + delta_seconds,
        )
        candidate.duration = f"{duration:.3f}"
        self._ensure_nonzero_duration(candidate)

    def bulk_reject(self, clip_ids: list[str]) -> int:
        """Mark pending candidates in clip_ids as rejected. Returns count changed."""
        count = 0
        for clip_id in dict.fromkeys(clip_ids):
            candidate = self.get_candidate(clip_id)
            if candidate is None or candidate.status != "pending":
                continue
            self.editable(clip_id).status = "rejected"
            count += 1
        return count
