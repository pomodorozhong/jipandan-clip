import copy
import json
import tempfile
import unittest
from pathlib import Path

from jipandan.cli.dataset import _inputs
from jipandan.core.datasets import build_dataset, write_dataset
from jipandan.core.round_files import build_round_file, build_update_file

from test_round_files import FIXTURES, RECORDING, SOURCE, change, clip, finished_round, view


def round_two():
    """Round 2 of recording A: an exported keeper that was split, a correction, an undo, and an unfinished clip."""
    item = finished_round(roles={"1": "top", "2": "top", "3": "random", "4": "random"})
    start = {"1": clip(1, 1000, 2000, peak_db=-12.0), "2": clip(2, 3000, 4000), "3": clip(3, 5000, 6000),
             "4": clip(4, 7000, 8000)}
    exported = clip(1, 1000, 2000, "exported", start="00:00:01.200", duration="0.800", title="Hi!",
                    last_export_title="Hi!", last_export_mode="trim_edges", last_export_path="a_0001_Hi!.mp3")
    exported["last_export_snapshot"] = {"title": "Hi!", "start_ms": 1200, "end_ms": 2000, "mode": "trim_edges",
                                        "start_threshold_db": None, "stop_threshold_db": None}
    changes = [
        change(2, {"1": clip(1, 1000, 2000, "group1")}),
        change(3, {"1-2": clip(1, 1000, 2000, "group1", suffix=2)}, kind="duplicate"),
        change(4, {"1": exported}),
        change(5, {"1-2": clip(1, 1000, 2000, "group2", suffix=2, title="Line 1 again")}),
        change(6, {"2": clip(2, 3000, 4000, "group2")}),
        change(7, {"2": clip(2, 3000, 4000, "rejected")}),
        change(8, {"3": clip(3, 5000, 6000, "rejected")}),
        change(9, {"3": clip(3, 5000, 6000, "pending")}, kind="undo", undoes=[8]),
        change(10, {"3": clip(3, 5000, 6000, "rejected")}),
    ]
    events = [view(1, "1", "triage", 4000), view(11, "1", "publish", 3000)]
    scores = {"1": 80.0, "2": 60.0, "3": 20.0, "4": 10.0}
    data = build_round_file(item, RECORDING, SOURCE, start, scores, changes, events, 0, 20)
    # After the round: the Ready split clip is moved back to Needs work.
    update = build_update_file(item, RECORDING["sha256"], 1, 20, 30,
                               [change(25, {"1-2": clip(1, 1000, 2000, "group1", suffix=2)})], [])
    return data, update


class DatasetTests(unittest.TestCase):
    def build(self, files):
        return build_dataset(files)

    def test_examples_come_from_what_each_round_found_and_its_clips_latest_approved_state(self):
        data, update = round_two()
        dataset = self.build([("a.round-02.json", data), ("a.round-02.update-01.json", update)])
        ranking = {row["clip_id"]: row for row in dataset["ranking"]}
        self.assertEqual({clip_id: row["outcome"] for clip_id, row in ranking.items()},
                         {"1": "kept", "1-2": "kept", "2": "rejected", "3": "rejected", "4": "unfinished"})
        self.assertEqual((ranking["1"]["pick_chance"], ranking["3"]["pick_chance"]), (1.0, 0.1))
        self.assertEqual((ranking["1-2"]["parent"], ranking["1-2"]["score"], ranking["1-2"]["features"]["peak_db"]),
                         ("1", 80.0, -12.0))
        self.assertEqual((ranking["2"]["corrected"], ranking["3"]["corrected"], ranking["3"]["undone"]), (True, False, 1))
        self.assertEqual(ranking["1"]["time_ms"], {"triage": 4000, "polish": 0, "publish": 3000})
        self.assertEqual(ranking["1"]["partition"], RECORDING["sha256"])
        self.assertEqual(ranking["1"]["sources"], ["a.round-02.json", "a.round-02.update-01.json"])

        # Only clip 1 is still approved: its split clip went back to Needs work after the round.
        [timing] = dataset["timing"]
        self.assertEqual((timing["clip_id"], timing["original_start_ms"], timing["start_ms"], timing["retimed"]),
                         ("1", 1000, 1200, True))
        self.assertEqual((timing["export"]["mode"], timing["export"]["state"]), ("trim_edges", "matching"))
        [title] = dataset["titles"]
        self.assertEqual((title["source_text"], title["title"], title["edited"]), ("Line 1", "Hi!", True))

        manifest = dataset["manifest"]
        self.assertEqual(manifest["counts"]["ranking"], {
            "corrected": 1, "examples": 5, "kept": 2, "missing_features": 3, "missing_pick_chance": 0,
            "rejected": 2, "synthetic": 0, "unfinished": 1})
        self.assertEqual(manifest["counts"]["timing"]["excluded"], {"needs work": 1})
        # Clip 3 was drawn at random and decided; clip 4 was drawn but left unfinished.
        self.assertEqual(manifest["labels"], {"random_draws": 1, "recordings": 1, "target": 250})
        self.assertTrue(all(entry["used"] for entry in manifest["inputs"]))

    def test_the_same_files_give_the_same_bytes_in_any_order(self):
        data, update = round_two()
        folders = []
        with tempfile.TemporaryDirectory() as root:
            for position, files in enumerate(([("r.json", data), ("u.json", update)], [("u.json", update), ("r.json", data)])):
                folder = Path(root) / str(position)
                write_dataset(folder, self.build(files))
                folders.append({path.name: path.read_bytes() for path in folder.iterdir()})
        self.assertEqual(folders[0], folders[1])
        self.assertEqual(sorted(folders[0]), ["manifest.json", "ranking.jsonl", "timing.jsonl", "titles.jsonl"])

    def test_copies_count_once_and_the_newest_format_stands_for_a_round(self):
        data, update = round_two()
        v1 = {"format": "jipandan-round", "version": 1, "recording": RECORDING,
              "round": {key: data["round"][key] for key in ("number", "size", "seed", "started", "ended")},
              "clips": [{"start_ms": 1000, "end_ms": 2000, "role": "top", "score": 1.0, "outcome": "rejected"}]}
        dataset = self.build([("r.json", data), ("r2.json", copy.deepcopy(data)), ("old.json", v1),
                              ("u.json", update), ("u2.json", copy.deepcopy(update))])
        self.assertEqual(len(dataset["ranking"]), 5)
        inputs = {entry["file"]: entry for entry in dataset["manifest"]["inputs"]}
        self.assertEqual([name for name, entry in sorted(inputs.items()) if entry["used"]], ["r.json", "u.json"])
        self.assertEqual(inputs["old.json"]["reason"], "another copy of this round, r.json, is used")
        self.assertEqual(inputs["u2.json"]["reason"], "a copy of another update file")

    def test_older_and_unusable_files_are_counted_not_guessed(self):
        v1 = json.loads((FIXTURES / "version-1.json").read_text(encoding="utf-8"))
        legacy = {**v1, "round": {key: value for key, value in v1["round"].items()
                                  if key not in ("sampling", "random_chance")}}
        _, update = round_two()
        dataset = self.build([("v1.json", legacy), ("orphan.json", update), ("junk.json", {"format": "x"}),
                              ("broken.json", None)])
        counts = dataset["manifest"]["counts"]
        self.assertEqual((counts["ranking"]["examples"], counts["ranking"]["synthetic"],
                          counts["ranking"]["missing_pick_chance"], counts["ranking"]["missing_features"]), (4, 4, 4, 4))
        self.assertTrue(all(row["features"]["peak_db"] is None for row in dataset["ranking"]))
        # A version 1 file has outcomes but no final ranges or titles.
        self.assertEqual(dataset["timing"], [])
        self.assertEqual(counts["timing"]["excluded"], {"older format without final state": 2})
        reasons = {entry["file"]: entry.get("reason") for entry in dataset["manifest"]["inputs"]}
        self.assertEqual(reasons["orphan.json"], "its round file is not among the inputs")
        self.assertEqual(reasons["junk.json"], "not a Jipandan round file")
        self.assertEqual(reasons["broken.json"], "not a Jipandan round file")

    def test_copies_sharing_a_name_give_the_same_bytes_in_any_order(self):
        data, _ = round_two()
        other = copy.deepcopy(data)
        other["changes"] = other["changes"][:-1]
        folders = []
        with tempfile.TemporaryDirectory() as root:
            for position, files in enumerate(([("r.json", data), ("r.json", other)], [("r.json", other), ("r.json", data)])):
                folder = Path(root) / str(position)
                write_dataset(folder, self.build(files))
                folders.append({path.name: path.read_bytes() for path in folder.iterdir()})
        self.assertEqual(folders[0], folders[1])

    def test_the_command_names_files_from_folders_by_their_paths(self):
        data, _ = round_two()
        with tempfile.TemporaryDirectory() as root:
            folders = [Path(root) / name for name in ("a", "b")]
            for folder, number in zip(folders, (1, 2)):
                folder.mkdir()
                other = {**data, "round": {**data["round"], "seed": f"s{number}"}}
                (folder / "audio.round-02.json").write_text(json.dumps(other), encoding="utf-8")
            (folders[0] / "snap-points.json").write_text("{}", encoding="utf-8")
            # Named from the folder they share, which is left out, so moving them all changes nothing.
            self.assertEqual([name for name, _ in _inputs(folders)], ["a/audio.round-02.json", "b/audio.round-02.json"])
            self.assertEqual([name for name, _ in _inputs(folders[:1])], ["audio.round-02.json"])
            self.assertEqual([name for name, _ in _inputs([folders[0] / "snap-points.json"])], ["snap-points.json"])
            manifests = [build_dataset(_inputs(order))["manifest"] for order in (folders, folders[::-1])]
        self.assertEqual(manifests[0], manifests[1])

    def test_renaming_copies_does_not_change_which_one_is_used(self):
        data, update = round_two()
        other = copy.deepcopy(data)
        other["changes"] = other["changes"][:-1]
        used = []
        for names in (("a.json", "b.json"), ("b.json", "a.json")):
            dataset = self.build([(names[0], data), (names[1], other), ("u.json", update), ("u.json", copy.deepcopy(update))])
            [entry] = [entry for entry in dataset["manifest"]["inputs"] if entry["used"] and entry["kind"] == "round"]
            used.append((entry["content_sha256"], dataset["ranking"]))
            self.assertEqual(sum(entry["used"] for entry in dataset["manifest"]["inputs"] if entry["kind"] == "update"), 1)
        self.assertEqual(used[0][0], used[1][0])
        self.assertEqual([row["outcome"] for row in used[0][1]], [row["outcome"] for row in used[1][1]])

    def test_a_missing_update_file_between_two_others_is_counted(self):
        data, update = round_two()
        later = build_update_file(finished_round(), RECORDING["sha256"], 3, 40, 50, [], [])
        self.assertEqual(self.build([("r.json", data), ("u3.json", later)])["manifest"]["update_gaps"], 1)
        self.assertEqual(self.build([("r.json", data), ("u1.json", update)])["manifest"]["update_gaps"], 0)


if __name__ == "__main__":
    unittest.main()
