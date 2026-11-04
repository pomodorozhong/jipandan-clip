"""Protocol guards; optional model-evaluation dependencies stay outside the app runtime."""
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
    from evaluate_audio_semantics import load_scores


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


if __name__ == "__main__":
    unittest.main()
