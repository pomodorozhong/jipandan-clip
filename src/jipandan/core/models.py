import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal

from jipandan.core.srt import (
    compute_duration,
    parse_srt,
    srt_time_to_ffmpeg,
    srt_time_to_seconds,
    seconds_to_ffmpeg_timestamp,
)

ClipStatus = Literal["pending", "group1", "group2", "exported", "skipped"]
SESSION_VERSION = 2

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
    # Persist the last export settings used for this clip (if any).
    last_export_title: str | None = None
    last_export_mode: str | None = None
    last_export_start_threshold_db: float | None = None
    last_export_stop_threshold_db: float | None = None

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


def _clip_candidate_from_dict(item: dict) -> ClipCandidate:
    """Build a candidate from session JSON, ignoring unknown legacy keys."""
    return ClipCandidate(
        **{key: value for key, value in item.items() if key in _CLIP_CANDIDATE_FIELD_NAMES}
    )


@dataclass
class Session:
    audio: Path
    srt: Path
    clip_dir: Path
    candidates: list[ClipCandidate] = field(default_factory=list)
    version: int = SESSION_VERSION

    @property
    def session_path(self) -> Path:
        return self.audio.with_suffix(".jipandan.json")

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

        candidates = []
        for entry in entries:
            start = srt_time_to_ffmpeg(entry.start)
            candidates.append(
                ClipCandidate(
                    index=entry.index,
                    title=entry.text,
                    original_start=start,
                    original_end=srt_time_to_ffmpeg(entry.end),
                    start=start,
                    duration=compute_duration(entry.start, entry.end),
                )
            )
        return cls(
            audio=audio.resolve(),
            srt=srt_path.resolve(),
            clip_dir=(clip_dir or Path("clip")).resolve(),
            candidates=candidates,
        )

    @classmethod
    def load(cls, path: Path) -> "Session":
        data = json.loads(path.read_text(encoding="utf-8"))
        candidates = [_clip_candidate_from_dict(item) for item in data["candidates"]]
        for candidate in candidates:
            if candidate.last_export_title:
                candidate.title = candidate.last_export_title
        return cls(
            audio=Path(data["audio"]),
            srt=Path(data["srt"]),
            clip_dir=Path(data["clip_dir"]),
            candidates=candidates,
            version=data.get("version", SESSION_VERSION),
        )

    def save(self) -> None:
        payload = {
            "version": self.version,
            "audio": str(self.audio),
            "srt": str(self.srt),
            "clip_dir": str(self.clip_dir),
            "candidates": [asdict(candidate) for candidate in self.candidates],
        }
        self.session_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def merge_with_srt(self) -> list[str]:
        """Refresh candidates from SRT, preserving status, finetuned times, and duplicates."""
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
                if prior.suffix == 0:
                    merged.append(
                        ClipCandidate(
                            index=fresh_candidate.index,
                            title=prior.title,
                            original_start=fresh_candidate.original_start,
                            original_end=fresh_candidate.original_end,
                            start=prior.start,
                            duration=prior.duration,
                            status=prior.status,
                            suffix=0,
                            last_export_title=prior.last_export_title,
                            last_export_mode=prior.last_export_mode,
                            last_export_start_threshold_db=prior.last_export_start_threshold_db,
                            last_export_stop_threshold_db=prior.last_export_stop_threshold_db,
                        )
                    )
                else:
                    merged.append(
                        ClipCandidate(
                            index=fresh_candidate.index,
                            title=prior.title,
                            original_start=fresh_candidate.original_start,
                            original_end=fresh_candidate.original_end,
                            start=prior.start,
                            duration=prior.duration,
                            status=prior.status,
                            suffix=prior.suffix,
                            last_export_title=prior.last_export_title,
                            last_export_mode=prior.last_export_mode,
                            last_export_start_threshold_db=prior.last_export_start_threshold_db,
                            last_export_stop_threshold_db=prior.last_export_stop_threshold_db,
                        )
                    )

        fresh_indices = {candidate.index for candidate in fresh.candidates}
        removed_indices = [index for index in existing_by_index if index not in fresh_indices]
        if removed_indices:
            warnings.append(f"Removed {len(removed_indices)} candidates no longer in SRT.")

        added = [
            candidate.index
            for candidate in fresh.candidates
            if candidate.index not in {c.index for c in self.candidates}
        ]
        if added:
            warnings.append(f"Added {len(added)} new candidates from SRT.")

        self.candidates = merged
        return warnings

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
            last_export_title=source.last_export_title,
            last_export_mode=source.last_export_mode,
            last_export_start_threshold_db=source.last_export_start_threshold_db,
            last_export_stop_threshold_db=source.last_export_stop_threshold_db,
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

    def bulk_skip(self, clip_ids: list[str]) -> int:
        """Mark pending candidates in clip_ids as skipped. Returns count changed."""
        clip_id_set = set(clip_ids)
        count = 0
        for candidate in self.candidates:
            if candidate.clip_id not in clip_id_set:
                continue
            if candidate.status != "pending":
                continue
            candidate.status = "skipped"
            count += 1
        return count
