"""Synthetic checks of the candidate variants: energy-run joining, next-run extension limits and
deduplication preference and boundaries. Needs the application's ``src`` on PYTHONPATH."""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN / "candidates"))
HAVE_APP = importlib.util.find_spec("jipandan") is not None and importlib.util.find_spec("platformdirs") is not None
if HAVE_APP:
    import candidate_variants as cv


def frames(*parts):
    """Build a level array from (level_db, frame_count) parts."""
    return np.concatenate([np.full(n, level, float) for level, n in parts])


@unittest.skipUnless(HAVE_APP, "needs the application's src on PYTHONPATH and platformdirs")
class EnergyTests(unittest.TestCase):
    def test_bursts_join_across_gaps_up_to_the_limit_only(self):
        levels = frames((-60, 10), (-20, 5), (-60, 16), (-20, 5), (-60, 17), (-20, 5), (-60, 5))
        # The 16-frame gap is joined (10-15 and 31-36 become one), the 17-frame gap is not.
        self.assertEqual(cv.energy_bursts(levels, -30), [[10, 36], [53, 58]])

    def test_the_threshold_decides_what_counts_as_loud(self):
        levels = frames((-60, 5), (-32, 5), (-60, 5))
        self.assertEqual(cv.energy_bursts(levels, -35), [[5, 10]])
        self.assertEqual(cv.energy_bursts(levels, -30), [])

    def test_a_silent_signal_has_no_bursts(self):
        self.assertEqual(cv.energy_bursts(np.full(100, -80.0), -40), [])

    def test_additions_need_the_right_length_and_no_speech(self):
        levels = frames((-60, 5), (-20, 70), (-60, 5))
        quiet = np.zeros(10, np.float32)
        spoken = np.ones(10, np.float32)
        added = cv.energy_additions(levels, quiet, -30)
        self.assertEqual(len(added), 1)
        start, end = added[0]
        self.assertAlmostEqual(start, 0.0)          # padded before, never below zero
        self.assertAlmostEqual(end, .85)            # 0.75 s plus the 0.1 s pad after
        self.assertEqual(cv.energy_additions(levels, spoken, -30), [])
        too_short = frames((-60, 5), (-20, 20), (-60, 5))
        self.assertEqual(cv.energy_additions(too_short, quiet, -30), [])
        too_long = frames((-60, 5), (-20, 600), (-60, 5))
        self.assertEqual(cv.energy_additions(too_long, np.zeros(300, np.float32), -30), [])


@unittest.skipUnless(HAVE_APP, "needs the application's src on PYTHONPATH and platformdirs")
class NextRunTests(unittest.TestCase):
    base = np.array([[1.0, 2.0]])

    def test_an_end_moves_to_the_next_run_when_it_is_close_enough(self):
        out = cv.extend_into_next_run(self.base, [(2100, 3000)], .16)
        np.testing.assert_allclose(out, [[1.0, 3.0]])

    def test_a_run_beyond_the_gap_is_ignored(self):
        out = cv.extend_into_next_run(self.base, [(2300, 3000)], .16)
        np.testing.assert_allclose(out, self.base)

    def test_a_clip_never_grows_past_the_maximum_length(self):
        out = cv.extend_into_next_run(self.base, [(2100, 6500)], .16)   # would be 5.5 s long
        np.testing.assert_allclose(out, self.base)
        out = cv.extend_into_next_run(self.base, [(2100, 6000)], .16)   # exactly 5 s is allowed
        np.testing.assert_allclose(out, [[1.0, 6.0]])

    def test_only_runs_that_start_after_the_end_count(self):
        out = cv.extend_into_next_run(self.base, [(1500, 1900), (2100, 3000)], .16)
        np.testing.assert_allclose(out, [[1.0, 3.0]])

    def test_no_runs_or_no_candidates_change_nothing(self):
        np.testing.assert_allclose(cv.extend_into_next_run(self.base, [], .16), self.base)
        self.assertEqual(cv.extend_into_next_run(np.empty((0, 2)), [(0, 1000)], .16).shape, (0, 2))


@unittest.skipUnless(HAVE_APP, "needs the application's src on PYTHONPATH and platformdirs")
class DedupTests(unittest.TestCase):
    pair = np.array([[0.0, 1.0], [0.05, 1.0]])   # IoU 0.95

    def test_the_preference_decides_which_duplicate_survives(self):
        np.testing.assert_allclose(cv.suppress(self.pair, .9, "short"), [[0.05, 1.0]])
        np.testing.assert_allclose(cv.suppress(self.pair, .9, "long"), [[0.0, 1.0]])

    def test_a_duplicate_exactly_at_the_threshold_is_dropped(self):
        spans = np.array([[0.0, 1.0], [0.0, 0.5]])   # IoU exactly 0.5
        self.assertEqual(len(cv.suppress(spans, .5, "short")), 1)
        self.assertEqual(len(cv.suppress(spans, .51, "short")), 2)

    def test_spans_that_do_not_overlap_are_all_kept(self):
        spans = np.array([[0.0, 1.0], [2.0, 3.0], [1.0, 2.0]])
        self.assertEqual(len(cv.suppress(spans, .5, "long")), 3)

    def test_survivors_keep_their_input_order(self):
        spans = np.array([[2.0, 3.0], [0.0, 1.0], [0.0, 0.9]])
        np.testing.assert_allclose(cv.suppress(spans, .8, "short"), [[2.0, 3.0], [0.0, 0.9]])

    def test_an_unknown_preference_is_an_error(self):
        with self.assertRaises(ValueError):
            cv.suppress(self.pair, .9, "middle")


if __name__ == "__main__":
    unittest.main()
