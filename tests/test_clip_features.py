import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from jipandan.core.clip_features import (
    SAMPLE_RATE,
    compute_clip_features,
    features_from_samples,
    likely_keep_scores,
)
from jipandan.core.models import Session
from jipandan.core.store import RecordingStore, store_path
from jipandan.core.srt import segment_scores_path
from jipandan.core.whisper import write_segment_scores


SRT = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"


def tone(frequency: float, seconds: float, amplitude: float) -> np.ndarray:
    times = np.arange(round(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * frequency * times)).astype(np.float32)


class ClipFeatureTests(unittest.TestCase):
    def test_voice_band_and_bass_shares_follow_the_dominant_tone(self):
        voice = features_from_samples(tone(1000, 1.0, 0.5))
        bass = features_from_samples(tone(100, 1.0, 0.05))
        self.assertGreater(voice.peak_db, bass.peak_db)
        self.assertGreater(voice.mid_share_db, bass.mid_share_db)
        self.assertGreater(bass.bass_share_db, voice.bass_share_db)

    def test_very_short_clips_report_loudness_only_or_nothing(self):
        self.assertIsNone(features_from_samples(np.zeros(10, np.float32)))
        short = features_from_samples(tone(1000, 0.05, 0.5))
        self.assertIsNotNone(short.peak_db)
        self.assertIsNone(short.mid_share_db)

    def test_streaming_decode_measures_unordered_spans_and_spans_past_the_end(self):
        quiet, loud = tone(1000, 2.0, 0.01), tone(1000, 2.0, 0.5)
        samples = np.concatenate([quiet, loud, quiet])
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            subprocess.run(
                ["ffmpeg", "-loglevel", "quiet", "-f", "f32le", "-ar", str(SAMPLE_RATE),
                 "-ac", "1", "-i", "pipe:0", str(audio)],
                input=samples.tobytes(), check=True,
            )
            progress = []
            results = compute_clip_features(
                audio, [(2.2, 3.8), (0.2, 1.8), (30.0, 31.0)],
                progress=lambda finished: progress.append(finished) is None,
            )
        loud_clip, quiet_clip, missing = results
        self.assertGreater(loud_clip.peak_db - quiet_clip.peak_db, 25)
        self.assertIsNone(missing)
        self.assertEqual(progress, [1, 2, 3])

    def test_score_averages_available_signal_ranks(self):
        rows = [
            SimpleNamespace(peak_db=-10.0, no_speech_prob=0.1, mid_share_db=-2.0, bass_share_db=-20.0),
            SimpleNamespace(peak_db=-30.0, no_speech_prob=0.9, mid_share_db=-9.0, bass_share_db=-3.0),
            SimpleNamespace(peak_db=-20.0, no_speech_prob=None, mid_share_db=None, bass_share_db=None),
            SimpleNamespace(peak_db=None, no_speech_prob=None, mid_share_db=None, bass_share_db=None),
        ]
        self.assertEqual(likely_keep_scores(rows), [100.0, 0.0, 50.0, None])


class SegmentScoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.audio = self.root / "audio.mp3"
        self.audio.write_bytes(b"audio")
        self.srt = self.root / "audio.srt"
        self.srt.write_text(SRT, encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_session_reads_scores_only_for_the_matching_srt(self):
        write_segment_scores(self.srt, [
            {"avg_logprob": -0.2, "no_speech_prob": 0.05, "compression_ratio": 1.1},
            {"avg_logprob": float("nan"), "no_speech_prob": 0.7},
        ])
        session = Session.from_srt(self.audio, self.srt, self.root / "clips")
        self.assertEqual(
            [(c.avg_logprob, c.no_speech_prob) for c in session.candidates],
            [(-0.2, 0.05), (None, 0.7)],
        )
        store = RecordingStore(store_path(self.audio))
        try:
            store.create(session)
            self.assertEqual(store.load().candidates[1].no_speech_prob, 0.7)
        finally:
            store.close()

        self.srt.write_text(SRT.replace("Second", "Edited"), encoding="utf-8")
        edited = Session.from_srt(self.audio, self.srt, self.root / "clips")
        self.assertEqual([c.no_speech_prob for c in edited.candidates], [None, None])
        self.assertEqual(json.loads(segment_scores_path(self.srt).read_text())["version"], 1)

    def test_merge_and_duplicate_keep_measured_signals(self):
        session = Session.from_srt(self.audio, self.srt, self.root / "clips")
        session.candidates[0].peak_db = -12.0
        session.candidates[1].peak_db = -30.0
        session.clip_features_complete = True
        duplicate = session.duplicate_candidate("1")
        self.assertEqual(duplicate.peak_db, -12.0)
        self.srt.write_text(SRT.replace("00:00:03,000", "00:00:02,500"), encoding="utf-8")
        session.merge_with_srt()
        self.assertEqual([c.peak_db for c in session.candidates], [-12.0, -12.0, None])
        self.assertFalse(session.clip_features_complete)


if __name__ == "__main__":
    unittest.main()
