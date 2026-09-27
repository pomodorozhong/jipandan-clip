import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jipandan.core.models import Session
from jipandan.core.paths import AppPaths, default_export_dir
from jipandan.web.service import SessionService


SRT = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n"


class StoragePathTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.audio = self.root / "audio.mp3"
        self.audio.write_bytes(b"audio")
        self.srt = self.root / "audio.srt"
        self.srt.write_text(SRT, encoding="utf-8")
        self.paths = AppPaths(
            data_dir=self.root / "data",
            cache_dir=self.root / "cache",
            log_dir=self.root / "logs",
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_new_session_defaults_to_exports_beside_audio(self):
        session = Session.from_srt(self.audio, self.srt)
        self.assertEqual(session.clip_dir, (self.root / "exports").resolve())

    def test_unwritable_source_export_path_uses_application_data(self):
        blocked = self.root / "blocked"
        blocked.mkdir()
        audio = blocked / "audio.mp3"
        audio.write_bytes(b"audio")
        (blocked / "exports").write_text("not a directory", encoding="utf-8")

        selected = default_export_dir(audio, paths=self.paths)

        self.assertTrue(selected.is_relative_to(self.paths.fallback_export_dir.resolve()))
        self.assertTrue(selected.is_dir())

    def test_web_service_uses_data_cache_and_log_roots(self):
        with patch("jipandan.web.service.probe_duration_seconds", return_value=10.0):
            service = SessionService(app_paths=self.paths)
            try:
                state = service.open_audio(self.audio)
                self.assertEqual(state["clip_dir"], str((self.root / "exports").resolve()))
                self.assertEqual(service.upload_dir, self.paths.uploads_dir.resolve())
                self.assertEqual(service._previews.root, self.paths.preview_dir.resolve())
                self.assertEqual(service._transcriptions.root, self.paths.transcription_dir.resolve())
                self.assertEqual(
                    service._transcriptions.log_root,
                    self.paths.transcription_log_dir.resolve(),
                )
            finally:
                service.close()

    def test_existing_session_keeps_saved_export_directory(self):
        saved_dir = self.root / "saved-exports"
        Session.from_srt(self.audio, self.srt, saved_dir).save()

        with patch("jipandan.web.service.probe_duration_seconds", return_value=10.0):
            service = SessionService(self.root / "new-exports", app_paths=self.paths)
            try:
                state = service.open_audio(self.audio)
                self.assertEqual(state["clip_dir"], str(saved_dir.resolve()))
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
