"""Synthetic checks of the audio and title input builders: which rows they pick, in what order,
and that neither one looks at a label. No recordings and no ffmpeg: extraction is stubbed."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
for folder in ("tests", "ranking", "model_scoring"):
    sys.path.insert(0, str(RUN / folder))
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None
if HAS_SKLEARN:
    import experiment_titles
    import prepare_audio_inputs
    import prepare_inputs
    import prepare_title_inputs
    import synthetic


@unittest.skipUnless(HAS_SKLEARN, "scikit-learn is part of the experiments' evaluate group")
class InputBuilderTests(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = synthetic.make_inputs(self.root)
        prepare_inputs.main(["--legacy-features", str(self.inputs["feats"]), "--eg2-meta", str(self.inputs["eg2"]),
                             "--snapshot", str(self.inputs["snapshot"]), "--out-dir", str(self.root / "work"),
                             "--input-hashes", str(self.inputs["hashes"])])
        self.rows_path = self.root / "work" / "ranking-input.json"
        self.rows = json.loads(self.rows_path.read_text())
        self.extracted = []
        original = prepare_audio_inputs.extract
        self.real_extract = original
        prepare_audio_inputs.extract = self.fake_extract
        self.addCleanup(setattr, prepare_audio_inputs, "extract", original)

    def fake_extract(self, audio, start, end, dest):
        self.extracted.append((audio.name, start, end, dest.name))
        dest.write_bytes(b"wav")

    def audio(self, name: str, *extra: str) -> list[dict]:
        out = self.root / name
        prepare_audio_inputs.main(["--rows", str(self.rows_path), "--config", str(self.config),
                                   "--snapshot", str(self.inputs["snapshot"]), "--audio-dir", str(self.root / "audio"),
                                   "--out", str(out), "--input-hashes", str(self.inputs["hashes"]), *extra])
        return json.loads(out.read_text())

    def test_audio_sample_is_fixed_ordered_and_blind_to_labels(self):
        chosen = prepare_audio_inputs.select_rows(self.rows, per_recording=10)
        self.assertEqual(chosen, prepare_audio_inputs.select_rows(self.rows, per_recording=10))
        position = {r["id"]: i for i, r in enumerate(self.rows)}
        for recording in synthetic.LEGACY:
            ids = [r["id"] for r in chosen if r["recording"] == recording]
            self.assertEqual(len(ids), 10)
            self.assertEqual(ids, sorted(ids, key=position.get))
        self.assertEqual([r for r in chosen if r["recording"] == "0903"],
                         [r for r in self.rows if r["recording"] == "0903"])
        self.assertEqual([r["recording"] for r in chosen], sorted(r["recording"] for r in chosen))
        flipped = [{**r, "label": 1 - r["label"]} for r in self.rows]
        self.assertEqual([r["id"] for r in prepare_audio_inputs.select_rows(flipped, per_recording=10)],
                         [r["id"] for r in chosen])
        # A recording with fewer rows than the sample size contributes all of them.
        self.assertEqual(len(prepare_audio_inputs.select_rows(self.rows, per_recording=10 ** 6)), len(self.rows))

    def test_audio_rows_point_at_excerpts_of_the_original_unsplit_bounds(self):
        self.config = synthetic.write_sessions(self.root / "sessions")
        rows = self.audio("audio-input.json")
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in prepare_audio_inputs.select_rows(self.rows)])
        self.assertEqual(len(self.extracted), len(rows))
        by_dest = {dest: (audio, start, end) for audio, start, end, dest in self.extracted}
        for row in rows:
            recording, index = row["id"].split(":")
            path = Path(row["audio_path"])
            self.assertTrue(path.is_absolute() and path.is_file())
            self.assertEqual(path.name, f"{recording}_{index}.wav")
            self.assertEqual({k: v for k, v in row.items() if k != "audio_path"},
                             next(r for r in self.rows if r["id"] == row["id"]))
            if recording != "0903":
                # Clip 1 has a split with other bounds; the row is the unsplit clip.
                self.assertEqual(by_dest[path.name], (recording + ".mp3", int(index) * 60., int(index) * 60 + 1.25))
            else:
                self.assertEqual(by_dest[path.name], ("0903.mp3", float(index), int(index) + .5))

    def test_a_split_clip_stops_the_run_before_anything_is_cut(self):
        self.config = synthetic.write_sessions(self.root / "sessions")
        rows = [dict(r) for r in self.rows]
        rows[-1]["id"] += ".b"  # a generated split: it has no unsplit clip of its own
        self.rows_path.write_text(json.dumps(rows))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as message:
            self.audio("split.json")
        self.assertIn(f"first: {rows[-1]['id']}", message.getvalue())
        self.assertIn("split clips are not supported", message.getvalue())
        self.assertEqual(self.extracted, [])

    def test_a_missing_config_entry_stops_the_run_before_anything_is_cut(self):
        self.config = synthetic.write_sessions(self.root / "sessions")
        entries = json.loads(self.config.read_text())
        for drop, message in [("0903", "no existing audio file for 0903"), ("audio", "no existing audio file for"),
                              ("session", "no session file for")]:
            with self.subTest(drop):
                if drop == "0903":
                    changed = [e for e in entries if e["name"] != "0903"]
                else:
                    changed = [{k: v for k, v in e.items() if k != drop} if e["name"] != "0903" else e for e in entries]
                self.config.write_text(json.dumps(changed))
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.audio(f"missing-{drop}.json")
                self.assertIn(message, stderr.getvalue())
                self.assertEqual(self.extracted, [])
        self.config.write_text(json.dumps(entries))

    def test_existing_excerpts_are_kept_only_on_request(self):
        self.config = synthetic.write_sessions(self.root / "sessions")
        first = self.audio("a.json")
        self.extracted.clear()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as message:
            self.audio("b.json")
        self.assertIn("excerpts already exist", message.getvalue())
        self.assertEqual(self.audio("c.json", "--reuse-excerpts"), first)
        self.assertEqual(self.extracted, [])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.audio("c.json", "--reuse-excerpts")  # never overwrites an input file

    def test_an_interrupted_extraction_leaves_no_excerpt_behind(self):
        dest = self.root / "0511_1.wav"
        calls = []

        def ffmpeg(command, check):
            calls.append(command)
            Path(command[-1]).write_bytes(b"half an excerpt")
            if len(calls) == 1:
                raise KeyboardInterrupt

        original = prepare_audio_inputs.subprocess.run
        prepare_audio_inputs.subprocess.run = ffmpeg
        self.addCleanup(setattr, prepare_audio_inputs.subprocess, "run", original)
        with self.assertRaises(KeyboardInterrupt):
            self.real_extract(self.root / "0511.mp3", 0., 1., dest)
        self.assertEqual([p.name for p in self.root.glob("*.wav")], [])
        self.real_extract(self.root / "0511.mp3", 0., 1., dest)
        self.assertEqual([p.name for p in self.root.glob("*.wav")], ["0511_1.wav"])
        self.assertNotEqual(calls[1][-1], str(dest))  # ffmpeg never writes to the final name
        self.assertEqual(calls[1][-1][-4:], ".wav")   # but still picks the WAV container

    def titles(self, name: str = "title-input.json") -> list[dict]:
        out = self.root / name
        prepare_title_inputs.main(["--eg2-meta", str(self.inputs["eg2"]), "--snapshot", str(self.inputs["snapshot"]),
                                   "--out", str(out), "--input-hashes", str(self.inputs["hashes"])])
        return json.loads(out.read_text())

    def test_title_rows_are_the_approved_clips_in_source_order(self):
        rows = self.titles()
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        meta = json.loads(self.inputs["eg2"].read_text())
        first = {}
        for m in meta:
            first.setdefault((m["rec"], m["idx"]), m)
        approved = [m for m in first.values() if m["status"] in ("exported", "group2")]
        self.assertTrue(any(m["status"] == "group2" for m in approved))
        self.assertLess(len(approved), len(first))
        legacy = [r for r in rows if r["recording"] != "0903"]
        self.assertEqual([(r["id"], r["text"], r["approved"]) for r in legacy],
                         [(f"{m['rec']}:{m['idx']}", m["srt_text"], m["title"]) for m in approved])
        self.assertEqual(rows[:len(legacy)], legacy)  # generated rows come last
        generated = rows[len(legacy):]
        self.assertTrue(generated)
        for r in generated:
            cid = int(r["id"].split(":")[1])
            self.assertEqual(r["text"], f"generated {cid}")
            # The last exported title wins over the current title.
            self.assertEqual(r["approved"], f"exported {cid}" if cid % 3 == 0 else f"generated {cid}?")

    def test_edited_ignores_punctuation_like_the_title_experiment(self):
        rows = self.titles()
        self.assertEqual({r["edited"] for r in rows}, {True, False})
        for r in rows:
            self.assertEqual(r["edited"], experiment_titles.normalize(r["text"])
                             != experiment_titles.normalize(r["approved"]))
        for text in ("真的！？", "Ａ b．c", "好 耶~"):
            self.assertEqual(prepare_title_inputs.normalize(text), experiment_titles.normalize(text))
        selected, _ = experiment_titles.select(rows, 3)  # the experiment accepts these rows as they are
        self.assertTrue(selected)


if __name__ == "__main__":
    unittest.main()
