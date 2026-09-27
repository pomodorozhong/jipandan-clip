import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from jipandan.tui.app import JipandanApp
from jipandan.tui.screens.review import ReviewScreen


class TuiRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_skip_and_immediate_nudge_save(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            # textual-plot currently cannot render with Textual's NO_COLOR filter.
            os.environ.pop("NO_COLOR", None)
            root = Path(directory)
            audio = root / "fixture.wav"
            with wave.open(str(audio), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8_000)
                output.writeframes(b"\x00\x00" * 8_000)
            srt = root / "fixture.srt"
            srt.write_text(
                "1\n00:00:00,200 --> 00:00:00,800\nFirst\n",
                encoding="utf-8",
            )

            app = JipandanApp(audio, srt_path=srt)
            with patch(
                "jipandan.tui.screens.review.waveform_cache_dir",
                return_value=root / "cache",
            ):
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, ReviewScreen)
                    session_path = audio.with_suffix(".jipandan.json")
                    self.assertEqual(json.loads(session_path.read_text()).get("revision", 0), 1)
                    self.assertEqual(app.screen.session.clip_dir, (root / "exports").resolve())
                    candidate = app.screen.session.candidates[0]
                    previous = candidate.start
                    app.screen._nudge_start(0.1)
                    self.assertNotEqual(candidate.start, previous)
                    self.assertEqual(
                        json.loads(session_path.read_text())["candidates"][0]["start"], candidate.start
                    )
                    await pilot.press("ctrl+shift+x")
                    await pilot.pause()
                    self.assertEqual(
                        sum(c["status"] == "skipped" for c in json.loads(session_path.read_text())["candidates"]),
                        1,
                    )
                    app.exit()
