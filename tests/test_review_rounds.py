import unittest

from jipandan.core.review_rounds import (
    from_review_set, in_pool, keep_curve, keep_chance, overview, pick_round, set_order_key, unit_hash, unprocessed,
)


def view(clip, start, ms, stage="triage"):
    return {"type": "view", "clip": clip, "t": start, "start": start, "dwell_ms": ms, "filter": stage}


class PickTests(unittest.TestCase):
    def setUp(self):
        # 100 clips; clip i scores i, so the highest indexes rank first.
        self.clips = [(f"c{i}", i, float(i)) for i in range(100)]

    def test_round_mixes_a_random_sample_with_the_top_ranked_rest(self):
        picked = pick_round(self.clips, 30, seed="fixed")
        self.assertEqual((picked["size"], picked["pool"]), (30, 100))
        self.assertEqual((len(picked["random"]), len(picked["top"])), (6, 24))
        self.assertFalse(set(picked["random"]) & set(picked["top"]))
        # The top part is the highest scores among clips the random draw left.
        rest = [f"c{i}" for i in range(99, -1, -1) if f"c{i}" not in picked["random"]]
        self.assertEqual(picked["top"], rest[:24])
        self.assertEqual(len(picked["roles"]), 30)
        self.assertEqual(picked["roles"][picked["random"][0][1:]], "random")
        self.assertIsNone(picked["completed"])

    def test_same_seed_gives_the_same_round(self):
        self.assertEqual(pick_round(self.clips, 30, seed="s"), pick_round(self.clips, 30, seed="s"))
        self.assertNotEqual(pick_round(self.clips, 30, seed="s")["random"],
                            pick_round(self.clips, 30, seed="t")["random"])

    def test_random_part_is_drawn_from_the_whole_pool(self):
        # Over many seeds, low-scored clips are drawn as often as high-scored ones.
        low = high = 0
        for seed in range(400):
            for clip_id in pick_round(self.clips, 30, seed=str(seed))["random"]:
                low += int(clip_id[1:]) < 50
                high += int(clip_id[1:]) >= 50
        self.assertLess(abs(low - high) / (low + high), 0.06)

    def test_random_share_can_be_tuned(self):
        self.assertEqual(len(pick_round(self.clips, 30, random_share=0.5, seed="s")["random"]), 15)
        self.assertEqual(pick_round(self.clips, 30, random_share=0, seed="s")["random"], [])

    def test_small_pools_review_every_clip(self):
        picked = pick_round(self.clips[:12], 30, seed="s")
        self.assertEqual(picked["size"], 12)
        self.assertEqual(len(picked["roles"]), 12)

    def test_unscored_clips_rank_last(self):
        clips = [("a", 1, None), ("b", 2, 10.0), ("c", 3, 50.0)]
        self.assertEqual(pick_round(clips, 2, random_share=0, seed="s")["top"], ["c", "b"])

    def test_only_exported_and_rejected_clips_are_processed(self):
        roles = {"1": "top", "2": "random", "3": "top"}
        clips = [(1, "exported"), (2, "rejected"), (3, "group2"), (4, "pending"), (3, "group1")]
        self.assertEqual(unprocessed(roles, clips), 2)

    def test_new_rounds_take_only_unsorted_clips_outside_the_open_round(self):
        rounds = [{"roles": {"1": "top", "2": "random"}, "completed": None}]
        clips = [(1, "pending"), (2, "rejected"), (3, "pending"), (4, "group1"), (5, "pending"), (5, "rejected")]
        self.assertEqual(in_pool(rounds, clips), {3})
        # Clips a round ended early left Unsorted go back to the pool.
        rounds[0]["completed"] = {"t": "2026-10-21T12:00:00.000Z", "unprocessed": 1}
        self.assertEqual(in_pool(rounds, clips), {1, 3})

    def test_a_review_set_reads_as_round_one(self):
        old = {"size": 2, "total": 9, "random_share": 0.2, "seed": "s", "score_version": "v", "top": ["a"],
               "random": ["b"], "roles": {"1": "top", "2": "random"}, "completed": None}
        round_one = from_review_set(old, "2026-10-21T10:00:00.000Z")
        self.assertEqual((round_one["number"], round_one["pool"], round_one["started"]),
                         (1, 9, "2026-10-21T10:00:00.000Z"))

    def test_order_matches_the_frontend_hash(self):
        # Values from unitHash in frontend/src/reviewOrder.ts.
        self.assertAlmostEqual(unit_hash("a1b2c3d4:order:1"), 0.4212992808315903)
        self.assertAlmostEqual(unit_hash("a1b2c3d4:order:2"), 0.5049334005452693)
        self.assertAlmostEqual(unit_hash("a1b2c3d4:order:17"), 0.8219743503723294)
        self.assertAlmostEqual(set_order_key("seed", 903), 0.033122957684099674)


class EstimateTests(unittest.TestCase):
    def test_keep_curve_rises_with_the_score_when_high_scores_are_kept_more(self):
        samples = [(score, score > 50) for score in range(0, 100, 5)] + [(80.0, False), (20.0, True)]
        curve = keep_curve(samples)
        self.assertGreater(keep_chance(curve, 90, 0.5), 0.7)
        self.assertLess(keep_chance(curve, 10, 0.5), 0.3)
        self.assertIsNone(keep_curve([]))

    def test_keep_curve_stays_finite_when_every_label_agrees(self):
        curve = keep_curve([(score, True) for score in range(0, 100, 10)])
        self.assertGreater(keep_chance(curve, 50, 0.5), 0.9)

    def make_round(self, number, roles, started="2026-10-21T10:00:00.000Z", completed="2026-10-21T12:00:00.000Z"):
        return {"number": number, "size": len(roles), "random_share": 0.5, "roles": roles, "started": started,
                "completed": completed and {"t": completed, "unprocessed": 0}}

    def test_round_one_has_no_estimates_until_random_clips_are_decided(self):
        clips = [(f"c{i}", i, "pending", float(i)) for i in range(1, 41)]
        result = overview([], clips, [], 10, 0.2)
        self.assertIsNone(result["stream"])
        self.assertIsNone(result["next"]["adds"])
        self.assertEqual((result["pool"], result["next"]["size"], result["next"]["random_count"]), (40, 10, 2))
        self.assertEqual(result["pace"]["source"], "default")
        self.assertEqual(result["labels"]["so_far"], 0)

    def test_later_rounds_add_less_because_the_best_clips_go_first(self):
        # 200 clips scored 0–99.5; a clip is kept when it scores at least 50, so keepers sit at the top.
        def status(i):
            return "exported" if i >= 100 else "rejected"
        roles = {str(i): "top" for i in range(180, 200)}
        roles.update({str(i): "random" for i in range(0, 200, 10) if str(i) not in roles})
        clips = [(f"c{i}", i, status(i) if str(i) in roles else "pending", i / 2) for i in range(200)]
        result = overview([self.make_round(1, roles)], clips, [], 20, 0.2)
        stream = result["stream"]
        self.assertTrue(stream["low"] <= stream["keepers"] <= stream["high"])
        self.assertLess(abs(stream["keepers"] - 100), 15)
        first = result["rounds"][0]["captured"]
        # Round 1 took the 20 best clips, all kept, plus the random clips kept among them.
        self.assertAlmostEqual(first, result["rounds"][0]["kept"] / stream["keepers"])
        self.assertLess(result["next"]["adds"], first)
        self.assertEqual(result["next"]["number"], 2)
        self.assertEqual(result["labels"]["so_far"], 18)
        self.assertEqual(result["pool"], 200 - len(roles))

    def test_round_time_counts_only_views_inside_the_round(self):
        roles = {"1": "top", "2": "random"}
        clips = [("a", 1, "exported", 80.0), ("b", 2, "rejected", 10.0), ("c", 3, "pending", 50.0)]
        events = [
            view("a", "2026-10-21T09:00:00.000Z", 60_000),  # before the round: left out
            view("a", "2026-10-21T10:30:00.000Z", 20_000),
            view("b", "2026-10-21T11:00:00.000Z", 10_000, "publish"),
            view("c", "2026-10-21T11:00:00.000Z", 99_000),  # not a round clip
            view("b", "2026-10-21T13:00:00.000Z", 5_000),  # after the round
        ]
        result = overview([self.make_round(1, roles)], clips, events, 10, 0.2)
        self.assertEqual(result["rounds"][0]["time_ms"], 30_000)
        self.assertEqual(result["rounds"][0]["stage_ms"], {"triage": 20_000, "polish": 0, "publish": 10_000})
        self.assertEqual(result["pace"], {"source": "rounds", "rounds": [1],
                                          "stage_ms": {"triage": 10_000, "polish": 0, "publish": 5_000}, "ms": 15_000})
        self.assertEqual(result["next"]["ms"], 15_000)

    def test_views_across_the_round_edges_count_only_their_part_inside_it(self):
        roles = {"1": "top"}
        clips = [("a", 1, "exported", 80.0)]
        item = self.make_round(1, roles, started="2026-10-21T10:00:10.000Z", completed="2026-10-21T10:00:20.000Z")
        events = [
            view("a", "2026-10-21T10:00:09.000Z", 5_000),  # 9–14 s: 4 s inside
            view("a", "2026-10-21T10:00:19.000Z", 5_000),  # 19–24 s: 1 s inside
            view("a", "2026-10-21T10:00:21.000Z", 5_000),  # after the round
        ]
        result = overview([item], clips, events, 10, 0.2)
        self.assertEqual(result["rounds"][0]["time_ms"], 5_000)
        self.assertEqual(result["rounds"][0]["stages"][0]["ms"], 5_000)

    def test_views_without_a_start_time_count_as_ending_when_logged(self):
        roles = {"1": "top"}
        clips = [("a", 1, "exported", 80.0)]
        logged = {"type": "view", "clip": "a", "t": "2026-10-21T10:00:05.000Z", "dwell_ms": 30_000, "filter": "triage"}
        item = self.make_round(1, roles, started="2026-10-21T10:00:00.000Z")
        self.assertEqual(overview([item], clips, [logged], 10, 0.2)["rounds"][0]["time_ms"], 5_000)

    def test_a_clip_drawn_again_after_an_early_end_counts_once(self):
        # Round 1 drew clip 5 at random and ended early with it Unsorted; round 2 drew it again and kept it.
        first = {**self.make_round(1, {"5": "random"}), "closed_status": {"5": "pending"}}
        second = {**self.make_round(2, {"5": "random"}, started="2026-10-21T13:00:00.000Z",
                                    completed="2026-10-21T14:00:00.000Z"), "closed_status": {"5": "exported"}}
        clips = [("5", 5, "exported", 60.0)] + [(f"c{i}", i, "pending", float(i)) for i in range(10, 30)]
        result = overview([first, second], clips, [], 10, 0.2)
        self.assertEqual(result["labels"]["so_far"], 1)
        self.assertEqual([r["kept"] for r in result["rounds"]], [0, 1])
        self.assertLessEqual(result["captured"], 1.0)

    def test_a_finished_round_keeps_what_it_found_when_it_ended(self):
        # Clip 1 was Ready when the round ended and rejected afterwards; clip 2 was decided after it ended.
        item = {**self.make_round(1, {"1": "top", "2": "random"}), "closed_status": {"1": "group1", "2": "pending"}}
        clips = [("1", 1, "rejected", 80.0), ("2", 2, "exported", 30.0)]
        summary = overview([item], clips, [], 10, 0.2)
        self.assertEqual((summary["rounds"][0]["kept"], summary["rounds"][0]["decided"]), (1, 1))
        self.assertEqual(summary["labels"]["so_far"], 0)

    def test_clips_split_from_a_random_clip_add_no_labels(self):
        item = {**self.make_round(1, {"5": "random"}), "closed_status": {"5": "group1", "5-1": "rejected"}}
        clips = [("5", 5, "group1", 60.0), ("5-1", 5, "rejected", 20.0)]
        result = overview([item], clips, [], 10, 0.2)
        self.assertEqual(result["labels"]["so_far"], 1)
        self.assertEqual(result["rounds"][0]["clips"], 2)

    def test_an_open_round_reads_its_clips_as_they_are(self):
        item = self.make_round(1, {"1": "random"}, completed=None)
        result = overview([item], [("1", 1, "group2", 50.0)], [], 10, 0.2)
        self.assertEqual((result["rounds"][0]["kept"], result["labels"]["so_far"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
