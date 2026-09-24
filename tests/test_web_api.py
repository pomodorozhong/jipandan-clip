import tempfile
import os
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from jipandan.core.waveform_envelope import WaveformEnvelopeCache
from jipandan.web.api import create_app
from jipandan.web.service import SessionService


SRT = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.audio = self.root / "audio.mp3"
        self.audio.write_bytes(b"A" * 4096)
        self.srt = self.root / "audio.srt"
        self.srt.write_text(SRT, encoding="utf-8")
        self.probe = patch("jipandan.web.service.probe_duration_seconds", return_value=10.0)
        self.probe.start()
        self.service = SessionService(self.root / "clips", self.root / "uploads")
        self.client = TestClient(create_app(self.service, allowed_hosts={"testserver"}))
        self.token = self.client.get("/api/bootstrap").json()["token"]
        self.headers = {"x-jipandan-token": self.token}

    def tearDown(self):
        self.probe.stop()
        self.client.close()
        self.directory.cleanup()

    def open(self):
        result = self.client.post(
            "/api/session/open", json={"path": str(self.audio)}, headers=self.headers
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_open_edit_undo_and_reload(self):
        state = self.open()
        self.assertEqual(state["revision"], 1)
        marked = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "group1"},
            headers=self.headers,
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.json()["candidates"][0]["status"], "group1")
        stale = self.client.patch(
            "/api/clips/2", json={"expected_revision": 1, "status": "group2"},
            headers=self.headers,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["session"]["revision"], 2)
        trim = self.client.patch(
            "/api/clips/1", json={"expected_revision": 2, "start_ms": 1100, "end_ms": 1900},
            headers=self.headers,
        )
        self.assertEqual(trim.status_code, 200)
        self.assertEqual(trim.json()["candidates"][0]["start_ms"], 1100)
        undone = self.client.post(
            "/api/session/undo", json={"expected_revision": 3}, headers=self.headers
        )
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(undone.json()["candidates"][0]["start_ms"], 1000)
        self.assertEqual(undone.json()["candidates"][0]["status"], "group1")
        reopened = SessionService(self.root / "clips")
        reopened.open_audio(self.audio)
        self.assertEqual(reopened.snapshot()["candidates"][0]["status"], "group1")

    def test_bulk_skip_and_invalid_bounds(self):
        self.open()
        bad = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "start_ms": 2000, "end_ms": 2000},
            headers=self.headers,
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.service.snapshot()["revision"], 1)
        skipped = self.client.post(
            "/api/clips/bulk-skip",
            json={"expected_revision": 1, "clip_ids": ["1", "2"]}, headers=self.headers,
        )
        self.assertEqual(skipped.status_code, 200)
        self.assertEqual(skipped.json()["changed_clip_ids"], ["1", "2"])
        undone = self.client.post(
            "/api/session/undo", json={"expected_revision": 2}, headers=self.headers,
        )
        self.assertEqual(undone.json()["counts"]["pending"], 2)

    def test_millisecond_trim_survives_reload_and_rejects_invalid_duration(self):
        self.open()
        trimmed = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "start_ms": 1101, "end_ms": 1907},
            headers=self.headers,
        )
        self.assertEqual(trimmed.status_code, 200)
        self.assertEqual(trimmed.json()["candidates"][0]["start_ms"], 1101)
        self.assertEqual(trimmed.json()["candidates"][0]["end_ms"], 1907)
        reopened = SessionService(self.root / "clips")
        self.assertEqual(reopened.open_audio(self.audio)["candidates"][0]["end_ms"], 1907)
        invalid = self.client.patch(
            "/api/clips/1", json={"expected_revision": 2, "start_ms": 1900, "end_ms": 1909},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.service.snapshot()["revision"], 2)

    def test_waveform_windows_are_bounded_and_cached_by_source_identity(self):
        self.open()
        envelope = WaveformEnvelopeCache(
            times=np.array([0.25, 0.75]), mins=np.array([-0.25, -0.5]),
            maxs=np.array([0.4, 0.8]), duration=1.0, buckets=2,
        )
        with patch("jipandan.web.waveform.build_envelope_from_audio_slice", return_value=envelope) as decode:
            path = "/api/waveforms/1?start_ms=1000&end_ms=2000&buckets=800"
            first = self.client.get(path)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["mins"], [-0.25, -0.5])
            self.assertEqual(first.json()["maxs"], [0.4, 0.8])
            decode.assert_called_once_with(self.audio.resolve(), 1.0, 1.0, 800)
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(decode.call_count, 1)
            self.audio.write_bytes(b"B" * 4097)
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(decode.call_count, 2)
        self.assertEqual(self.client.get("/api/waveforms/1?start_ms=0&end_ms=10001").status_code, 422)
        self.assertEqual(self.client.get("/api/waveforms/1?start_ms=2000&end_ms=1000").status_code, 422)
        self.assertEqual(self.client.get("/api/waveforms/unknown?start_ms=0&end_ms=1000").status_code, 422)
        self.assertEqual(self.client.get("/api/waveforms/1?start_ms=0&end_ms=1000&buckets=2000").status_code, 422)
        self.service.duration_ms = 200_000
        self.assertEqual(self.client.get("/api/waveforms/1?start_ms=0&end_ms=120001").status_code, 422)
        with patch("jipandan.web.waveform.build_envelope_from_audio_slice",
                   side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])):
            unavailable = self.client.get("/api/waveforms/1?start_ms=2000&end_ms=3000")
        self.assertEqual(unavailable.status_code, 503)
        self.assertIn("Could not decode", unavailable.json()["detail"])

    def test_srt_merge_requires_explicit_removal(self):
        self.open()
        self.srt.write_text(SRT.split("\n\n")[0] + "\n", encoding="utf-8")
        preview = self.client.get("/api/session/merge-preview").json()
        self.assertEqual(preview["removed"], [2])
        self.assertEqual(len(self.client.get("/api/session").json()["candidates"]), 2)
        kept = self.client.post(
            "/api/session/merge", json={
                "expected_revision": 1, "srt_fingerprint": preview["srt_fingerprint"],
                "remove_indexes": [],
            }, headers=self.headers,
        )
        self.assertEqual(len(kept.json()["candidates"]), 2)
        removed = self.client.post(
            "/api/session/merge", json={
                "expected_revision": 2, "srt_fingerprint": preview["srt_fingerprint"],
                "remove_indexes": [2],
            }, headers=self.headers,
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(len(removed.json()["candidates"]), 1)
        self.assertEqual(len(list(self.root.glob("*.bak"))), 1)

    def test_older_session_warns_on_possible_text_only_change(self):
        self.open()
        session_path = self.audio.with_suffix(".jipandan.json")
        data = json.loads(session_path.read_text(encoding="utf-8"))
        data.pop("srt_fingerprint", None)
        for candidate in data["candidates"]:
            candidate.pop("source_text", None)
        session_path.write_text(json.dumps(data), encoding="utf-8")
        self.srt.write_text(SRT.replace("First", "Reworded"), encoding="utf-8")
        newer = session_path.stat().st_mtime + 10
        os.utime(self.srt, (newer, newer))
        reopened = SessionService(self.root / "clips")
        state = reopened.open_audio(self.audio)
        self.assertTrue(state["merge_preview"]["text_change_unverified"])
        self.assertEqual(state["merge_preview"]["text_changed"], [])
        self.assertEqual(state["candidates"][0]["title"], "First")

    def test_local_security_and_audio_range(self):
        self.assertEqual(self.client.post("/api/session/open", json={"path": str(self.audio)}).status_code, 403)
        denied = self.client.post(
            "/api/session/open", json={"path": str(self.audio)}, headers={
                **self.headers, "origin": "https://example.com"
            },
        )
        self.assertEqual(denied.status_code, 403)
        self.open()
        self.assertEqual(self.client.get("/api/audio?token=wrong").status_code, 403)
        media = self.client.get(
            f"/api/audio?token={self.token}", headers={"range": "bytes=0-99"}
        )
        self.assertEqual(media.status_code, 206)
        self.assertEqual(media.content, b"A" * 100)

    def test_missing_audio_and_srtless_open(self):
        missing = self.client.post(
            "/api/session/open", json={"path": str(self.root / 'missing.mp3')},
            headers=self.headers,
        )
        self.assertEqual(missing.status_code, 404)
        self.srt.unlink()
        state = self.open()
        self.assertTrue(state["needs_transcription"])
        self.assertEqual(state["candidates"], [])

    def test_browser_upload_streams_into_managed_directory(self):
        result = self.client.post(
            "/api/session/upload", files={"file": ("picked.mp3", b"B" * 4096, "audio/mpeg")},
            headers=self.headers,
        )
        self.assertEqual(result.status_code, 200, result.text)
        imported = Path(result.json()["audio"])
        self.assertTrue(imported.is_relative_to((self.root / "uploads").resolve()))
        self.assertEqual(imported.read_bytes(), b"B" * 4096)
        self.assertTrue(result.json()["needs_transcription"])

    def test_second_server_cannot_overwrite_first_server(self):
        self.open()
        second_service = SessionService(self.root / "clips")
        second_service.open_audio(self.audio)
        second_client = TestClient(create_app(second_service, allowed_hosts={"testserver"}))
        second_token = second_client.get("/api/bootstrap").json()["token"]
        first = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "group1"},
            headers=self.headers,
        )
        self.assertEqual(first.status_code, 200)
        stale = second_client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "skipped"},
            headers={"x-jipandan-token": second_token},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["session"]["candidates"][0]["status"], "group1")
        second_client.close()


if __name__ == "__main__":
    unittest.main()
