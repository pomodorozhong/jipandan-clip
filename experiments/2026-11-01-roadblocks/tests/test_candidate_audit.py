"""Guards for the candidate audit's oracle ceiling. Needs the application's ``src`` on PYTHONPATH."""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN / "candidates"))
HAVE_APP = importlib.util.find_spec("jipandan") is not None and importlib.util.find_spec("platformdirs") is not None
if HAVE_APP:
    from audit_candidate_coverage import ONSET_BACKOFF, oracle_found


@unittest.skipUnless(HAVE_APP, "needs the application's src on PYTHONPATH and platformdirs")
class OracleTests(unittest.TestCase):
    # Long enough that a start 0.47 s late still covers most of the reference.
    reference = np.array([[10.0, 16.0]])
    ends = np.array([16.0])

    def test_backoff_is_applied_before_the_tolerance_window(self):
        # 10.52 is outside +-0.5 s of the reference start, but 0.05 s earlier it is 10.47:
        # inside the window, so the oracle may use it.
        self.assertEqual(oracle_found(self.reference, np.array([10.52]), self.ends, .5), 1)

    def test_a_start_pushed_out_of_the_window_by_the_backoff_is_not_used(self):
        # 9.52 is inside the window unshifted, but the shifted 9.47 is 0.53 s early.
        self.assertEqual(oracle_found(self.reference, np.array([9.52]), self.ends, .5), 0)

    def test_the_shifted_start_has_to_match_within_tolerance_on_both_edges(self):
        self.assertEqual(oracle_found(self.reference, np.array([10.0]), np.array([16.6]), .5), 0)
        self.assertEqual(oracle_found(self.reference, np.array([10.0]), np.array([16.4]), .5), 1)

    def test_no_choices_or_no_references_find_nothing(self):
        self.assertEqual(oracle_found(self.reference, np.array([]), self.ends, .5), 0)
        self.assertEqual(oracle_found(np.empty((0, 2)), np.array([10.0]), self.ends, .5), 0)

    def test_the_backoff_default_is_the_generators(self):
        self.assertEqual(ONSET_BACKOFF, .05)


if __name__ == "__main__":
    unittest.main()
