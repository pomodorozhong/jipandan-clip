import unittest

from jipandan.core import candidates as cand


def word(text, start, end):
    return {"word": text, "start": start, "end": end}


class WordTests(unittest.TestCase):
    def test_words_are_sorted_and_invalid_timings_skipped(self):
        segments = [
            {"words": [word(" 好", 2.0, 2.5), word("壞", "x", 1.0), word("負", -1.0, 0.0)]},
            {"words": [word("欸", 0.5, 0.75), word("反", 3.0, 2.0)]},
            {"text": "no words"},
        ]
        self.assertEqual(
            cand.words_from_segments(segments),
            [cand.Word(500, 750, "欸"), cand.Word(2000, 2500, " 好")],
        )


class GenerateTests(unittest.TestCase):
    def generate(self, segments, runs, **options):
        options = {"min_length_ms": 0, "max_length_ms": 60_000, **options}
        return cand.generate_candidates(segments, runs, **options)

    def test_runs_with_words_start_early_and_runs_without_words_are_dropped(self):
        segments = [{"end": 2.0, "words": [word("走", 1.1, 1.6), word(" 吧", 1.6, 2.0)]}]
        result = self.generate(segments, [(1000, 2400), (5000, 6000)], start_snap_ms=0, end_snap_ms=0)
        self.assertIn(cand.Candidate(800, 2400, "走 吧"), result)
        self.assertFalse(any(c.start_ms >= 4000 for c in result))

    def test_segment_edges_snap_to_nearby_voice_activity(self):
        # One long run of speech holds two Whisper segments; a second run ends after a pause.
        segments = [
            {"end": 3.0, "words": [word("一", 1.3, 2.0), word("二", 2.0, 3.0)]},
            {"end": 7.0, "words": [word("三", 4.0, 7.0)]},
        ]
        runs = [(1500, 3600), (4100, 6200)]
        result = self.generate(segments, runs)
        # The first segment starts at the run's onset minus the lead, and ends where speech ends.
        self.assertIn(cand.Candidate(1300, 3600, "一二"), result)
        # The second segment's end is 0.8 s after the speech end, within the 1 s snap.
        self.assertIn(cand.Candidate(3900, 6200, "三"), result)

    def test_far_voice_activity_leaves_segment_edges_alone(self):
        segments = [{"end": 9.0, "words": [word("遠", 5.0, 9.0)]}]
        result = self.generate(segments, [(1000, 2000)], start_snap_ms=500, end_snap_ms=1000)
        self.assertEqual(result, [cand.Candidate(5000, 9000, "遠")])

    def test_length_limits_and_duplicates(self):
        segments = [{"end": 2.0, "words": [word("短", 1.2, 2.0)]}]
        runs = [(1200, 2000)]
        # The run and the snapped segment give the same bounds, kept once.
        self.assertEqual(self.generate(segments, runs), [cand.Candidate(1000, 2000, "短")])
        self.assertEqual(self.generate(segments, runs, min_length_ms=1200), [])
        self.assertEqual(self.generate(segments, runs, max_length_ms=900), [])

    def test_start_never_goes_below_zero(self):
        segments = [{"end": 1.0, "words": [word("零", 0.05, 1.0)]}]
        self.assertEqual(self.generate(segments, [(100, 1000)])[0].start_ms, 0)


if __name__ == "__main__":
    unittest.main()
