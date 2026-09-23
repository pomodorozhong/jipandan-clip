import json
import os
import shutil
import tempfile
import unittest
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
            for suffix in (".mp3", ".srt", ".jipandan.json"):
                shutil.copy2(Path("raw") / f"0524{suffix}", root / f"0524{suffix}")
            session_path = root / "0524.jipandan.json"
            data = json.loads(session_path.read_text(encoding="utf-8"))
            data["audio"] = str(root / "0524.mp3")
            data["srt"] = str(root / "0524.srt")
            data["clip_dir"] = str(root / "clips")
            session_path.write_text(json.dumps(data), encoding="utf-8")

            app = JipandanApp(root / "0524.mp3", clip_dir=root / "clips")
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)
                self.assertEqual(json.loads(session_path.read_text()).get("revision", 0), 0)
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
