import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from jipandan.core.ffmpeg import (
    NO_AUDIO_LEFT, ExportOptions, _audio_filter_for_options, _extract_audio_slice, render_export_preview,
)
from jipandan.core.models import ClipCandidate
from jipandan.core.trim_map import retained_ranges
from jipandan.web.preview import PreviewJobs


class TrimMapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def pcm(self, name, samples, rate=1000):
        path = self.root / name
        samples = np.asarray(samples, dtype="<i4")
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
            output.setsampwidth(4)
            output.setframerate(rate)
            output.writeframes(samples.tobytes())
        return path

    def test_maps_multiple_cuts_in_stereo_and_retained_leading_silence(self):
        source = np.random.default_rng(1).integers(-10000, 10000, (3000, 2), dtype=np.int32)
        source[500:600] = 0
        kept = np.concatenate([source[500:1000], source[1800:2400]])
        result = retained_ranges(self.pcm("source.wav", source), self.pcm("kept.wav", kept))
        self.assertEqual(result["kept_ranges_ms"], [[500, 1000], [1800, 2400]])
        self.assertEqual(result["duration_ms"], 1100)
        self.assertTrue(PreviewJobs._valid_trim_map(result))

    def test_handles_no_cuts_empty_result_and_invalid_audio(self):
        source = np.arange(1000, dtype=np.int32)
        original = self.pcm("source.wav", source)
        self.assertEqual(retained_ranges(original, original)["kept_ranges_ms"], [[0, 1000]])
        self.assertEqual(retained_ranges(original, self.pcm("empty.wav", []))["kept_ranges_ms"], [])
        with self.assertRaises(ValueError):
            retained_ranges(original, self.pcm("different.wav", [-100, -200]))

    def test_cache_rejects_invalid_trim_geometry(self):
        for ranges in ([[100, 50]], [[0, 1200]], [[0, 200], [100, 300]], [[float("nan"), 200]]):
            self.assertFalse(PreviewJobs._valid_trim_map({
                "source_duration_ms": 1000, "duration_ms": 200, "kept_ranges_ms": ranges,
            }))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_real_filter_maps_edges_and_middle_and_keeps_export_audio(self):
        rate = 44100
        rng = np.random.default_rng(2)
        speech = rng.integers(-300_000_000, 300_000_000, rate, dtype=np.int32)
        silence = np.zeros(rate, dtype=np.int32)
        audio = self.pcm("input.wav", np.concatenate([silence, speech, silence, speech, np.zeros(rate * 3 // 2)]), rate)
        clip = ClipCandidate(1, "test", "00:00:00.000", "00:00:05.500", "00:00:00.000", "5.500")
        source = self.root / "slice.mp3"
        _extract_audio_slice(audio, clip.start, clip.duration, source)
        for mode in ("trim_edges", "trim_all"):
            with self.subTest(mode=mode):
                output = self.root / f"{mode}.mp3"
                result = render_export_preview(audio, clip, ExportOptions(mode), output)
                self.assertIsNotNone(result)
                self.assertTrue(PreviewJobs._valid_trim_map(result))
                ranges = result["kept_ranges_ms"]
                self.assertGreater(ranges[0][0], 500)
                self.assertLess(ranges[-1][1], 5400)
                self.assertLess(result["duration_ms"], result["source_duration_ms"])
                if mode == "trim_all":
                    self.assertTrue(any(right[0] - left[1] > 400 for left, right in zip(ranges, ranges[1:])))
                decoded = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(output), "-f", "s32le", "pipe:1",
                ], capture_output=True, check=True).stdout
                self.assertAlmostEqual(len(decoded) / 4 / rate * 1000, result["rendered_duration_ms"], delta=1)
                baseline = self.root / f"baseline-{mode}.mp3"
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-i", str(source),
                    "-af", _audio_filter_for_options(ExportOptions(mode)), str(baseline),
                ], check=True)
                expected = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(baseline), "-f", "s32le", "pipe:1",
                ], capture_output=True, check=True).stdout
                self.assertEqual(decoded, expected)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_trimming_away_all_audio_reports_a_plain_message(self):
        audio = self.pcm("silent.wav", np.zeros(44100, dtype=np.int32), 44100)
        clip = ClipCandidate(1, "test", "00:00:00.000", "00:00:00.100", "00:00:00.000", "0.100")
        with self.assertRaises(RuntimeError) as raised:
            render_export_preview(audio, clip, ExportOptions("trim_edges"), self.root / "empty.mp3")
        self.assertEqual(str(raised.exception), NO_AUDIO_LEFT)


if __name__ == "__main__":
    unittest.main()
