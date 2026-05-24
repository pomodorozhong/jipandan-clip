import json
from dataclasses import asdict, dataclass, field
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
SESSION_VERSION = 1


@dataclass
class ClipCandidate:
    index: int
    title: str
    original_start: str
    original_end: str
    start: str
    duration: str
    status: ClipStatus = "pending"

    @property
    def end(self) -> str:
        end_seconds = srt_time_to_seconds(self.start.replace(".", ",")) + float(self.duration)
        return seconds_to_ffmpeg_timestamp(end_seconds)

    def start_offset_seconds(self) -> float:
        return srt_time_to_seconds(self.start.replace(".", ",")) - srt_time_to_seconds(
            self.original_start.replace(".", ",")
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
        candidates = [ClipCandidate(**item) for item in data["candidates"]]
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
        """Refresh candidates from SRT, preserving status and finetuned times where possible."""
        warnings: list[str] = []
        fresh = Session.from_srt(self.audio, self.srt, self.clip_dir)
        existing = {candidate.index: candidate for candidate in self.candidates}
        merged: list[ClipCandidate] = []

        for candidate in fresh.candidates:
            prior = existing.get(candidate.index)
            if prior is None:
                merged.append(candidate)
                continue
            merged.append(
                ClipCandidate(
                    index=candidate.index,
                    title=candidate.title,
                    original_start=candidate.original_start,
                    original_end=candidate.original_end,
                    start=prior.start,
                    duration=prior.duration,
                    status=prior.status,
                )
            )

        fresh_indices = {candidate.index for candidate in fresh.candidates}
        removed = [index for index in existing if index not in fresh_indices]
        if removed:
            warnings.append(f"Removed {len(removed)} candidates no longer in SRT.")

        added = [candidate.index for candidate in fresh.candidates if candidate.index not in existing]
        if added:
            warnings.append(f"Added {len(added)} new candidates from SRT.")

        self.candidates = merged
        return warnings

    def get_candidate(self, index: int) -> ClipCandidate | None:
        for candidate in self.candidates:
            if candidate.index == index:
                return candidate
        return None

    def nudge_start(self, index: int, delta_seconds: float) -> None:
        candidate = self.get_candidate(index)
        if candidate is None:
            return
        start_seconds = srt_time_to_seconds(candidate.start.replace(".", ","))
        end_seconds = start_seconds + float(candidate.duration)
        nudged_start = min(end_seconds, start_seconds + delta_seconds)
        candidate.start = seconds_to_ffmpeg_timestamp(nudged_start)
        candidate.duration = f"{max(0.0, end_seconds - nudged_start):.3f}"

    def nudge_end(self, index: int, delta_seconds: float) -> None:
        candidate = self.get_candidate(index)
        if candidate is None:
            return
        duration = max(0.0, float(candidate.duration) + delta_seconds)
        candidate.duration = f"{duration:.3f}"

    def bulk_skip(self, indices: list[int]) -> int:
        """Mark pending candidates in indices as skipped. Returns count changed."""
        index_set = set(indices)
        count = 0
        for candidate in self.candidates:
            if candidate.index not in index_set:
                continue
            if candidate.status != "pending":
                continue
            candidate.status = "skipped"
            count += 1
        return count
