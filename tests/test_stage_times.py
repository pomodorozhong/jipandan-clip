import unittest

from jipandan.core.stage_times import stage_breakdown


def view(clip, ms, stage=None, t="2026-10-21T10:00:00.000Z", start=None):
    return {"type": "view", "clip": clip, "dwell_ms": ms, "t": t,
            **({"filter": stage} if stage else {}), **({"start": start} if start else {})}


class StageBreakdownTests(unittest.TestCase):
    def test_views_and_changes_are_summed_per_stage(self):
        events = [
            {"type": "import", "clip": None, "t": "2026-10-21T09:59:00.000Z"},
            view("1", 3000, "triage", start="2026-10-21T09:59:30.000Z"),
            view("2", 4000, "triage"),
            {"type": "status", "clip": "1", "filter": "triage", "t": "x"},
            view("1", 30_000, "group1"),
            view("1", 10_000, "unsorted"),
            {"type": "trim", "clip": "1", "filter": "group1", "t": "x"},
            {"type": "title", "clip": "1", "filter": "group1", "t": "x"},
            view("1", 50_000, "publish", t="2026-10-21T10:05:00.000Z"),
            {"type": "export", "clip": "1", "t": "x"},
            {"type": "undo", "clip": None, "t": "x"},
        ]
        result = stage_breakdown(events)
        self.assertEqual(result["stages"], [
            {"stage": "triage", "ms": 7000, "views": 2, "clips": 2, "changes": 1},
            {"stage": "polish", "ms": 40_000, "views": 2, "clips": 1, "changes": 2},
            {"stage": "publish", "ms": 50_000, "views": 1, "clips": 1, "changes": 1},
        ])
        self.assertEqual(result["total_ms"], 97_000)
        self.assertEqual((result["first_view"], result["last_view"]),
                         ("2026-10-21T09:59:30.000Z", "2026-10-21T10:05:00.000Z"))

    def test_a_recorded_stage_wins_over_the_filter(self):
        # A view in Triage started while Polish's Unsorted filter was still set.
        event = {**view("1", 2000, "unsorted"), "stage": "triage"}
        self.assertEqual(stage_breakdown([event])["stages"][0], {"stage": "triage", "ms": 2000, "views": 1, "clips": 1, "changes": 0})

    def test_views_without_a_stage_are_reported_separately(self):
        result = stage_breakdown([view("1", 2000)])
        self.assertEqual(result["stages"][-1], {"stage": "unknown", "ms": 2000, "views": 1, "clips": 1, "changes": 0})
        self.assertEqual(stage_breakdown([])["stages"][0]["ms"], 0)
        self.assertIsNone(stage_breakdown([])["first_view"])


if __name__ == "__main__":
    unittest.main()
