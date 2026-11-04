"""Synthetic end-to-end checks of the ranking preparation: row alignment, held-out exclusion and
the two edited-title leakage corrections. Needs the ``evaluate`` dependency group."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN / "tests"))
sys.path.insert(0, str(RUN / "ranking"))
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None
if HAS_SKLEARN:
    import build_baseline
    import evaluate_pipeline
    import prepare_inputs
    import prepare_pipeline_features
    import synthetic


@unittest.skipUnless(HAS_SKLEARN, "scikit-learn is part of the experiments' evaluate group")
class RankingPreparationTests(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = synthetic.make_inputs(self.root)

    def prepare(self, out: Path):
        prepare_inputs.main(["--legacy-features", str(self.inputs["feats"]), "--eg2-meta", str(self.inputs["eg2"]),
                             "--snapshot", str(self.inputs["snapshot"]), "--out-dir", str(out)])
        return json.loads((out / "ranking-input.json").read_text())

    def baseline(self, out: Path):
        build_baseline.main(["--rows", str(out / "ranking-input.json"), "--legacy-dir", str(self.inputs["legacy_dir"]),
                             "--snapshot", str(self.inputs["snapshot"]), "--out-dir", str(out)])
        with np.load(out / "ranking-features.npz") as arrays:
            return dict(arrays)

    def test_rows_use_original_text_skip_pending_and_have_unique_ids(self):
        rows = self.prepare(self.root / "a")
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any("edited title" in r["text"] for r in rows))
        legacy = [r for r in rows if r["role"] == "legacy"]
        pending = sum(d["status"] == "pending" for d in json.loads(self.inputs["feats"].read_text()))
        self.assertEqual(len(legacy), len(synthetic.LEGACY) * synthetic.PER_RECORDING - pending)
        self.assertEqual({r["role"] for r in rows if r["recording"] == "0903"}, {"random", "top"})
        # Row hashes of the inputs are recorded for later comparison.
        self.assertEqual(set(json.loads((self.root / "a" / "input-hashes.json").read_text())),
                         {"legacy_features", "eg2_meta", "snapshot_0903"})

    def test_ids_and_labels_align_with_the_rows(self):
        out = self.root / "a"
        rows = {r["id"]: r for r in self.prepare(out)}
        arrays = self.baseline(out)
        self.assertTrue(all(i in rows for i in arrays["ids"]))
        for row_id, label in zip(arrays["ids"], arrays["y"]):
            self.assertEqual(rows[str(row_id)]["label"], int(label))

    def test_a_held_out_recording_never_trains_its_own_predictions(self):
        out_a, out_b = self.root / "a", self.root / "b"
        self.prepare(out_a)
        a = self.baseline(out_a)
        feats = json.loads(self.inputs["feats"].read_text())
        for d in feats:  # invert every label of one recording
            if d["rec"] == "0602" and d["status"] != "pending":
                d["status"] = "skipped" if d["status"] != "skipped" else "exported"
        self.inputs["feats"].write_text(json.dumps(feats))
        self.prepare(out_b)
        b = self.baseline(out_b)
        held = a["recording"] == "0602"
        for name in ("fully_clean", "audio_only", "single_clip_confidence"):
            np.testing.assert_array_equal(a[name][held], b[name][held])
            self.assertFalse(np.array_equal(a[name][~held], b[name][~held]))

    def test_edited_titles_do_not_change_the_clean_features(self):
        out_a, out_b = self.root / "a", self.root / "b"
        self.prepare(out_a)
        a = self.baseline(out_a)
        feats = json.loads(self.inputs["feats"].read_text())
        for d in feats:
            d["txt"] = d["txt"] + " with a longer edited title!"
        self.inputs["feats"].write_text(json.dumps(feats))
        b = self.baseline(out_a)  # same rows file; edited titles only
        np.testing.assert_array_equal(a["X"], b["X"])
        np.testing.assert_array_equal(a["fully_clean"], b["fully_clean"])
        # The deliberately leaky variant does see the edit.
        self.assertFalse(np.array_equal(a["old_title_leak"], b["old_title_leak"]))

    def test_pipeline_ranking_never_trains_on_the_generated_session(self):
        out_a, out_b = self.root / "a", self.root / "b"
        rows = self.prepare(out_a)
        pipeline = self.root / "pipeline"
        synthetic.write_pipeline_features(pipeline)
        (pipeline / "ranking-input.json").write_text(json.dumps(rows))
        # The 0903 features are measured from the snapshot, like the real run.
        cfg = self.root / "recordings.json"
        cfg.write_text(json.dumps([{"name": "0903"}]))
        prepare_pipeline_features.main(["--config", str(cfg), "--snapshot", str(self.inputs["snapshot"]),
                                        "--out-dir", str(pipeline)])
        evaluate_pipeline.main(["--work-dir", str(pipeline), "--out-dir", str(out_a)])
        with np.load(out_a / "pipeline-ranking.npz") as arrays:
            a = dict(arrays)
        self.assertEqual([str(i) for i in a["ids"]], [r["id"] for r in rows])
        for r in rows:  # invert the generated labels
            if r["recording"] == "0903":
                r["label"] = 1 - r["label"]
        (pipeline / "ranking-input.json").write_text(json.dumps(rows))
        evaluate_pipeline.main(["--work-dir", str(pipeline), "--out-dir", str(out_b)])
        with np.load(out_b / "pipeline-ranking.npz") as arrays:
            b = dict(arrays)
        legacy = a["recording"] != "0903"
        for name in ("refit_logistic", "refit_gbm"):
            np.testing.assert_array_equal(a[name][legacy], b[name][legacy])


if __name__ == "__main__":
    unittest.main()
