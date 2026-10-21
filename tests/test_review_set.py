import unittest

from jipandan.core.review_set import pick_review_set, unprocessed


class ReviewSetTests(unittest.TestCase):
    def setUp(self):
        # 100 clips; clip i scores i, so the highest indexes rank first.
        self.clips = [(f"c{i}", i, float(i)) for i in range(100)]

    def test_set_mixes_a_random_sample_with_the_top_ranked_rest(self):
        picked = pick_review_set(self.clips, 30, seed="fixed")
        self.assertEqual((picked["size"], picked["total"]), (30, 100))
        self.assertEqual((len(picked["random"]), len(picked["top"])), (6, 24))
        self.assertFalse(set(picked["random"]) & set(picked["top"]))
        # The top part is the highest scores among clips the random draw left.
        rest = [f"c{i}" for i in range(99, -1, -1) if f"c{i}" not in picked["random"]]
        self.assertEqual(picked["top"], rest[:24])
        self.assertEqual(len(picked["roles"]), 30)
        self.assertEqual(picked["roles"][picked["random"][0][1:]], "random")
        self.assertIsNone(picked["completed"])

    def test_same_seed_gives_the_same_set(self):
        self.assertEqual(pick_review_set(self.clips, 30, seed="s"), pick_review_set(self.clips, 30, seed="s"))
        self.assertNotEqual(pick_review_set(self.clips, 30, seed="s")["random"],
                            pick_review_set(self.clips, 30, seed="t")["random"])

    def test_random_part_is_drawn_from_every_clip(self):
        # Over many seeds, low-scored clips are drawn as often as high-scored ones.
        low = high = 0
        for seed in range(400):
            for clip_id in pick_review_set(self.clips, 30, seed=str(seed))["random"]:
                low += int(clip_id[1:]) < 50
                high += int(clip_id[1:]) >= 50
        self.assertLess(abs(low - high) / (low + high), 0.06)

    def test_small_recordings_review_every_clip(self):
        picked = pick_review_set(self.clips[:12], 30, seed="s")
        self.assertEqual(picked["size"], 12)
        self.assertEqual(len(picked["roles"]), 12)

    def test_unscored_clips_rank_last(self):
        clips = [("a", 1, None), ("b", 2, 10.0), ("c", 3, 50.0)]
        self.assertEqual(pick_review_set(clips, 2, random_share=0, seed="s")["top"], ["c", "b"])

    def test_only_exported_and_rejected_clips_are_processed(self):
        roles = {"1": "top", "2": "random", "3": "top"}
        clips = [(1, "exported"), (2, "rejected"), (3, "group2"), (4, "pending"), (3, "group1")]
        self.assertEqual(unprocessed(roles, clips), 2)


if __name__ == "__main__":
    unittest.main()
