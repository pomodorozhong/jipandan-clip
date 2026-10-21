"""Clip candidates cut at pauses in speech, from voice activity and Whisper word timings."""

from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass
from pathlib import Path

# Voice activity for candidates uses a lower threshold than snap points: on 0602 it found more
# kept clips at every edge tolerance, since kept clips keep quiet speech at their edges.
SPEECH_THRESHOLD = 0.3
# Kept clips start a little before speech: the median start is 0.16 s before the onset.
LEAD_MS = 200
# A Whisper segment edge moves to a voice-activity edge this close to it.
START_SNAP_MS = 500
END_SNAP_MS = 1000
# 1–99% of kept clips on 0602 are 0.5–5.4 s long.
MIN_LENGTH_MS = 600
MAX_LENGTH_MS = 5000


def candidates_srt_path(srt_path: Path) -> Path:
    """SRT holding the candidates generated while transcribing ``srt_path``."""
    return srt_path.with_name(f"{srt_path.stem}.candidates.srt")


def is_candidates_srt(srt_path: Path) -> bool:
    return srt_path.name.endswith(".candidates.srt")


@dataclass(frozen=True)
class Word:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Candidate:
    start_ms: int
    end_ms: int
    text: str


def words_from_segments(segments: list[dict]) -> list[Word]:
    """Return every timed word in Whisper ``segments``, in time order."""
    words: list[Word] = []
    for segment in segments:
        for word in segment.get("words") or []:
            try:
                start, end = float(word["start"]), float(word["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end < start:
                continue
            words.append(Word(round(start * 1000), round(end * 1000), str(word.get("word", ""))))
    words.sort(key=lambda word: (word.start_ms, word.end_ms))
    return words


def _nearest(points: list[int], value: int, limit: int) -> int:
    """Return the point in sorted ``points`` nearest ``value`` if within ``limit``, else ``value``."""
    index = bisect.bisect_left(points, value)
    near = [points[i] for i in (index - 1, index) if 0 <= i < len(points)]
    best = min(near, key=lambda point: abs(point - value), default=value)
    return best if abs(best - value) <= limit else value


def _text(words: list[Word], word_starts: list[int], start: int, end: int) -> str:
    """Join the words that lie mostly between ``start`` and ``end``."""
    first = bisect.bisect_left(word_starts, start - 30_000)
    inside = []
    for word in words[first:]:
        if word.start_ms >= end:
            break
        if min(word.end_ms, end) - max(word.start_ms, start) >= (word.end_ms - word.start_ms) / 2:
            inside.append(word.text)
    return "".join(inside).strip()


def generate_candidates(
    segments: list[dict],
    speech_runs: list[tuple[int, int]],
    *,
    lead_ms: int = LEAD_MS,
    start_snap_ms: int = START_SNAP_MS,
    end_snap_ms: int = END_SNAP_MS,
    min_length_ms: int = MIN_LENGTH_MS,
    max_length_ms: int = MAX_LENGTH_MS,
) -> list[Candidate]:
    """Return candidates from voice-activity runs and Whisper ``segments``, in time order.

    Each run of voice activity that Whisper heard words in is a candidate, starting
    ``lead_ms`` before the speech. Runs miss clips inside long stretches of speech, so each
    Whisper segment is a candidate too, with its edges moved to nearby voice-activity edges:
    Whisper word ends trail off, while voice activity ends where kept clips end.
    """
    words = words_from_segments(segments)
    word_starts = [word.start_ms for word in words]
    runs = sorted(speech_runs)
    onsets = [max(0, start - lead_ms) for start, _ in runs]
    offsets = sorted(end for _, end in runs)

    # The latest end of any word starting at or before each word, to find words overlapping a run.
    latest_ends = list(itertools.accumulate((word.end_ms for word in words), max))

    bounds: set[tuple[int, int]] = set()
    for start, end in runs:
        index = bisect.bisect_left(word_starts, end)
        if index and latest_ends[index - 1] > start:
            bounds.add((max(0, start - lead_ms), end))
    for segment in segments:
        segment_words = words_from_segments([segment])
        if not segment_words:
            continue
        try:
            end = round(float(segment["end"]) * 1000)
        except (KeyError, TypeError, ValueError):
            continue
        bounds.add((
            _nearest(onsets, segment_words[0].start_ms, start_snap_ms),
            _nearest(offsets, end, end_snap_ms),
        ))
    return [
        Candidate(start, end, _text(words, word_starts, start, end))
        for start, end in sorted(bounds)
        if min_length_ms <= end - start <= max_length_ms
    ]


def best_segments(segments: list[dict], candidates: list[Candidate]) -> list[dict]:
    """Return, for each candidate, the Whisper segment that overlaps it most (or the nearest)."""
    ordered = sorted(segments, key=lambda segment: float(segment["start"]))
    starts = [round(float(segment["start"]) * 1000) for segment in ordered]
    ends = [round(float(segment["end"]) * 1000) for segment in ordered]
    matched = []
    for candidate in candidates:
        high = bisect.bisect_left(starts, candidate.end_ms)
        # Segments are short and rarely nest, so the few before the candidate's end are enough.
        nearby = range(max(0, high - 20), min(len(ordered), high + 1))
        best = max(
            nearby,
            key=lambda i: (
                min(ends[i], candidate.end_ms) - max(starts[i], candidate.start_ms),
                -abs(starts[i] - candidate.start_ms),
            ),
        )
        matched.append(ordered[best])
    return matched
