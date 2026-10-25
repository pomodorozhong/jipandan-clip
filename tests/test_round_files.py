import json
import tempfile
import unittest
from pathlib import Path

from jipandan.core.review_rounds import effective_clips, in_pool, overview, random_labels
from jipandan.core.round_files import (
    RoundHistory, audio_sha256, build_round_file, build_update_file, file_kind, imported_round, match_clips,
    parse_round_file, parse_update_file, round_file_path, round_slice, update_file_path, write_round_file,
)
from jipandan.core.srt import seconds_to_ffmpeg_timestamp

RECORDING = {"name": "a.mp3", "sha256": "f" * 64, "duration_ms": 60_000}
SOURCE = {"clip_source": "lines", "srt_sha256": "e" * 64, "features_version": 1}
FIXTURES = Path(__file__).parent / "fixtures" / "round-files"


def finished_round(**fields):
    return {"number": 2, "size": 3, "pool": 50, "total": 60, "random_share": 0.2, "seed": "s1", "score_version": "v",
            "sampling": 2, "random_chance": 0.1, "roles": {"1": "top", "2": "top", "3": "random"},
            "started": "2026-10-23T10:00:00.000Z", "completed": {"t": "2026-10-23T11:00:00.000Z", "unprocessed": 1},
            **fields}


def clip(index, start_ms, end_ms, status="pending", suffix=0, **fields):
    start = seconds_to_ffmpeg_timestamp(start_ms / 1000)
    return {"index": index, "suffix": suffix, "title": f"Line {index}", "source_text": f"Line {index}",
            "original_start": start, "original_end": seconds_to_ffmpeg_timestamp(end_ms / 1000), "start": start,
            "duration": f"{(end_ms - start_ms) / 1000:.3f}", "status": status, **fields}


def change(seq, after, kind="status", undoes=None):
    return {"seq": seq, "t": f"2026-10-23T10:{seq:02d}:00.000Z", "type": kind, "label": None, "undoes": undoes,
            "events": [{"seq": seq, "type": kind}], "after": after}


def view(seq, clip_id, stage, dwell_ms, minute=None):
    t = f"2026-10-23T10:{seq if minute is None else minute:02d}:00.000Z"
    return {"seq": seq, "t": t, "type": "view", "clip": clip_id, "stage": stage, "dwell_ms": dwell_ms, "start": t}


def round_file(item=None, start=None, changes=(), events=(), end_seq=20):
    start = start or {"1": clip(1, 1000, 2000), "2": clip(2, 3000, 4000), "3": clip(3, 5000, 6000),
                      "4": clip(4, 7000, 8000)}
    scores = {"1": 80.04, "2": None, "3": 10.0, "4": 90.0}
    return build_round_file(item or finished_round(), RECORDING, SOURCE, start, scores, changes, events, 0, end_seq)


class RoundFileTests(unittest.TestCase):
    def test_the_file_holds_the_round_clips_history_and_reading_it_gives_what_the_round_found(self):
        data = parse_round_file(round_file(changes=[
            change(2, {"1": clip(1, 1000, 2000, "group2")}),
            change(3, {"1": clip(1, 1000, 2000, "exported", start="00:00:01.200", duration="0.800"), "4": clip(4, 7000, 8000, "rejected")}),
            change(4, {"3": clip(3, 5000, 6000, "rejected")}),
            # After the round ended.
            change(30, {"3": clip(3, 5000, 6000, "group1")}),
        ], events=[view(1, "1", "triage", 4000), view(5, "1", "publish", 2000), view(6, "4", "triage", 9000),
                   # A view from before the round started counts only its part inside the round.
                   {**view(7, "2", "polish", 120_000), "start": "2026-10-23T09:59:00.000Z"}]))
        self.assertEqual((data["format"], data["version"]), ("jipandan-round", 2))
        self.assertEqual(list(data["clips_at_start"]), ["1", "2", "3"])
        self.assertEqual((data["round"]["roles"], data["round"]["clip_source"]), (finished_round()["roles"], "lines"))
        history = RoundHistory(data)
        self.assertEqual([(c["clip_id"], c["start_ms"], c["role"], c["score"], c["outcome"]) for c in history.file_clips()],
                         [("1", 1000, "top", 80.0, "kept"), ("2", 3000, "top", None, "unfinished"),
                          ("3", 5000, "random", 10.0, "rejected")])
        self.assertEqual(history.clips_at()["3"]["status"], "group1")
        self.assertEqual(history.clips_at()["1"]["start"], "00:00:01.200")
        self.assertEqual(history.times(), {"1": {"triage": 4000, "polish": 0, "publish": 2000},
                                           "2": {"triage": 0, "polish": 60_000, "publish": 0}})

    def test_clips_split_off_a_round_clip_belong_to_it_and_take_its_score(self):
        data = parse_round_file(round_file(changes=[change(2, {"1-2": clip(1, 1000, 2000, "exported", suffix=2)},
                                                           kind="duplicate")]))
        history = RoundHistory(data)
        self.assertEqual([(c["clip_id"], c["score"], c["outcome"]) for c in history.file_clips()][:2],
                         [("1", 80.0, "unfinished"), ("1-2", 80.0, "kept")])

    def test_corrections_and_undone_changes_are_worked_out_from_the_history(self):
        data = parse_round_file(round_file(changes=[
            change(2, {"1": clip(1, 1000, 2000, "group1")}),
            change(3, {"1": clip(1, 1000, 2000, "group2")}),
            change(4, {"2": clip(2, 3000, 4000, "group1")}),
            change(5, {"2": clip(2, 3000, 4000, "rejected")}),
            change(6, {"3": clip(3, 5000, 6000, "rejected")}),
            change(7, {"3": clip(3, 5000, 6000, "pending")}, kind="undo", undoes=[6]),
        ]))
        marks = RoundHistory(data).review_marks()
        # Needs work to Ready is the usual way through; kept to rejected is a change of mind.
        self.assertEqual(marks["1"], {"corrected": False, "undone": 0})
        self.assertEqual(marks["2"], {"corrected": True, "undone": 0})
        self.assertEqual(marks["3"], {"corrected": False, "undone": 1})

    def test_update_files_add_later_changes_once_and_name_gaps(self):
        item = finished_round()
        data = parse_round_file(round_file(changes=[change(2, {"1": clip(1, 1000, 2000, "exported")})]))
        first = parse_update_file(build_update_file(
            item, RECORDING["sha256"], 1, 20, 40, [change(30, {"1": clip(1, 1000, 2000, "exported", start="00:00:01.100")})],
            [view(31, "1", "publish", 500)]))
        again = json.loads(json.dumps(first))
        later = build_update_file(item, RECORDING["sha256"], 3, 60, 80, [change(70, {"1": clip(1, 1000, 2000, "rejected")})], [])
        history = RoundHistory(data, [later, first, again])
        self.assertEqual((history.updates, history.gaps, history.last_seq), (2, 1, 80))
        self.assertEqual(history.clips_at()["1"]["status"], "rejected")
        self.assertEqual(history.clips_at(40)["1"]["start"], "00:00:01.100")
        # The round's own findings stay as it ended.
        self.assertEqual(history.file_clips()[0]["outcome"], "kept")
        self.assertEqual(sum(1 for e in history.events if e["type"] == "view"), 1)
        other = build_update_file({**item, "seed": "other"}, RECORDING["sha256"], 1, 20, 40, [], [])
        with self.assertRaises(ValueError):
            RoundHistory(data, [other])

    def test_only_round_clips_go_in_and_export_paths_keep_only_the_file_name(self):
        exported = clip(1, 1000, 2000, "exported", last_export_path="/Users/someone/exports/a_0001_hi.mp3")
        changes, events = round_slice({"1": "top"}, [
            {**change(2, {"1": exported, "9": clip(9, 0, 500, "rejected")}),
             "events": [{"seq": 2, "type": "export", "clip": "1", "path": "/Users/someone/exports/a_0001_hi.mp3"}]},
            change(3, {"9": clip(9, 0, 500, "group1")}),
        ], [view(4, "1", "triage", 100), view(5, "9", "triage", 100)])
        self.assertEqual([list(c["after"]) for c in changes], [["1"]])
        self.assertEqual(changes[0]["after"]["1"]["last_export_path"], "a_0001_hi.mp3")
        self.assertEqual(changes[0]["events"][0]["path"], "a_0001_hi.mp3")
        self.assertEqual([e["clip"] for e in events], ["1"])

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
            self.assertEqual(update_file_path(audio, 1, 3).name, "a.round-01.update-03.json")
            self.assertEqual(audio_sha256(audio), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_malformed_files_are_refused(self):
        good = round_file()
        broken_clip = {**good, "clips_at_start": {"1": {"index": 1}}}
        broken_change = {**good, "changes": [{"seq": "x", "after": {}}]}
        for broken in ({}, {**good, "version": 9}, {**good, "recording": {}}, broken_clip, broken_change,
                       {**good, "round": {**good["round"], "roles": {"1": "maybe"}}}):
            with self.assertRaises(ValueError):
                parse_round_file(broken)
        update = build_update_file(finished_round(), RECORDING["sha256"], 1, 20, 40, [], [])
        self.assertEqual((file_kind(good), file_kind(update), file_kind([])), ("round", "update", None))
        with self.assertRaises(ValueError):
            parse_round_file(update)
        with self.assertRaises(ValueError):
            parse_update_file({**update, "to_seq": None})

    def test_history_with_clips_the_readers_cannot_use_is_refused(self):
        good = round_file(changes=[change(2, {"1": clip(1, 1000, 2000, "group2")})])
        broken = [{}, {**clip(1, 1000, 2000), "original_start": 5}, {**clip(1, 1000, 2000), "duration": "long"},
                  {key: value for key, value in clip(1, 1000, 2000).items() if key != "status"},
                  {**clip(1, 1000, 2000), "duration": 10 ** 400}, {**clip(1, 1000, 2000), "start": f"00:00:01,{10 ** 400}"}]
        for snapshot in broken:
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                parse_round_file({**good, "changes": [change(2, {"1": snapshot})]})
        for bad in ({**good, "changes": [change(2, {"x": clip(1, 1000, 2000)})]},
                    {**good, "changes": [change(2, {"9": clip(9, 1000, 2000)})]},
                    {**good, "events": [view(1, "9", "triage", 100)]},
                    {**good, "events": [{**view(1, "1", "triage", 100), "dwell_ms": None}]}):
            with self.assertRaises(ValueError):
                parse_round_file(bad)
        update = build_update_file(finished_round(), RECORDING["sha256"], 1, 20, 40, [change(30, {"1": {}})], [])
        with self.assertRaises(ValueError):
            parse_update_file(update)
        outside = build_update_file(finished_round(), RECORDING["sha256"], 1, 20, 40, [], [])
        outside["changes"] = [change(30, {"9": clip(9, 1000, 2000)})]
        parse_update_file(outside)
        with self.assertRaises(ValueError):
            RoundHistory(parse_round_file(good), [outside])

    def test_every_frozen_file_reads_in_the_current_version(self):
        for path in sorted(FIXTURES.glob("version-*.json")):
            with self.subTest(path.name):
                data = parse_round_file(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(data["version"], 2)
                self.assertTrue(RoundHistory(data).file_clips())

    def test_the_frozen_version_2_files_read_as_the_app_wrote_them(self):
        data = parse_round_file(json.loads((FIXTURES / "version-2.json").read_text(encoding="utf-8")))
        update = parse_update_file(json.loads((FIXTURES / "update-version-2.json").read_text(encoding="utf-8")))
        history = RoundHistory(data, [update])
        self.assertEqual([(c["clip_id"], c["role"], c["score"], c["outcome"]) for c in history.file_clips()],
                         [("1", "top", 75.0, "kept"), ("1-2", "top", 75.0, "kept"), ("2", "random", 0.0, "rejected"),
                          ("3", "top", 50.0, "rejected"), ("4", "random", 25.0, "unfinished")])
        self.assertEqual(history.review_marks()["3"], {"corrected": False, "undone": 1})
        # The script that wrote these files closed the round moments after opening it, so its 3-second
        # view counts only the part inside the round.
        self.assertEqual(history.times()["1"]["triage"], 12)
        self.assertEqual((history.clips_at()["1"]["status"], history.clips_at()["1"]["title"]), ("group2", "Line one!"))
        self.assertEqual((history.updates, history.gaps), (1, 0))

    def test_a_version_1_file_reads_as_the_history_that_would_produce_it(self):
        raw = json.loads((FIXTURES / "version-1.json").read_text(encoding="utf-8"))
        history = RoundHistory(parse_round_file(raw))
        self.assertTrue(history.synthetic)
        self.assertEqual([(c["clip_id"], c["start_ms"], c["role"], c["score"], c["outcome"]) for c in history.file_clips()],
                         [("1", 1000, "top", 81.0, "kept"), ("2", 3000, "top", 66.0, "rejected"),
                          ("3", 5000, "random", 20.5, "kept"), ("4", 7000, "random", 12.0, "unfinished")])
        self.assertEqual(history.times()["1"], {"triage": 4000, "polish": 6000, "publish": 9000})
        self.assertEqual(history.review_marks()["2"], {"corrected": False, "undone": 0})
        self.assertEqual((history.info["sampling"], history.info["random_chance"]), (2, 0.0435))
        legacy = {**raw, "round": {key: value for key, value in raw["round"].items()
                                   if key not in ("sampling", "random_chance")}}
        self.assertEqual(parse_round_file(legacy)["round"]["sampling"], 1)

    def test_clips_match_by_time_when_a_project_is_cut_differently(self):
        file_clips = [{"start_ms": 1000, "end_ms": 3000, "role": "top", "outcome": "kept"},
                      {"start_ms": 10_000, "end_ms": 11_000, "role": "random", "outcome": "rejected"}]
        # Here the first file clip is cut in two, one clip barely touches it, and one is elsewhere.
        clips = [(1, 1000, 1900), (2, 2000, 3100), (3, 2900, 4000), (4, 10_200, 10_900), (5, 20_000, 21_000)]
        matches = match_clips(file_clips, clips)
        self.assertEqual(sorted(matches), [1, 2, 4])
        self.assertEqual(matches[4][1]["outcome"], "rejected")
        self.assertAlmostEqual(matches[1][0][0], 1.0)

    def test_nested_clips_match_the_file_clip_with_the_same_range(self):
        # Generated clips nest: 282 lies inside 281, so both overlap all of the shorter clip.
        history = RoundHistory(parse_round_file(round_file(
            item=finished_round(size=2, roles={"281": "top", "282": "top"}),
            start={"281": clip(281, 1_316_472, 1_318_368), "282": clip(282, 1_317_208, 1_318_368)},
            changes=[change(2, {"281": clip(281, 1_316_472, 1_318_368, "exported"),
                                "282": clip(282, 1_317_208, 1_318_368, "rejected")})])))
        # Here 280 is the start of 281 and is cut from that file clip alone.
        matches = match_clips(history.file_clips(), [
            (280, 1_316_472, 1_317_208), (281, 1_316_472, 1_318_368), (282, 1_317_208, 1_318_368)])
        self.assertEqual({index: clip["index"] for index, (_, clip) in matches.items()}, {280: 281, 281: 281, 282: 282})
        item = imported_round(history, matches, 1, "a.round-02.json")
        self.assertEqual(item["imported"]["unmatched"], 0)
        # The clip with the same range takes the outcome, not the one nested inside it.
        self.assertEqual((item["outcomes"], item["covered"]), ({"281": "kept", "282": "rejected"}, [280]))

    def test_imported_round_counts_its_decisions_and_keeps_unfinished_clips_in_the_pool(self):
        history = RoundHistory(parse_round_file(round_file(
            changes=[change(2, {"1": clip(1, 1000, 2000, "exported")}), change(3, {"3": clip(3, 5000, 6000, "rejected")})],
            events=[view(1, "1", "triage", 4000), view(4, "1", "publish", 1000)])))
        matches = match_clips(history.file_clips(), [(7, 1000, 2000), (8, 3000, 4000), (9, 5000, 6000)])
        item = imported_round(history, matches, 1, "a.round-02.json")
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
        history = RoundHistory(parse_round_file(round_file(
            item=finished_round(roles={"3": "random"}), start={"3": clip(3, 1000, 4000)},
            changes=[change(2, {"3": clip(3, 1000, 4000, "exported")})])))
        history.start["3"]["score"] = 70.0
        matches = match_clips(history.file_clips(), [(7, 1000, 2000), (8, 2000, 3000), (9, 3000, 4000)])
        self.assertEqual(sorted(matches), [7, 8, 9])
        item = imported_round(history, matches, 1, "a.round-02.json")
        self.assertEqual((item["outcomes"], item["covered"]), ({"7": "kept"}, [8, 9]))
        clips = [(f"c{i}", i, "pending", 20.0) for i in (7, 8, 9, 10)]
        summary = overview([item], clips, [], 10, 0.2)
        self.assertEqual((summary["rounds"][0]["kept"], summary["labels"]["so_far"]), (1, 1))
        # The label keeps the file's score, not the newly cut clips' scores.
        self.assertEqual(random_labels([item], clips), [(70.0, True)])
        effective = effective_clips([item], clips)
        self.assertEqual([status for _, _, status, _ in effective], ["exported", "covered", "covered", "pending"])
        self.assertEqual(in_pool([item], [(index, status) for _, index, status, _ in effective]), {10})

    def test_the_file_holds_how_the_round_was_picked(self):
        data = round_file()
        self.assertEqual((data["round"]["sampling"], data["round"]["random_chance"]), (2, 0.1))
        item = finished_round()
        del item["sampling"]
        self.assertEqual(round_file(item=item)["round"]["sampling"], 1)


if __name__ == "__main__":
    unittest.main()
