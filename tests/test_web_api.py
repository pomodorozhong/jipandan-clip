import tempfile
import os
import json
import subprocess
import shutil
import threading
import time
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
        self.service = SessionService(
            self.root / "clips", self.root / "uploads",
            self.root / "previews", self.root / "transcriptions",
        )
        self.client = TestClient(create_app(self.service, allowed_hosts={"testserver"}))
        self.token = self.client.get("/api/bootstrap").json()["token"]
        self.headers = {"x-jipandan-token": self.token}

    def tearDown(self):
        self.probe.stop()
        self.client.close()
        self.service.close()
        self.directory.cleanup()

    def wait_for_job(self, path, expected):
        for _ in range(200):
            state = self.client.get(path).json()
            if state["state"] == expected:
                return state
            time.sleep(0.01)
        self.fail(f"Job did not reach {expected}: {state}")

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

    def test_leading_silence_batches_share_one_undo_and_persist_completion(self):
        self.open()
        path = "/api/session/leading-silence-detection"
        with patch("jipandan.web.service.LEADING_SILENCE_BATCH_SIZE", 1), patch(
            "jipandan.web.service.detect_leading_silence_start",
            side_effect=lambda _audio, start, _end: start + 400,
        ):
            response = self.client.post(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            job = self.wait_for_job(path, "completed")
        self.assertEqual(job["adjusted"], 2)
        state = self.service.snapshot()
        self.assertEqual([clip["start_ms"] for clip in state["candidates"]], [1400, 3400])
        persisted = json.loads(self.audio.with_suffix(".jipandan.json").read_text())
        self.assertTrue(persisted["leading_silence_detection_complete"])
        undone = self.client.post("/api/session/undo", json={
            "expected_revision": state["revision"],
        }, headers=self.headers)
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual([clip["start_ms"] for clip in undone.json()["candidates"]], [1000, 3000])
        with patch("jipandan.web.service.detect_leading_silence_start") as detect:
            self.assertEqual(self.client.post(path, headers=self.headers).json()["state"], "completed")
            detect.assert_not_called()

    def test_leading_silence_preserves_manual_trim_during_detection(self):
        self.open()
        entered, release = threading.Event(), threading.Event()

        def detect(_audio, start, _end):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release detector")
            return start + 400

        path = "/api/session/leading-silence-detection"
        with patch("jipandan.web.service.detect_leading_silence_start", side_effect=detect):
            self.client.post(path, headers=self.headers)
            try:
                self.assertTrue(entered.wait(5))
                edited = self.client.patch("/api/clips/1", json={
                    "expected_revision": 1, "start_ms": 1200,
                }, headers=self.headers)
                self.assertEqual(edited.status_code, 200, edited.text)
            finally:
                release.set()
            job = self.wait_for_job(path, "completed")
        self.assertEqual(job["adjusted"], 1)
        self.assertEqual(self.service.snapshot()["candidates"][0]["start_ms"], 1200)

    def test_preview_title_change_reuses_render_and_waveform(self):
        self.open()
        envelope = WaveformEnvelopeCache(
            times=np.array([0.4]), mins=np.array([-0.25]), maxs=np.array([0.5]),
            duration=0.8, buckets=1,
        )

        def render(_audio, _candidate, _options, output):
            output.write_bytes(b"rendered audio")

        request = {"clip_id": "1", "expected_revision": 1, "mode": "as_is", "title": "First"}
        with patch("jipandan.web.preview.render_export_preview", side_effect=render) as renderer, \
             patch("jipandan.web.preview.probe_duration_seconds", return_value=0.8), \
             patch("jipandan.web.preview.build_envelope_from_audio_slice", return_value=envelope):
            first = self.client.post("/api/previews", json=request, headers=self.headers).json()
            completed = self.wait_for_job(f"/api/previews/{first['id']}", "completed")
            renamed = self.client.post("/api/previews", json={**request, "title": "Renamed"},
                                       headers=self.headers)
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()["id"], first["id"])
            self.assertEqual(renamed.json()["title"], "Renamed")
            self.assertEqual(renamed.json()["waveform"], completed["waveform"])
            renderer.assert_called_once()

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

    def test_preview_jobs_are_isolated_and_stale_after_trim(self):
        self.open()
        outputs = []

        def render(_audio, candidate, options, output):
            outputs.append(output)
            output.write_bytes(f"{candidate.clip_id}:{options.mode}".encode())

        with patch("jipandan.web.preview.render_export_preview", side_effect=render), \
             patch("jipandan.web.preview.probe_duration_seconds", return_value=0.8):
            jobs = []
            for clip_id, mode in (("1", "as_is"), ("2", "trim_all")):
                response = self.client.post("/api/previews", json={
                    "clip_id": clip_id, "expected_revision": 1, "mode": mode,
                    "title": f"Preview {clip_id}",
                }, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                jobs.append(response.json()["id"])
            for job_id in jobs:
                for _ in range(100):
                    state = self.client.get(f"/api/previews/{job_id}").json()
                    if state["state"] == "completed":
                        break
                    time.sleep(0.01)
                self.assertEqual(state["state"], "completed", state)
                self.assertFalse(state["stale"])
                self.assertEqual(self.client.get(
                    f"/api/previews/{job_id}/audio?token={self.token}").status_code, 200)
            self.assertEqual(len(set(outputs)), 2)
            self.assertEqual(len({path.parent for path in outputs}), 2)
            self.assertEqual(outputs[0].read_bytes(), b"1:as_is")
            self.assertEqual(outputs[1].read_bytes(), b"2:trim_all")
            trimmed = self.client.patch("/api/clips/1", json={
                "expected_revision": 1, "start_ms": 1100,
            }, headers=self.headers)
            self.assertEqual(trimmed.status_code, 200)
            self.assertTrue(self.client.get(f"/api/previews/{jobs[0]}").json()["stale"])
            self.assertFalse(self.client.get(f"/api/previews/{jobs[1]}").json()["stale"])
            self.assertEqual(self.client.get(
                f"/api/previews/{jobs[0]}/audio?token={self.token}").status_code, 409)

    def test_preview_failure_reports_retryable_error(self):
        self.open()
        with patch("jipandan.web.preview.render_export_preview", side_effect=RuntimeError("decode failed")):
            response = self.client.post("/api/previews", json={
                "clip_id": "1", "expected_revision": 1, "mode": "trim_edges", "title": "First",
            }, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["id"]
            for _ in range(100):
                state = self.client.get(f"/api/previews/{job_id}").json()
                if state["state"] == "failed":
                    break
                time.sleep(0.01)
            self.assertEqual(state["state"], "failed")
            self.assertIn("decode failed", state["error"])
            self.assertEqual(self.client.get(
                f"/api/previews/{job_id}/audio?token={self.token}").status_code, 409)
            self.assertEqual(self.client.post("/api/previews", json={
                "clip_id": "1", "expected_revision": 1, "mode": "trim_edges",
                "title": "First", "start_threshold_db": -100,
            }, headers=self.headers).status_code, 422)

    def test_publish_reviewed_preview_is_collision_safe_and_stale_preview_is_rejected(self):
        self.open()
        valid_mp3 = self.root / "valid.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.8", str(valid_mp3),
        ], check=True)

        def render(_audio, _candidate, _options, output):
            shutil.copyfile(valid_mp3, output)

        with patch("jipandan.web.preview.render_export_preview", side_effect=render):
            response = self.client.post("/api/previews", json={
                "clip_id": "1", "expected_revision": 1, "mode": "as_is", "title": "First",
            }, headers=self.headers)
            job_id = response.json()["id"]
            self.wait_for_job(f"/api/previews/{job_id}", "completed")
            first = self.client.post("/api/exports", json={
                "preview_id": job_id, "expected_revision": 1,
            }, headers=self.headers)
            self.assertEqual(first.status_code, 200, first.text)
            first_path = Path(first.json()["output_path"])
            self.assertTrue(first_path.is_file())
            self.assertEqual(first.json()["candidates"][0]["status"], "exported")
            original_bytes = first_path.read_bytes()
            second = self.client.post("/api/exports", json={
                "preview_id": job_id, "expected_revision": 2,
            }, headers=self.headers)
            self.assertEqual(second.status_code, 200, second.text)
            second_path = Path(second.json()["output_path"])
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), original_bytes)
            self.assertTrue(second_path.is_file())
            trimmed = self.client.patch("/api/clips/1", json={
                "expected_revision": 3, "start_ms": 1100,
            }, headers=self.headers)
            self.assertEqual(trimmed.status_code, 200)
            stale = self.client.post("/api/exports", json={
                "preview_id": job_id, "expected_revision": 4,
            }, headers=self.headers)
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(len(list((self.root / "clips").glob("*.mp3"))), 2)

    def test_reveal_export_activates_finder_and_reports_launch_failure(self):
        self.open()
        output = self.root / "clips" / "First export.mp3"
        output.parent.mkdir()
        output.write_bytes(b"mp3")
        self.service.session.get_candidate("1").last_export_path = str(output)
        with patch("jipandan.web.service.sys.platform", "darwin"), \
             patch("jipandan.web.service.subprocess.run") as launch:
            revealed = self.client.post("/api/clips/1/reveal-export", headers=self.headers)
            self.assertEqual(revealed.status_code, 200, revealed.text)
            self.assertEqual(launch.call_args_list[0].args[0], ["open", "-R", str(output.resolve())])
            self.assertEqual(launch.call_args_list[1].args[0], [
                "open", "-a", "/System/Library/CoreServices/Finder.app",
            ])
            launch.side_effect = [None, subprocess.CalledProcessError(1, ["open", "-a"])]
            unavailable = self.client.post("/api/clips/1/reveal-export", headers=self.headers)
            self.assertEqual(unavailable.status_code, 503)
            self.assertIn("Could not open Finder", unavailable.json()["detail"])

    def test_transcription_failure_retry_and_srt_publication(self):
        self.srt.unlink()
        state = self.open()
        self.assertTrue(state["needs_transcription"])
        settings = {"audio": str(self.audio.resolve()), "model_name": "large-v3",
                    "language": None, "temperature": 0, "max_context": 0,
                    "entropy_thold": 3}

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", return_value=1):
            started = self.client.post("/api/transcriptions", json=settings, headers=self.headers)
            self.assertEqual(started.status_code, 200, started.text)
            failed = self.wait_for_job(f"/api/transcriptions/{started.json()['id']}", "failed")
            self.assertIn("status 1", failed["error"])
            self.assertFalse(self.srt.exists())

        def succeed(_manager, job):
            job.output.write_text(SRT, encoding="utf-8")
            return 0

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", succeed):
            retried = self.client.post(
                f"/api/transcriptions/{started.json()['id']}/retry", headers=self.headers,
            )
            self.assertEqual(retried.status_code, 200, retried.text)
            completed = self.wait_for_job(f"/api/transcriptions/{retried.json()['id']}", "completed")
            self.assertEqual(completed["entry_count"], 2)
            self.assertEqual(self.srt.read_text(encoding="utf-8"), SRT)
            self.assertEqual(len(self.client.get("/api/session").json()["candidates"]), 2)
            self.assertEqual(self.client.post(
                "/api/transcriptions", json=settings, headers=self.headers,
            ).status_code, 409)

    def test_export_save_failure_removes_new_file_and_keeps_session_unexported(self):
        self.open()

        def render(_audio, _candidate, _options, output):
            output.write_bytes(b"preview")

        def publish(_source, _audio, _candidate, clip_dir, _title):
            clip_dir.mkdir(parents=True, exist_ok=True)
            output = clip_dir / "new.mp3"
            output.write_bytes(b"exported")
            return output

        with patch("jipandan.web.preview.render_export_preview", side_effect=render), \
             patch("jipandan.web.preview.probe_duration_seconds", return_value=0.8), \
             patch("jipandan.web.service.publish_prebuilt_clip", side_effect=publish):
            response = self.client.post("/api/previews", json={
                "clip_id": "1", "expected_revision": 1, "mode": "as_is", "title": "First",
            }, headers=self.headers)
            job_id = response.json()["id"]
            self.wait_for_job(f"/api/previews/{job_id}", "completed")
            with patch("jipandan.web.service.Session.save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    self.service.publish_export(job_id, 1)
            self.assertFalse((self.root / "clips" / "new.mp3").exists())
            self.assertEqual(self.service.snapshot()["revision"], 1)
            self.assertEqual(self.service.snapshot()["candidates"][0]["status"], "pending")

    def test_interrupted_transcription_recovers_as_failed(self):
        self.srt.unlink()
        self.open()
        job_dir = self.root / "transcriptions" / "interrupted"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({
            "id": "interrupted", "audio": str(self.audio.resolve()), "settings": {},
            "state": "running", "phase": "Transcribing", "created_at": 1,
        }), encoding="utf-8")
        recovered = SessionService(
            self.root / "clips", self.root / "uploads",
            self.root / "other-previews", self.root / "transcriptions",
        )
        try:
            self.assertEqual(recovered.open_audio(self.audio)["transcription"]["state"], "failed")
            self.assertIn("server stopped", recovered.snapshot()["transcription"]["error"])
        finally:
            recovered.close()

    def test_cancelled_transcription_does_not_publish_srt(self):
        self.srt.unlink()
        state = self.open()
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocked(_manager, job):
            entered.set()
            release.wait(2)
            job.output.write_text(SRT, encoding="utf-8")
            finished.set()
            return 0

        settings = {"audio": state["audio"], "model_name": "large-v3"}
        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", blocked):
            started = self.client.post("/api/transcriptions", json=settings, headers=self.headers)
            self.assertEqual(started.status_code, 200, started.text)
            self.assertTrue(entered.wait(1))
            cancelled = self.client.post(
                f"/api/transcriptions/{started.json()['id']}/cancel", headers=self.headers,
            )
            self.assertEqual(cancelled.json()["state"], "cancelled")
            release.set()
            self.assertTrue(finished.wait(1))
            self.assertFalse(self.srt.exists())


if __name__ == "__main__":
    unittest.main()
