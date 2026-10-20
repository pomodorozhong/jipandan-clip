import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jipandan.core import ffmpeg, whisper
from jipandan.core.candidates import candidates_srt_path
from jipandan.core.models import Session
from jipandan.core.srt import load_segment_scores, parse_srt
from jipandan.core.snap_points import load_snap_points, snap_points_path


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
        self.srt.write_text(SRT.split("\n\n")[0] + "\n", encoding="utf-8")
        self.assertEqual(session.srt_merge_preview()["removed"], [2])
        self.assertEqual([c.clip_id for c in session.candidates], ["1", "2", "2-2"])
        session.merge_with_srt()
        self.assertEqual([c.clip_id for c in session.candidates], ["1", "2", "2-2"])
        self.assertEqual(session.get_candidate("2").status, "group1")
        session.merge_with_srt(remove_missing=True)
        self.assertEqual([c.clip_id for c in session.candidates], ["1"])

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

    def transcribe_with_words(self, speech):
        calls = []

        def transcribe(*args, **kwargs):
            calls.append(kwargs)
            return {"segments": [
                {"start": 1, "end": 2, "text": "First",
                 "words": [{"start": 1.0, "end": 1.4}, {"start": 1.5, "end": 2.0}]},
                {"start": 3, "end": 4, "text": "Second", "words": [{"start": 3.0004, "end": 4.0}]},
            ]}

        with patch.dict(sys.modules, {"mlx_whisper": types.SimpleNamespace(transcribe=transcribe)}), \
             patch.object(whisper, "configure_progress_bars"), \
             patch.object(whisper, "_speech_probabilities", side_effect=speech):
            whisper.transcribe_to_text(self.audio, self.srt)
        self.assertTrue(calls[0]["word_timestamps"])
        fingerprint = hashlib.sha256(self.srt.read_bytes()).hexdigest()
        return load_snap_points(self.srt, fingerprint)

    @staticmethod
    def speech(*frames):
        """Silero probabilities with speech in each (first, last) span of 32 ms frames."""
        def probabilities(audio):
            values = np.zeros(200, np.float32)
            for first, last in frames:
                values[first:last] = 0.9
            return values
        return probabilities

    def test_transcription_saves_word_starts_and_speech_ends(self):
        points = self.transcribe_with_words(self.speech((31, 66), (94, 131)))
        self.assertEqual(points, {"word_start": [1000, 1500, 3000], "speech_end": [2112, 4192]})

    def test_transcription_saves_generated_candidates_beside_the_srt(self):
        self.transcribe_with_words(self.speech((31, 66), (94, 131)))
        candidates = candidates_srt_path(self.srt)
        self.assertEqual(candidates.name, "audio.candidates.srt")
        entries = parse_srt(candidates)
        # Each speech run starts 0.2 s early; the segments snap to the same bounds.
        self.assertEqual(
            [(e.start, e.end, e.text) for e in entries],
            [("00:00:00,792", "00:00:02,112", "First"), ("00:00:02,808", "00:00:04,192", "Second")],
        )
        fingerprint = hashlib.sha256(candidates.read_bytes()).hexdigest()
        self.assertEqual(sorted(load_segment_scores(candidates, fingerprint)), [1, 2])
        self.assertEqual(load_snap_points(candidates, fingerprint)["speech_end"], [2112, 4192])

    def test_failed_voice_activity_keeps_transcript_and_word_starts(self):
        def fail(audio):
            raise RuntimeError("no model")

        stale = candidates_srt_path(self.srt)
        stale.write_text(SRT, encoding="utf-8")
        self.assertEqual(self.transcribe_with_words(fail), {"word_start": [1000, 1500, 3000]})
        self.assertFalse(stale.exists())

    def test_snap_points_from_another_srt_are_ignored(self):
        self.transcribe_with_words(self.speech((31, 66)))
        self.assertTrue(snap_points_path(self.srt).is_file())
        self.assertEqual(load_snap_points(self.srt, "other"), {})

if __name__ == "__main__":
    unittest.main()
