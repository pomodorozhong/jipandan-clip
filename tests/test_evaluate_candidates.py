import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.evaluate_candidates import Recording, exported_start, kept_clips, timing


class EvaluationTests(unittest.TestCase):
    def test_needs_work_is_not_an_approved_timing_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text(json.dumps({"candidates": [
                {"status": status, "start": f"00:00:0{i}.000", "duration": 1}
                for i, status in enumerate(("exported", "group1", "group2", "rejected", "pending"))
            ]}))
            np.testing.assert_equal(kept_clips(path), [[0, 1], [2, 3]])

    def test_trim_never_uses_sound_after_the_clip_ends(self):
        levels = np.r_[np.full(200, -100.), np.full(100, -10.)]
        self.assertTrue(np.isnan(exported_start(levels, 0, 1)))
        self.assertAlmostEqual(exported_start(levels, 0, 3), 1.8)
        self.assertTrue(np.isnan(exported_start(levels, 2, 2.05)))

    def test_unmeasurable_starts_are_reported_separately(self):
        recording = Recording("sample", 1, np.array([[0., 1.], [2., 3.]]),
                              {"source": np.array([[0., 1.], [2.3, 3.]])},
                              np.r_[np.full(200, -100.), np.full(100, -10.)])
        result = timing(recording, "source")
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["start_measured"], 1)
        self.assertEqual(result["late"], 1)

    def test_empty_keeps_or_candidates_do_not_crash(self):
        for kept, source in (([], [[0, 1]]), ([[0, 1]], [])):
            recording = Recording("empty", 1, np.array(kept).reshape(-1, 2),
                                  {"source": np.array(source).reshape(-1, 2)}, np.zeros(100))
            self.assertEqual(timing(recording, "source")["matched_count"], 0)


if __name__ == "__main__":
    unittest.main()
