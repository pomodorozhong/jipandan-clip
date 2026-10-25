import json
import tempfile
import unittest
from pathlib import Path

from jipandan.core.review_rounds import effective_clips, in_pool, overview, random_labels
from jipandan.core.round_files import (
    audio_sha256, build_round_file, imported_round, match_clips, parse_round_file, round_file_path, write_round_file,
)

RECORDING = {"name": "a.mp3", "sha256": "f" * 64, "duration_ms": 60_000}


def finished_round():
    return {"number": 2, "size": 3, "pool": 50, "total": 60, "random_share": 0.2, "seed": "s1", "score_version": "v",
            "roles": {"1": "top", "2": "top", "3": "random"}, "started": "2026-10-23T10:00:00.000Z",
            "completed": {"t": "2026-10-23T11:00:00.000Z", "unprocessed": 1}}


class RoundFileTests(unittest.TestCase):
    def test_file_holds_each_round_clip_by_time_with_its_outcome_and_time_in_the_round(self):
        clips = [("1", 1, 1000, 2000, "exported", 80.04), ("2", 2, 3000, 4000, "pending", None),
                 ("3", 3, 5000, 6000, "rejected", 10.0), ("4", 4, 7000, 8000, "exported", 90.0)]
        times = {"1": {"triage": 5, "polish": 6, "publish": 7}}
        data = parse_round_file(build_round_file(finished_round(), RECORDING, clips, times))
        self.assertEqual(data["round"]["number"], 2)
        self.assertEqual(data["round"]["ended"], "2026-10-23T11:00:00.000Z")
        self.assertEqual([(c["start_ms"], c["role"], c["outcome"], c["score"]) for c in data["clips"]],
                         [(1000, "top", "kept", 80.0), (3000, "top", "unfinished", None), (5000, "random", "rejected", 10.0)])
        self.assertEqual(data["clips"][0]["time_ms"], {"triage": 5, "polish": 6, "publish": 7})
        self.assertEqual(data["clips"][1]["time_ms"], {"triage": 0, "polish": 0, "publish": 0})

    def test_files_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "a.mp3"
            audio.write_bytes(b"abc")
            first = round_file_path(audio, 1)
            write_round_file(first, {"x": 1})
            second = round_file_path(audio, 1)
            self.assertEqual((first.name, second.name), ("a.round-01.json", "a.round-01-2.json"))
            with self.assertRaises(FileExistsError):
                write_round_file(first, {"x": 2})
            self.assertEqual(json.loads(first.read_text()), {"x": 1})
            self.assertEqual(audio_sha256(audio), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_malformed_files_are_refused(self):
        good = build_round_file(finished_round(), RECORDING, [("1", 1, 1000, 2000, "exported", 80.0)], {})
        for broken in ({}, {**good, "version": 9}, {**good, "recording": {}},
                       {**good, "clips": [{"start_ms": 5, "end_ms": 1, "role": "top", "outcome": "kept"}]}):
            with self.assertRaises(ValueError):
                parse_round_file(broken)

    def test_clips_match_by_time_when_a_project_is_cut_differently(self):
        file_clips = [{"start_ms": 1000, "end_ms": 3000, "role": "top", "outcome": "kept"},
                      {"start_ms": 10_000, "end_ms": 11_000, "role": "random", "outcome": "rejected"}]
        # Here the first file clip is cut in two, one clip barely touches it, and one is elsewhere.
        clips = [(1, 1000, 1900), (2, 2000, 3100), (3, 2900, 4000), (4, 10_200, 10_900), (5, 20_000, 21_000)]
        matches = match_clips(file_clips, clips)
        self.assertEqual(sorted(matches), [1, 2, 4])
        self.assertEqual(matches[4][1]["outcome"], "rejected")
        self.assertAlmostEqual(matches[1][0], 1.0)

    def test_imported_round_counts_its_decisions_and_keeps_unfinished_clips_in_the_pool(self):
        data = build_round_file(finished_round(), RECORDING, [
            ("1", 1, 1000, 2000, "exported", 80.0), ("2", 2, 3000, 4000, "pending", 60.0),
            ("3", 3, 5000, 6000, "rejected", 10.0)], {"1": {"triage": 4000, "polish": 0, "publish": 1000}})
        matches = match_clips(data["clips"], [(7, 1000, 2000), (8, 3000, 4000), (9, 5000, 6000)])
        item = imported_round(data, matches, 1, "a.round-02.json")
        self.assertEqual((item["number"], item["size"], item["imported"]["number"], item["imported"]["unmatched"]),
                         (1, 3, 2, 0))
        self.assertEqual(item["outcomes"], {"7": "kept", "8": "unfinished", "9": "rejected"})
        self.assertEqual(item["covered"], [])
        # Here every clip is still Unsorted: the file's decisions stand in for them.
        clips = [(f"c{i}", i, "pending", 50.0) for i in (7, 8, 9, 10)]
        effective = effective_clips([item], clips)
        self.assertEqual([status for _, _, status, _ in effective], ["exported", "pending", "rejected", "pending"])
        self.assertEqual(in_pool([item], [(index, status) for _, index, status, _ in effective]), {8, 10})
        summary = overview([item], clips, [], 10, 0.2)
        self.assertEqual((summary["rounds"][0]["kept"], summary["rounds"][0]["time_ms"], summary["labels"]["so_far"]),
                         (1, 5000, 1))
        self.assertEqual(summary["rounds"][0]["imported"]["file"], "a.round-02.json")
        # Its views and changes stayed in the other project, so there is no stage breakdown.
        self.assertIsNone(summary["rounds"][0]["stages"])

    def test_a_file_clip_cut_into_parts_here_counts_once(self):
        # One random keeper spanning 1–4 s; this project cut the same audio into three clips.
        data = build_round_file({**finished_round(), "roles": {"3": "random"}}, RECORDING,
                                [("3", 3, 1000, 4000, "exported", 70.0)], {})
        matches = match_clips(data["clips"], [(7, 1000, 2000), (8, 2000, 3000), (9, 3000, 4000)])
        self.assertEqual(sorted(matches), [7, 8, 9])
        item = imported_round(data, matches, 1, "a.round-02.json")
        self.assertEqual((item["outcomes"], item["covered"]), ({"7": "kept"}, [8, 9]))
        clips = [(f"c{i}", i, "pending", 20.0) for i in (7, 8, 9, 10)]
        summary = overview([item], clips, [], 10, 0.2)
        self.assertEqual((summary["rounds"][0]["kept"], summary["labels"]["so_far"]), (1, 1))
        # The label keeps the file's score, not the newly cut clips' scores.
        self.assertEqual(random_labels([item], clips), [(70.0, True)])
        effective = effective_clips([item], clips)
        self.assertEqual([status for _, _, status, _ in effective], ["exported", "covered", "covered", "pending"])
        self.assertEqual(in_pool([item], [(index, status) for _, index, status, _ in effective]), {10})

    def test_the_file_holds_the_round_as_it_ended_and_how_it_was_picked(self):
        item = {**finished_round(), "sampling": 2, "random_chance": 0.25}
        data = build_round_file(item, RECORDING, [("1", 1, 1000, 2000, "exported", 80.0)], {})
        self.assertEqual((data["round"]["sampling"], data["round"]["random_chance"]), (2, 0.25))
        self.assertEqual(build_round_file(finished_round(), RECORDING, [], {})["round"]["sampling"], 1)


if __name__ == "__main__":
    unittest.main()
