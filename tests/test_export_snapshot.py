import copy
import tempfile
import unittest
from pathlib import Path

from dataclasses import asdict
from jipandan.core.models import ClipCandidate, Session, clip_candidate_from_dict
from jipandan.core.store import RecordingStore


class ExportSnapshotTests(unittest.TestCase):
    def exported(self):
        clip = ClipCandidate(1, "First", "00:00:01.000", "00:00:02.000", "00:00:01.000", "1.000",
                             status="exported", last_export_path="/exports/first.mp3", last_export_title="First",
                             last_export_mode="trim_edges", last_export_start_threshold_db=-40,
                             last_export_stop_threshold_db=-50)
        clip.last_export_snapshot = clip.export_snapshot()
        return clip

    def test_title_bounds_and_render_settings_change_the_match(self):
        original = self.exported()
        self.assertEqual(original.export_state, "matching")
        for field, value in (("title", "Changed"), ("start", "00:00:01.010"), ("duration", "0.500"),
                             ("last_export_mode", "trim_all"), ("last_export_start_threshold_db", -30),
                             ("last_export_stop_threshold_db", -20)):
            clip = copy.deepcopy(original)
            setattr(clip, field, value)
            self.assertEqual(clip.export_state, "changed", field)
            self.assertEqual(clip.last_export_snapshot["title"], "First")
        original.last_export_snapshot = None
        self.assertEqual(original.export_state, "unknown")
        original.last_export_path = None
        self.assertEqual(original.export_state, "none")
        older = asdict(self.exported())
        del older["last_export_snapshot"]
        self.assertEqual(clip_candidate_from_dict(older).export_state, "unknown")

    def test_store_reopen_and_srt_merge_preserve_the_published_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            srt = root / "audio.srt"
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nFirst\n")
            session = Session.from_srt(audio, srt, root / "exports")
            session.candidates[0] = self.exported()
            store = RecordingStore(root / "session.db")
            self.addCleanup(store.close)
            store.create(session)
            store.close()
            store = RecordingStore(root / "session.db")
            self.addCleanup(store.close)
            restored = store.load()
            store.close()
            self.assertEqual(restored.candidates[0].export_state, "matching")
            duplicate = restored.duplicate_candidate("1")
            self.assertEqual(duplicate.export_state, "none")
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nUpdated subtitle\n")
            restored.merge_with_srt()
            self.assertEqual(restored.candidates[0].last_export_snapshot, session.candidates[0].last_export_snapshot)


if __name__ == "__main__":
    unittest.main()
