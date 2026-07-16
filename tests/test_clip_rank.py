"""Unit tests for smart clip ranking."""

from __future__ import annotations

import unittest

import numpy as np

from jipandan.core.clip_rank import (
    LONG_DURATION_SECONDS,
    amplitude_factor,
    average_amplitude,
    duration_factor,
    interest_score,
    score_candidate,
    sort_by_interest,
)
from jipandan.core.models import ClipCandidate


def _candidate(
    index: int,
    *,
    duration: str,
    status: str = "pending",
) -> ClipCandidate:
    return ClipCandidate(
        index=index,
        title=f"clip {index}",
        original_start="00:00:00.000",
        original_end="00:00:01.000",
        start="00:00:00.000",
        duration=duration,
        status=status,  # type: ignore[arg-type]
    )


class ClipRankTests(unittest.TestCase):
    def test_average_amplitude_from_envelope(self) -> None:
        mins = np.array([-0.2, -0.1, 0.0], dtype=np.float64)
        maxs = np.array([0.2, 0.1, 0.0], dtype=np.float64)
        self.assertAlmostEqual(average_amplitude(mins, maxs), 0.1)

    def test_average_amplitude_empty(self) -> None:
        empty = np.zeros(0, dtype=np.float64)
        self.assertEqual(average_amplitude(empty, empty), 0.0)

    def test_duration_factor_deranks_long_clips(self) -> None:
        self.assertEqual(duration_factor(5.0), 1.0)
        self.assertEqual(duration_factor(LONG_DURATION_SECONDS), 1.0)
        self.assertLess(duration_factor(20.0), duration_factor(10.0))
        self.assertLess(duration_factor(30.0), duration_factor(20.0))

    def test_amplitude_factor_deranks_silence(self) -> None:
        self.assertEqual(amplitude_factor(None), 1.0)
        self.assertEqual(amplitude_factor(0.0), 0.0)
        self.assertLess(amplitude_factor(0.01), amplitude_factor(0.08))
        self.assertEqual(amplitude_factor(0.2), 1.0)

    def test_interest_score_combines_signals(self) -> None:
        loud_short = interest_score(4.0, 0.1)
        silent_short = interest_score(4.0, 0.0)
        loud_long = interest_score(25.0, 0.1)
        self.assertGreater(loud_short, silent_short)
        self.assertGreater(loud_short, loud_long)

    def test_sort_by_interest_orders_most_interesting_first(self) -> None:
        long_loud = _candidate(1, duration="25.000")
        short_silent = _candidate(2, duration="3.000")
        short_loud = _candidate(3, duration="3.000")
        ordered = sort_by_interest(
            [long_loud, short_silent, short_loud],
            amplitude_for_candidate={
                "1": 0.2,
                "2": 0.0,
                "3": 0.2,
            },
        )
        self.assertEqual([c.clip_id for c in ordered], ["3", "1", "2"])

    def test_score_candidate_uses_duration_string(self) -> None:
        candidate = _candidate(7, duration="12.500")
        self.assertAlmostEqual(
            score_candidate(candidate, None),
            interest_score(12.5, None),
        )


if __name__ == "__main__":
    unittest.main()
