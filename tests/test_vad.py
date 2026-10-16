import types
import unittest
from unittest.mock import patch

import numpy as np

from jipandan.core import vad


class SpeechRunTests(unittest.TestCase):
    def test_runs_merge_short_gaps_and_drop_short_runs(self):
        # 32 ms frames: speech 0–5, gap of 2 frames (64 ms, merged), speech 7–10,
        # a 4-frame gap, a 2-frame blip (64 ms, dropped), another 4-frame gap, then speech 20–25.
        probabilities = np.zeros(30, np.float32)
        probabilities[0:5] = probabilities[7:10] = probabilities[14:16] = probabilities[20:25] = 0.9
        self.assertEqual(vad.speech_runs(probabilities), [(0, 320), (640, 800)])

    def test_threshold_is_exclusive(self):
        self.assertEqual(vad.speech_runs(np.full(10, 0.5, np.float32)), [])


class SpeechProbabilityTests(unittest.TestCase):
    def test_chunks_run_as_one_batch_with_context_and_state(self):
        seen = []

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, _outputs, inputs):
                seen.append(inputs)
                frame = inputs["input"]
                # Report each frame's last sample so the order can be checked.
                return frame[:, -1:].copy(), inputs["state"] + 1

        fake = types.SimpleNamespace(
            InferenceSession=FakeSession, SessionOptions=lambda: types.SimpleNamespace(),
        )
        samples = np.arange(5 * vad.FRAME_SAMPLES, dtype=np.float32)
        with patch.dict("sys.modules", {"onnxruntime": fake}), \
             patch.object(vad, "CHUNK_SAMPLES", 2 * vad.FRAME_SAMPLES):
            probabilities = vad.speech_probabilities(samples[:-10], model="model.onnx")

        frame_ends = samples[vad.FRAME_SAMPLES - 1::vad.FRAME_SAMPLES]
        self.assertEqual(probabilities.tolist(), [*frame_ends[:4].tolist(), 0.0])
        self.assertEqual(seen[0]["input"].shape, (3, vad.CONTEXT_SAMPLES + vad.FRAME_SAMPLES))
        self.assertFalse(seen[0]["input"][:, :vad.CONTEXT_SAMPLES].any())
        np.testing.assert_array_equal(
            seen[1]["input"][0, :vad.CONTEXT_SAMPLES],
            samples[vad.FRAME_SAMPLES - vad.CONTEXT_SAMPLES:vad.FRAME_SAMPLES],
        )
        self.assertEqual(seen[1]["state"].shape, (2, 3, 128))
        self.assertTrue((seen[1]["state"] == 1).all())


if __name__ == "__main__":
    unittest.main()
