"""Score pending clips by how likely they are to be interesting."""

from __future__ import annotations

import numpy as np

from jipandan.core.models import ClipCandidate

# Clips longer than this are progressively deranked.
LONG_DURATION_SECONDS = 10.0

# Typical float32 peak envelope level used to normalize amplitude into [0, 1].
# Quiet/silent clips score near 0; speech-level peaks score near 1.
AMPLITUDE_REFERENCE = 0.08


def average_amplitude(mins: np.ndarray, maxs: np.ndarray) -> float:
    """Mean of per-bucket peak magnitude from a min/max envelope."""
    if mins.size == 0 or maxs.size == 0:
        return 0.0
    return float(np.mean((np.abs(mins) + np.abs(maxs)) * 0.5))


def duration_factor(duration_seconds: float) -> float:
    """Prefer clips at or under ``LONG_DURATION_SECONDS``; decay after that."""
    if duration_seconds <= 0:
        return 0.0
    if duration_seconds <= LONG_DURATION_SECONDS:
        return 1.0
    return LONG_DURATION_SECONDS / duration_seconds


def amplitude_factor(avg_amplitude: float | None) -> float:
    """Derank silence. Missing amplitude is treated as neutral (no penalty)."""
    if avg_amplitude is None:
        return 1.0
    if avg_amplitude <= 0:
        return 0.0
    return min(1.0, avg_amplitude / AMPLITUDE_REFERENCE)


def interest_score(
    duration_seconds: float,
    avg_amplitude: float | None = None,
) -> float:
    """Higher means more likely interesting. Range is roughly [0, 1]."""
    return duration_factor(duration_seconds) * amplitude_factor(avg_amplitude)


def score_candidate(
    candidate: ClipCandidate,
    avg_amplitude: float | None = None,
) -> float:
    return interest_score(float(candidate.duration), avg_amplitude)


def sort_by_interest(
    candidates: list[ClipCandidate],
    *,
    amplitude_for_candidate: dict[str, float | None] | None = None,
) -> list[ClipCandidate]:
    """Return candidates ordered most-interesting first (stable on ties)."""
    amplitudes = amplitude_for_candidate or {}

    def sort_key(candidate: ClipCandidate) -> tuple[float, int, str]:
        score = score_candidate(candidate, amplitudes.get(candidate.clip_id))
        # Negate score for descending; keep index/clip_id for stable order.
        return (-score, candidate.index, candidate.clip_id)

    return sorted(candidates, key=sort_key)
