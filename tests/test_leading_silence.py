import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jipandan.core.leading_silence import detect_leading_silence_start


class LeadingSilenceTests(unittest.TestCase):
    def detect(self, samples):
        with patch("jipandan.core.leading_silence.decode_audio_slice_mono_f32", return_value=samples):
            return detect_leading_silence_start(Path("recording.mp3"), 1000, 2000)

    def test_long_gap_keeps_preroll_before_sustained_activity(self):
        samples = np.concatenate((np.zeros(4000), np.full(4000, 0.1))).astype(np.float32)
        start = self.detect(samples)
        self.assertIsNotNone(start)
        self.assertGreaterEqual(start, 1360)
        self.assertLessEqual(start, 1400)

    def test_silence_immediate_activity_and_short_transients_are_unchanged(self):
        transient = np.zeros(8000, dtype=np.float32)
        transient[4000:4080] = 0.1
        for samples in (np.zeros(8000), np.full(8000, 0.1), transient):
            with self.subTest(samples=samples):
                self.assertIsNone(self.detect(samples))
