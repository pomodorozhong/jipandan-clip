import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jipandan.core import ffmpeg


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class FastSeekTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.audio = Path(self.directory.name) / "tone.mp3"
        # A rising chirp, so any timing offset changes the decoded samples.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*(200+20*t)*t):s=44100:d=40",
             "-b:a", "128k", str(self.audio)],
            check=True,
        )
        ffmpeg._fast_seek_checks.clear()

    def tearDown(self):
        ffmpeg._fast_seek_checks.clear()
        self.directory.cleanup()

    def decode(self, before, after):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", *before, "-i", str(self.audio), *after, "-t", "2", "-ac", "1",
             "-f", "f32le", "pipe:1"], check=True, capture_output=True,
        ).stdout
        return np.frombuffer(raw, np.float32)

    def test_fast_seek_matches_decoding_from_the_start(self):
        self.assertTrue(ffmpeg.fast_seek_is_exact(self.audio))
        before, after = ffmpeg.seek_arguments(self.audio, 27.3)
        self.assertEqual(before[0], "-ss")
        fast = self.decode(before, after)
        exact = self.decode([], ["-ss", "27.3"])
        self.assertEqual(len(fast), len(exact))
        self.assertLess(float(np.max(np.abs(fast - exact))), 1e-4)

    def test_files_that_seek_inexactly_fall_back_to_decoding_from_the_start(self):
        with patch.object(ffmpeg, "_max_abs_difference", return_value=0.5):
            self.assertFalse(ffmpeg.fast_seek_is_exact(self.audio))
        self.assertEqual(ffmpeg.seek_arguments(self.audio, 27.3), ([], ["-ss", "27.300000"]))
        self.assertEqual(ffmpeg.seek_arguments(self.audio, 0), ([], []))


if __name__ == "__main__":
    unittest.main()
