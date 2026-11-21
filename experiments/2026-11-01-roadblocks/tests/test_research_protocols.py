"""Protocol guards; optional model-evaluation dependencies stay outside the app runtime."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
for folder in ("ranking", "model_scoring"):
    sys.path.insert(0, str(RUN / folder))
from experiment_titles import distance, final_title, normalize, select
from evaluate_title_alternatives import words_in_range

HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None
if HAS_SKLEARN:
    from evaluate_semantic_ranking import metrics
    from evaluate_audio_semantics import check_paired_runs, load_scores


class TitleProtocolTests(unittest.TestCase):
    def test_demos_exclude_held_recording_and_duplicate_transcripts(self):
        rows = [
            {"id": f"{recording}:{i}", "recording": recording,
             "text": "shared!" if i == 0 else f"{recording} phrase {i}",
             "approved": "shared" if i == 0 else f"edited {i}"}
            for recording in ("a", "b", "c") for i in range(4)
        ]
        selected, demos = select(rows, 2)
        self.assertEqual((selected, demos), select(rows, 2))
        self.assertEqual(len(selected), 9)
        for recording, examples in demos.items():
            held_texts = {normalize(r["text"]) for r in rows if r["recording"] == recording}
            self.assertTrue(examples)
            self.assertTrue(all(r["recording"] != recording for r in examples))
            self.assertTrue(all(normalize(r["text"]) not in held_texts for r in examples))

    def test_punctuation_is_separate_from_content_edits(self):
        self.assertEqual(normalize("真的！？"), normalize("真的"))
        self.assertEqual(distance("", ""), 0)
        self.assertEqual(distance("好", "不好"), .5)

    def test_only_final_model_answer_can_be_a_title(self):
        self.assertEqual(final_title("好</think> 好耶！"), "好耶！")
        self.assertEqual(final_title("<think>unfinished"), "")
        self.assertEqual(final_title(" 好耶！ "), "好耶！")

    def test_title_words_use_the_final_range_not_surrounding_context(self):
        words = [{"word": text, "start": start, "end": end} for text, start, end in
                 (("before", 0, 1), ("好", 1, 2), ("耶", 2, 3), ("after", 3, 4))]
        self.assertEqual(words_in_range(words, 1, 3), "好耶")


@unittest.skipUnless(HAS_SKLEARN, "optional research dependency: scikit-learn")
class RankingProtocolTests(unittest.TestCase):
    def test_constant_scores_cannot_benefit_from_label_order(self):
        y = np.r_[np.ones(5), np.zeros(5)]
        result = metrics(y, np.full(10, .5))
        self.assertEqual(result, metrics(y[::-1], np.full(10, .5)))
        self.assertEqual(result["auc"], .5)
        self.assertAlmostEqual(result["recall20"], .2)
        self.assertAlmostEqual(result["recall50"], .5)
        self.assertAlmostEqual(result["review80"], .8)

    def test_stale_or_duplicate_scores_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.jsonl"
            row = {"id": "a", "text_sha256": "stale"}
            path.write_text(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                load_scores(path, [{"id": "a", "text": "new"}])
            path.write_text((json.dumps(row) + "\n") * 2)
            with self.assertRaisesRegex(ValueError, "ids"):
                load_scores(path, [{"id": "a", "text": "new"}])


@unittest.skipUnless(HAS_SKLEARN, "optional research dependency: scikit-learn")
class PairedAudioProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.excerpt = self.root / "a.wav"
        self.excerpt.write_bytes(b"first excerpt")
        self.rows = [{"id": "a", "text": "text", "audio_path": str(self.excerpt)}]
        self.score = {"id": "a", "text_sha256": hashlib.sha256(b"text").hexdigest(),
                      "scores": {"reusable": .1, "standalone": .2, "expressive": .3}}
        self.pinned = {"revision": "r1", "checkpoint_sha256": "c1", "custom_code_sha256": {"api.py": "p1"}}
        self.questions = {"reusable": {"type": "noul"}}
        run = {"questions": self.questions, "model_revision": "r1", "checkpoint_sha256": "c1",
               "custom_code_sha256": {"api.py": "p1"}, "dtype": "torch.bfloat16", "input_sha256": "rows", "rows": 1}
        self.text_run, self.audio_run = {**run, "audio": False}, {**run, "audio": True}

    def scores(self, **extra):
        path = self.root / "scores.jsonl"
        path.write_text(json.dumps({**self.score, **extra}) + "\n")
        return path

    def test_audio_scores_must_match_the_current_excerpt(self):
        heard = hashlib.sha256(b"first excerpt").hexdigest()
        np.testing.assert_array_equal(load_scores(self.scores(audio_sha256=heard), self.rows, audio=True),
                                      [[.1, .2, .3]])
        with self.assertRaisesRegex(ValueError, "audio hash mismatch for a"):
            load_scores(self.scores(audio_sha256="0" * 64), self.rows, audio=True)
        with self.assertRaisesRegex(ValueError, "no audio hash"):
            load_scores(self.scores(), self.rows, audio=True)
        # Same ID and transcript, but the excerpt was extracted again after scoring.
        self.excerpt.write_bytes(b"second excerpt")
        with self.assertRaisesRegex(ValueError, "audio hash mismatch for a"):
            load_scores(self.scores(audio_sha256=heard), self.rows, audio=True)
        self.excerpt.unlink()
        with self.assertRaisesRegex(ValueError, "excerpt for a is missing"):
            load_scores(self.scores(audio_sha256=heard), self.rows, audio=True)

    def test_text_scores_must_not_have_heard_audio(self):
        np.testing.assert_array_equal(load_scores(self.scores(), self.rows), [[.1, .2, .3]])
        with self.assertRaisesRegex(ValueError, "made with audio"):
            load_scores(self.scores(audio_sha256="0" * 64), self.rows)

    def check(self, text=None, audio=None):
        check_paired_runs({**self.text_run, **(text or {})}, {**self.audio_run, **(audio or {})},
                          "rows", 1, self.pinned, self.questions)

    def test_paired_runs_must_share_everything_but_the_audio(self):
        self.check()
        for arm, change, message in [
            ("text", {"audio": True}, "text-only run"),
            ("audio", {"audio": False}, "run with audio"),
            ("audio", {"questions": {"reusable": {"type": "other"}}}, "differ in questions"),
            ("audio", {"dtype": "torch.float32"}, "differ in dtype"),
            ("audio", {"model_revision": "r2"}, "differ in model_revision"),
            ("text", {"input_sha256": "other rows"}, "text run scored a different rows file"),
            ("audio", {"rows": 0}, "audio run scored 0 of 1 rows"),
        ]:
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                self.check(**{arm: change})
        with self.assertRaisesRegex(ValueError, "differ in questions"):
            run = {k: v for k, v in self.audio_run.items() if k != "questions"}
            check_paired_runs(self.text_run, run, "rows", 1, self.pinned, self.questions)
        # A token budget is compared only when both manifests record one.
        self.check(audio={"token_budget": 2048})
        with self.assertRaisesRegex(ValueError, "differ in token_budget"):
            self.check(text={"token_budget": 8192}, audio={"token_budget": 2048})
        # Both runs agree with each other, but not with the fixed questions or the pinned checkpoint.
        other = {"reusable": {"type": "noul", "instructions": "other"}}
        with self.assertRaisesRegex(ValueError, "fixed questions of omni-questions.json"):
            self.check(text={"questions": other}, audio={"questions": other})
        with self.assertRaisesRegex(ValueError, "pinned d1-Omni-2B .checkpoint_sha256."):
            self.check(text={"checkpoint_sha256": "c2"}, audio={"checkpoint_sha256": "c2"})


if __name__ == "__main__":
    unittest.main()
