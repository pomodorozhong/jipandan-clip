"""Synthetic end-to-end checks of the ranking preparation: row alignment, held-out exclusion and
the two edited-title leakage corrections. Needs the ``evaluate`` dependency group."""
import contextlib
from contextlib import closing
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN / "tests"))
sys.path.insert(0, str(RUN / "ranking"))
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None
if HAS_SKLEARN:
    import build_baseline
    import evaluate_pipeline
    import frozen_inputs
    import historical_scorer
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
                             "--snapshot", str(self.inputs["snapshot"]), "--out-dir", str(out),
                             "--input-hashes", str(self.inputs["hashes"])])
        return json.loads((out / "ranking-input.json").read_text())

    def baseline(self, out: Path):
        build_baseline.main(["--rows", str(out / "ranking-input.json"), "--legacy-dir", str(self.inputs["legacy_dir"]),
                             "--snapshot", str(self.inputs["snapshot"]), "--out-dir", str(out),
                             "--input-hashes", str(self.inputs["hashes"])])
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
        self.assertEqual(set(json.loads((self.root / "a" / "ranking-input.sources.json").read_text())),
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
        synthetic.pin(self.inputs)
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
        synthetic.pin(self.inputs)
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
                                        "--out-dir", str(pipeline), "--input-hashes", str(self.inputs["hashes"])])
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

    def test_the_comparison_keeps_the_scorer_from_before_the_tied_rank_correction(self):
        # Three clips tie on every signal: the old scorer ranked them by input position.
        tied = [SimpleNamespace(peak_db=1., no_speech_prob=.5, mid_share_db=1., bass_share_db=1.)] * 3
        low = SimpleNamespace(peak_db=0., no_speech_prob=.9, mid_share_db=0., bass_share_db=2.)
        self.assertEqual(historical_scorer.likely_keep_scores([low, *tied]), [0., 33.3, 66.7, 100.])
        out = self.root / "a"
        self.prepare(out)
        self.baseline(out)
        current = json.loads((out / "ranking-current.json").read_text())
        # The synthetic snapshot has tied features; if "before" also averaged tied ranks, both
        # sides would be the same score and this change would be exactly zero.
        self.assertGreater(current["mean_absolute_score_change"], 0)
        self.assertEqual(build_baseline.likely_keep_scores, historical_scorer.likely_keep_scores)

    def test_every_frozen_input_is_checked_before_computing(self):
        out = self.root / "a"
        self.prepare(out)
        for name in ("playback.json", "whisperfeat.json", "feats.json"):
            path = self.inputs["legacy_dir"] / name
            original = path.read_text()
            path.write_text(original + " ")
            with self.subTest(name), self.assertRaisesRegex(ValueError, name + " is not the frozen input"):
                self.baseline(out)
            path.write_text(original)
        self.inputs["eg2"].write_text(self.inputs["eg2"].read_text() + " ")
        with self.assertRaisesRegex(ValueError, "eg2_meta.json is not the frozen input"):
            self.prepare(out)
        self.assertFalse((out / "ranking-features.npz").exists())

    def test_feature_preparation_checks_the_snapshot_it_reads(self):
        out = self.root / "features"
        with closing(sqlite3.connect(self.inputs["snapshot"])) as con, con:  # changed, but not pinned again
            con.execute("update clip set data=json_set(data, '$.peak_db', 42.0) where clip_id='1'")
        with self.assertRaisesRegex(ValueError, "0903.jipandan.db is not the frozen input snapshot_0903"):
            self.pipeline_features(out)
        self.assertFalse((out / "0903.pipeline-features.json").exists())

    def test_a_snapshot_with_a_pending_write_ahead_log_is_refused(self):
        log = self.inputs["snapshot"].with_name(self.inputs["snapshot"].name + "-wal")
        log.write_bytes(b"")  # an empty log holds nothing, as beside the real snapshot
        frozen_inputs.check({"snapshot_0903": self.inputs["snapshot"]}, self.inputs["hashes"])
        log.write_bytes(b"pending rows")
        with self.assertRaisesRegex(ValueError, "0903.jipandan.db-wal holds changes"):
            frozen_inputs.check({"snapshot_0903": self.inputs["snapshot"]}, self.inputs["hashes"])

    def test_the_hash_file_prepare_inputs_writes_is_not_mistaken_for_the_recorded_hashes(self):
        out = self.root / "a"
        self.prepare(out)
        self.assertFalse((out / "input-hashes.json").exists())  # the recorded-hash file's name
        with self.assertRaisesRegex(ValueError, "has no frozen_inputs section"):
            frozen_inputs.check({"snapshot_0903": self.inputs["snapshot"]}, out / "ranking-input.sources.json")

    def test_the_tracked_hashes_cover_every_frozen_input(self):
        pinned = json.loads((RUN / "input-hashes.json").read_text())["frozen_inputs"]
        self.assertEqual(set(pinned), set(json.loads(self.inputs["hashes"].read_text())["frozen_inputs"]))

    def pipeline_features(self, out: Path, *extra: str) -> tuple[float, str]:
        cfg = self.root / "recordings.json"
        cfg.write_text(json.dumps([{"name": "0903"}]))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            prepare_pipeline_features.main(["--config", str(cfg), "--snapshot", str(self.inputs["snapshot"]),
                                            "--out-dir", str(out), "--input-hashes", str(self.inputs["hashes"]),
                                            *extra])
        rows = json.loads((out / "0903.pipeline-features.json").read_text())
        return next(r["peak_db"] for r in rows if r["id"] == "0903:1"), printed.getvalue()

    def set_snapshot_peak(self, value: float) -> None:
        with closing(sqlite3.connect(self.inputs["snapshot"])) as con, con:
            clip = json.loads(con.execute("select data from clip where clip_id='1'").fetchone()[0])
            con.execute("update clip set data=? where clip_id='1'", (json.dumps({**clip, "peak_db": value}),))
        synthetic.pin(self.inputs)

    def test_pipeline_features_are_reused_only_for_unchanged_inputs(self):
        out = self.root / "features"
        self.set_snapshot_peak(.9)
        self.assertEqual(self.pipeline_features(out), (.9, "0903 generated 50\n"))
        self.assertEqual(sorted(p.name for p in out.iterdir()),  # no partly written file is left
                         ["0903.pipeline-features.json", "0903.pipeline-features.source.json"])
        self.assertEqual(self.pipeline_features(out), (.9, "0903 reused 0903.pipeline-features.json\n"))

        self.set_snapshot_peak(100.9)
        with self.assertRaises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()) as message:
            self.pipeline_features(out)
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("measured from different inputs: the snapshot's clips", message.getvalue())
        self.assertEqual(self.pipeline_features(out, "--regenerate"), (100.9, "0903 regenerated 50\n"))
        self.assertEqual(self.pipeline_features(out), (100.9, "0903 reused 0903.pipeline-features.json\n"))

    def test_a_feature_file_without_a_fingerprint_is_not_reused(self):
        out = self.root / "features"
        self.pipeline_features(out)
        (out / "0903.pipeline-features.source.json").unlink()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as message:
            self.pipeline_features(out)
        self.assertIn("no recorded input fingerprint", message.getvalue())

    def test_a_recording_fingerprint_follows_each_of_its_files(self):
        cfg = {}
        for key in ("session", "audio", "words"):
            cfg[key] = str(self.root / key)
            Path(cfg[key]).write_text(key)
        version = ["ffmpeg version 1"]
        original = prepare_pipeline_features.ffmpeg_version
        prepare_pipeline_features.ffmpeg_version = lambda: version[0]
        self.addCleanup(setattr, prepare_pipeline_features, "ffmpeg_version", original)
        before = prepare_pipeline_features.fingerprint("0511", cfg, self.inputs["snapshot"])
        self.assertEqual(before, prepare_pipeline_features.fingerprint("0511", cfg, self.inputs["snapshot"]))
        for key in ("session", "audio", "words"):
            Path(cfg[key]).write_text(key + " changed")
            after = prepare_pipeline_features.fingerprint("0511", cfg, self.inputs["snapshot"])
            self.assertNotEqual(before["sha256"][key], after["sha256"][key])
        self.assertEqual(prepare_pipeline_features.differences(before, after),
                         "the audio file, the session file, the words file")
        # Another ffmpeg build decodes to slightly different samples, so it is another fingerprint.
        version[0] = "ffmpeg version 2"
        other_build = prepare_pipeline_features.fingerprint("0511", cfg, self.inputs["snapshot"])
        self.assertNotEqual(after, other_build)
        self.assertEqual(prepare_pipeline_features.differences(after, other_build), "the ffmpeg build")

    def test_adopting_fingerprints_an_old_file_without_measuring_it(self):
        out = self.root / "features"
        self.pipeline_features(out)
        features = out / "0903.pipeline-features.json"
        (out / "0903.pipeline-features.source.json").unlink()
        features.write_text(features.read_text().replace("\n", "\n ", 1))  # would not survive measuring again
        kept = features.read_bytes()
        # Adopting wins over measuring again for a file that only lacks its fingerprint.
        self.assertEqual(self.pipeline_features(out, "--adopt", "--regenerate")[1],
                         "0903 adopted 0903.pipeline-features.json\n")
        self.assertEqual(features.read_bytes(), kept)
        self.assertEqual(self.pipeline_features(out)[1], "0903 reused 0903.pipeline-features.json\n")
        # Adopting never covers a file whose recorded inputs differ from the current ones.
        self.set_snapshot_peak(55.5)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as message:
            self.pipeline_features(out, "--adopt")
        self.assertIn("measured from different inputs", message.getvalue())
        self.assertEqual(features.read_bytes(), kept)


if __name__ == "__main__":
    unittest.main()
