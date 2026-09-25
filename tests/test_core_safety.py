import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jipandan.core import ffmpeg, whisper
from jipandan.core.models import ConcurrentSessionChange, Session
from jipandan.tui.clip_list import ClipListController
from jipandan.tui.screens.export_preview import build_export_preview_artifacts


SRT = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"


class SessionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.audio = self.root / "audio.mp3"
        self.audio.write_bytes(b"audio")
        self.srt = self.root / "audio.srt"
        self.srt.write_text(SRT, encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def session(self):
        return Session.from_srt(self.audio, self.srt, self.root / "clips")

    def test_merge_keeps_missing_reviewed_clip_and_duplicate(self):
        session = self.session()
        session.candidates[1].status = "group1"
        session.duplicate_candidate("2")
        session.save()
        self.srt.write_text(SRT.split("\n\n")[0] + "\n", encoding="utf-8")
        before = session.session_path.read_bytes()
        self.assertEqual(session.srt_merge_preview()["removed"], [2])
        self.assertEqual(before, session.session_path.read_bytes())
        session.merge_with_srt()
        self.assertEqual([c.clip_id for c in session.candidates], ["1", "2", "2-2"])
        self.assertEqual(session.get_candidate("2").status, "group1")
        session.merge_with_srt(remove_missing=True)
        self.assertEqual([c.clip_id for c in session.candidates], ["1"])
        backups = list(self.root.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_merge_refreshes_unedited_bounds_and_text(self):
        session = self.session()
        edited = session.duplicate_candidate("1")
        edited.title = "My custom title"
        session.nudge_start(edited.clip_id, 0.1)
        original_edited_start = edited.start
        self.srt.write_text(
            SRT.replace("00:00:01,000 --> 00:00:02,000\nFirst",
                        "00:00:01,500 --> 00:00:02,500\nUpdated"),
            encoding="utf-8",
        )
        preview = session.srt_merge_preview()
        self.assertEqual(preview["timing_changed"], [1])
        self.assertEqual(preview["text_changed"], [1])
        session.merge_with_srt()
        self.assertEqual(session.get_candidate("1").start, "00:00:01.500")
        self.assertEqual(session.get_candidate("1").title, "Updated")
        self.assertEqual(session.get_candidate("1-2").start, original_edited_start)
        self.assertEqual(session.get_candidate("1-2").title, "My custom title")

    def test_atomic_save_rejects_stale_writer(self):
        session = self.session()
        session.save()
        other = Session.load(session.session_path)
        session.candidates[0].status = "group2"
        session.save()
        other.candidates[0].status = "skipped"
        with self.assertRaises(ConcurrentSessionChange):
            other.save()
        stored = json.loads(session.session_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["candidates"][0]["status"], "group2")
        self.assertEqual(stored["revision"], 2)

    def test_search_stays_in_selected_filter(self):
        session = self.session()
        session.candidates[0].title = "match one"
        session.candidates[1].title = "match two"
        session.candidates[0].status = "group1"
        controller = ClipListController(session, on_selection_changed=lambda _: None)
        controller.filter_mode = "group1"
        controller.set_search_query("match")
        self.assertEqual([c.clip_id for c in controller.visible_candidates()], ["1"])

    def test_preview_jobs_use_different_paths(self):
        session = self.session()
        paths = []

        def fake_export(audio, candidate, clip_dir, **kwargs):
            output = clip_dir / "preview.mp3"
            output.write_bytes(b"preview")
            paths.append(output)
            return output

        with patch("jipandan.tui.screens.export_preview.ffmpeg.export_clip", fake_export), patch(
            "jipandan.tui.screens.export_preview.ffmpeg.probe_duration_seconds", return_value=1.0
        ):
            first = build_export_preview_artifacts(
                self.audio, session.candidates[0], ffmpeg.ExportOptions("as_is"),
                preview_dir=self.root / "previews",
            )
            second = build_export_preview_artifacts(
                self.audio, session.candidates[0], ffmpeg.ExportOptions("trim_all"),
                preview_dir=self.root / "previews",
            )
        self.assertNotEqual(first.preview_path, second.preview_path)
        self.assertTrue(all(path.exists() for path in paths))

    def test_existing_export_gets_new_name(self):
        first = self.root / "clip.mp3"
        first.write_bytes(b"old")
        source = self.root / "temporary.mp3"
        source.write_bytes(b"new")
        second = ffmpeg._publish_clip(source, first, replace_existing=False)
        self.assertEqual(second.name, "clip (2).mp3")
        self.assertEqual(first.read_bytes(), b"old")
        self.assertEqual(second.read_bytes(), b"new")

    def test_failed_transcription_preserves_existing_srt(self):
        old = self.srt.read_bytes()
        fake = types.SimpleNamespace(transcribe=lambda *a, **k: {
            "segments": [{"start": 2, "end": 1, "text": "bad"}]
        })
        with patch.dict(sys.modules, {"mlx_whisper": fake}), patch.object(
            whisper, "configure_progress_bars"
        ):
            with self.assertRaises(ValueError):
                whisper.transcribe_to_text(self.audio, self.srt)
        self.assertEqual(self.srt.read_bytes(), old)
        self.assertEqual(list(self.root.glob(".audio.srt.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
