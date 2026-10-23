import tempfile
import os
import json
import subprocess
import shutil
import sqlite3
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from jipandan.core.candidates import candidates_srt_path
from jipandan.core.review_rounds import set_order_key
from jipandan.core.clip_features import ClipFeatures
from jipandan.core.models import Session
from jipandan.core.snap_points import SPEECH_END, WORD_START, write_snap_points
from jipandan.core.waveform_envelope import WaveformEnvelopeCache
from jipandan.core.whisper import write_segment_scores
from jipandan.web.api import create_app
from jipandan.core.store import RecordingStore, store_path
from jipandan.core.ffmpeg import ExportOptions
from jipandan.core.paths import AppPaths
from jipandan.web.preview import PreviewJobs
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
        # Logs, uploads and caches stay in the test's folder, not the real application directories.
        self.paths = AppPaths(self.root / "app-data", self.root / "app-cache", self.root / "app-logs")
        self.service = SessionService(
            self.root / "clips", self.root / "uploads",
            self.root / "previews", self.root / "transcriptions", app_paths=self.paths,
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

    def stored(self):
        """The recording as saved on disk, read through a separate connection."""
        store = RecordingStore(store_path(self.audio))
        try:
            return store.load()
        finally:
            store.close()

    def events(self, *kinds):
        store = RecordingStore(store_path(self.audio))
        try:
            return store.events(kinds=kinds or None)
        finally:
            store.close()

    def open(self):
        result = self.client.post(
            "/api/session/open", json={"path": str(self.audio)}, headers=self.headers
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_open_edit_undo_and_reload(self):
        state = self.open()
        self.assertEqual(state["revision"], 1)
        self.assertNotIn("unsure", state["counts"])
        marked = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "group1"},
            headers=self.headers,
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.json()["candidates"][0]["status"], "group1")
        # Decisions apply to the current state even when the client's revision is behind.
        behind = self.client.patch(
            "/api/clips/2", json={"expected_revision": 1, "status": "group2"},
            headers=self.headers,
        )
        self.assertEqual(behind.status_code, 200)
        self.assertEqual(behind.json()["revision"], 3)
        trim = self.client.patch(
            "/api/clips/1", json={"expected_revision": 3, "start_ms": 1100, "end_ms": 1900},
            headers=self.headers,
        )
        self.assertEqual(trim.status_code, 200)
        self.assertEqual(trim.json()["candidates"][0]["start_ms"], 1100)
        undone = self.client.post(
            "/api/session/undo", json={"expected_revision": 4}, headers=self.headers
        )
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(undone.json()["candidates"][0]["start_ms"], 1000)
        self.assertEqual(undone.json()["candidates"][0]["status"], "group1")
        # Undo history survives a restart of the server.
        reopened = SessionService(self.root / "clips", app_paths=self.paths)
        try:
            state = reopened.open_audio(self.audio)
            self.assertEqual([c["status"] for c in state["candidates"]], ["group1", "group2"])
            self.assertTrue(state["can_undo"])
            self.assertEqual(reopened.undo(0)["candidates"][1]["status"], "pending")
        finally:
            reopened.close()

    def test_storage_setting_changes_future_exports_without_moving_existing_files(self):
        self.open()
        old_output = self.root / "clips" / "existing.mp3"
        old_output.parent.mkdir(parents=True, exist_ok=True)
        old_output.write_bytes(b"existing export")
        self.service._mutate(lambda draft: setattr(draft.get_candidate("1"), "last_export_path", str(old_output)))

        new_dir = self.root / "new exports"
        changed = self.client.patch(
            "/api/session/storage",
            json={
                "expected_revision": self.service.session.revision,
                "clip_dir": str(new_dir),
            },
            headers=self.headers,
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["clip_dir"], str(new_dir.resolve()))
        self.assertTrue(old_output.is_file())
        self.assertTrue(new_dir.is_dir())

        persisted = self.stored()
        self.assertEqual(persisted.clip_dir, new_dir.resolve())
        self.assertIn((self.root / "clips").resolve(), persisted.export_dirs)
        self.assertIn(new_dir.resolve(), persisted.export_dirs)

        with patch("jipandan.web.service.sys.platform", "linux"), \
             patch("jipandan.web.service.subprocess.Popen") as launch:
            revealed = self.client.post(
                "/api/clips/1/reveal-export", headers=self.headers,
            )
        self.assertEqual(revealed.status_code, 200, revealed.text)
        launch.assert_called_once_with(["xdg-open", str(old_output.parent.resolve())])

    def test_leading_silence_checks_an_open_round_first_in_its_order(self):
        self.srt.write_text("".join(
            f"{n}\n00:00:0{n},000 --> 00:00:0{n},500\nLine {n}\n\n" for n in range(1, 7)), encoding="utf-8")
        self.open()
        self.service._rounds = [{"number": 1, "size": 2, "random_share": 0.5, "seed": "a1b2c3d4",
                                 "roles": {"2": "top", "5": "random"}, "completed": None}]
        checked = []

        def detect(_audio, start, _end):
            checked.append(start // 1000)
            return None

        path = "/api/session/leading-silence-detection"
        with patch("jipandan.web.service.detect_leading_silence_start", side_effect=detect):
            self.client.post(path, headers=self.headers)
            self.wait_for_job(path, "completed")
        in_set = sorted([2, 5], key=lambda index: set_order_key("a1b2c3d4", index))
        self.assertEqual(checked, [*in_set, 1, 3, 4, 6])

    def test_export_succeeds_after_detection_saves_other_clips(self):
        state = self.open()
        valid_mp3 = self.root / "valid.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.8", str(valid_mp3),
        ], check=True)

        def render(_audio, _candidate, _options, output):
            shutil.copyfile(valid_mp3, output)

        with patch("jipandan.web.preview.render_export_preview", side_effect=render):
            job_id = self.client.post("/api/previews", json={
                "clip_id": "1", "expected_revision": state["revision"], "mode": "as_is", "title": "First",
            }, headers=self.headers).json()["id"]
            self.wait_for_job(f"/api/previews/{job_id}", "completed")
            path = "/api/session/leading-silence-detection"
            with patch("jipandan.web.service.detect_leading_silence_start",
                       side_effect=lambda _audio, start, _end: None if start == 1000 else start + 400):
                self.client.post(path, headers=self.headers)
                self.wait_for_job(path, "completed")
            self.assertGreater(self.service.snapshot()["revision"], state["revision"])
            self.assertFalse(self.client.get(f"/api/previews/{job_id}").json()["stale"])
            exported = self.client.post("/api/exports", json={
                "preview_id": job_id, "expected_revision": state["revision"],
            }, headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.json()["candidates"][0]["status"], "exported")

    def test_storage_rejects_a_file_as_export_directory(self):
        self.open()
        before = self.service.session.clip_dir
        existing_file = self.root / "existing.mp3"
        existing_file.write_bytes(b"not a directory")
        rejected = self.client.patch(
            "/api/session/storage",
            json={"expected_revision": self.service.session.revision, "clip_dir": str(existing_file)},
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(self.stored().clip_dir, before)

    def test_storage_default_and_native_picker(self):
        self.open()
        default = self.client.get("/api/session/storage/default")
        self.assertEqual(default.status_code, 200, default.text)
        self.assertEqual(default.json()["clip_dir"], str((self.root / "exports").resolve()))

        selected = self.root / "picked exports"
        selected.mkdir()
        with patch("jipandan.web.service.sys.platform", "darwin"), patch(
            "jipandan.web.service.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["osascript"], 0, stdout=f"{selected}/\n", stderr="",
            ),
        ) as picker:
            picked = self.client.post("/api/session/storage/pick", headers=self.headers)
        self.assertEqual(picked.status_code, 200, picked.text)
        self.assertEqual(picked.json(), {"path": str(selected.resolve()), "cancelled": False})
        picker.assert_called_once()

        with patch("jipandan.web.service.sys.platform", "darwin"), patch(
            "jipandan.web.service.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["osascript"], 1, stdout="", stderr="execution error: User canceled. (-128)\n",
            ),
        ):
            cancelled = self.client.post("/api/session/storage/pick", headers=self.headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json(), {"path": None, "cancelled": True})

    def test_leading_silence_run_persists_completion_and_is_not_undoable(self):
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
        self.assertTrue(self.stored().leading_silence_detection_complete)
        # A background run is never an Undo step.
        self.assertFalse(state["can_undo"])
        undone = self.client.post("/api/session/undo", json={
            "expected_revision": state["revision"],
        }, headers=self.headers)
        self.assertEqual(undone.status_code, 422, undone.text)
        with patch("jipandan.web.service.detect_leading_silence_start") as detect:
            self.assertEqual(self.client.post(path, headers=self.headers).json()["state"], "completed")
            detect.assert_not_called()

    def test_clip_transcription_suggests_titles_without_bumping_revision(self):
        state = self.open()
        calls = []

        def fake_transcribe(audio, settings, clips, log, register):
            calls.append((audio, settings, clips))
            yield "1", "Better first"
            yield "2", "Second"

        path = "/api/session/clip-transcription"
        with patch("jipandan.web.service.transcribe_clips", side_effect=fake_transcribe):
            response = self.client.post(path, json={"clip_ids": ["1", "2"]}, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            job = self.wait_for_job(path, "completed")
        self.assertEqual(job["progress"], 2)
        clips = calls[0][2]
        self.assertEqual([clip["clip_id"] for clip in clips], ["1", "2"])
        self.assertEqual((clips[0]["start_ms"], clips[0]["end_ms"], clips[0]["prompt"]), (1000, 2000, None))
        self.assertEqual(clips[1]["prompt"], "First")
        self.assertEqual(calls[0][1]["model_name"], "large-v3")

        session = self.client.get("/api/session").json()
        self.assertEqual(session["revision"], state["revision"])
        # A result identical to the current title is not a suggestion.
        self.assertEqual([clip["suggested_title"] for clip in session["candidates"]], ["Better first", None])

        # Suggestions survive reopening the audio.
        self.assertEqual(self.open()["candidates"][0]["suggested_title"], "Better first")

        accepted = self.client.patch(
            "/api/clips/1", json={"expected_revision": session["revision"], "title": "Better first"},
            headers=self.headers,
        ).json()
        self.assertEqual(accepted["candidates"][0]["title"], "Better first")
        self.assertIsNone(accepted["candidates"][0]["suggested_title"])

    def test_undo_skips_a_background_run_and_keeps_its_trims(self):
        state = self.open()
        rejected = self.client.patch("/api/clips/1", json={
            "expected_revision": state["revision"], "status": "rejected",
        }, headers=self.headers).json()
        path = "/api/session/leading-silence-detection"
        with patch("jipandan.web.service.detect_leading_silence_start",
                   side_effect=lambda _audio, start, _end: start + 400):
            self.client.post(path, headers=self.headers)
            self.wait_for_job(path, "completed")
        trimmed = self.service.snapshot()
        self.assertEqual([clip["start_ms"] for clip in trimmed["candidates"]], [1400, 3400])
        self.assertGreater(trimmed["revision"], rejected["revision"])

        undone = self.client.post("/api/session/undo", json={"expected_revision": trimmed["revision"]},
                                  headers=self.headers).json()
        self.assertEqual([clip["status"] for clip in undone["candidates"]], ["pending", "pending"])
        self.assertEqual([clip["start_ms"] for clip in undone["candidates"]], [1400, 3400])
        self.assertFalse(undone["can_undo"])

    def test_clip_transcription_run_undoes_as_one_step(self):
        state = self.open()
        path = "/api/session/clip-transcription"
        with patch("jipandan.web.service.transcribe_clips", return_value=iter([("1", "Better"), ("2", "Other")])):
            self.client.post(path, json={"clip_ids": ["1", "2"]}, headers=self.headers)
            self.wait_for_job(path, "completed")
        session = self.client.get("/api/session").json()
        self.assertTrue(session["can_undo"])
        self.assertEqual(session["revision"], state["revision"])
        # A suggestion accepted since is a title edit of its own and stays.
        accepted = self.client.patch("/api/clips/2", json={
            "expected_revision": session["revision"], "title": "Other",
        }, headers=self.headers).json()
        undone_title = self.client.post("/api/session/undo", json={"expected_revision": accepted["revision"]},
                                        headers=self.headers).json()
        self.assertEqual(undone_title["candidates"][1]["title"], "Second")
        undone = self.client.post("/api/session/undo", json={"expected_revision": undone_title["revision"]},
                                  headers=self.headers).json()
        self.assertEqual([clip["suggested_title"] for clip in undone["candidates"]], [None, None])
        self.assertEqual([clip["title"] for clip in undone["candidates"]], ["First", "Second"])
        self.assertFalse(undone["can_undo"])
        self.assertEqual(self.open()["candidates"][0]["suggested_title"], None)

    def test_clip_transcription_suggestion_can_be_dismissed(self):
        self.open()
        path = "/api/session/clip-transcription"
        with patch("jipandan.web.service.transcribe_clips", return_value=iter([("2", "Other")])):
            self.client.post(path, json={"clip_ids": ["2"]}, headers=self.headers)
            self.wait_for_job(path, "completed")
        dismissed = self.client.delete("/api/clips/2/suggested-title", headers=self.headers).json()
        self.assertIsNone(dismissed["candidates"][1]["suggested_title"])
        self.assertEqual(dismissed["candidates"][1]["title"], "Second")
        missing = self.client.post(path, json={"clip_ids": ["99"]}, headers=self.headers)
        self.assertEqual(missing.status_code, 422)

    def test_clip_transcription_failure_is_reported(self):
        self.open()
        path = "/api/session/clip-transcription"
        with patch("jipandan.web.service.transcribe_clips", side_effect=RuntimeError("no model")):
            self.client.post(path, json={"clip_ids": ["1"]}, headers=self.headers)
            job = self.wait_for_job(path, "failed")
        self.assertEqual(job["error"], "no model")

    def test_delta_responses_carry_only_changed_clips(self):
        self.open()
        marked = self.client.patch("/api/clips/1?delta=true", json={"expected_revision": 1, "status": "group1"},
                                   headers=self.headers).json()
        self.assertTrue(marked["delta"])
        self.assertEqual([(c["clip_id"], c["status"]) for c in marked["clips"]], [("1", "group1")])
        self.assertEqual((marked["removed"], marked["counts"]["group1"], marked["can_undo"]), ([], 1, True))
        duplicated = self.client.post("/api/clips/2/duplicate?delta=true", json={"expected_revision": 2},
                                      headers=self.headers).json()
        self.assertEqual((duplicated["created_clip_id"], [c["clip_id"] for c in duplicated["clips"]]), ("2-2", ["2-2"]))
        undone = self.client.post("/api/session/undo?delta=true", json={"expected_revision": 3},
                                  headers=self.headers).json()
        self.assertEqual((undone["clips"], undone["removed"]), ([], ["2-2"]))
        self.assertNotIn("candidates", undone)

    def test_older_session_files_are_refused_with_a_fresh_start_hint(self):
        legacy = self.audio.with_suffix(".jipandan.json")
        legacy.write_text(json.dumps({"version": 2, "candidates": []}), encoding="utf-8")
        refused = self.client.post("/api/session/open", json={"path": str(self.audio)}, headers=self.headers)
        self.assertEqual(refused.status_code, 422)
        self.assertIn("start a fresh session", refused.json()["detail"])
        self.assertFalse(store_path(self.audio).exists())
        legacy.unlink()
        self.assertEqual(self.open()["counts"]["pending"], 2)
        old_name = self.client.patch("/api/clips/1", json={"expected_revision": 1, "status": "skipped"},
                                     headers=self.headers)
        self.assertEqual(old_name.status_code, 422)

    def review_log(self):
        return [e for e in self.events() if e["type"] != "import"]

    def test_review_log_records_decisions_with_ranking_context(self):
        state = self.open()
        context = {"source": "keyboard", "order": "likely-desc", "filter": "unsorted", "rank": 3,
                   "score": 87.25, "explore": True, "score_version": "builtin-v1", "junk": "x" * 500}
        revision = state["revision"]
        for change in ({"status": "group1"}, {"title": "Better"}, {"start_ms": 1100}):
            response = self.client.patch("/api/clips/1", json={
                "expected_revision": revision, **change, "context": context,
            }, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            revision = response.json()["revision"]
        # An unchanged status is not a decision, so it is not logged.
        revision = self.client.patch("/api/clips/1", json={"expected_revision": revision, "status": "group1"},
                                     headers=self.headers).json()["revision"]
        revision = self.client.post("/api/clips/bulk-reject", json={
            "expected_revision": revision, "clip_ids": ["2"], "context": {"source": "pointer"},
        }, headers=self.headers).json()["revision"]
        self.client.post("/api/session/undo", json={"expected_revision": revision, "context": {"source": "gamepad"}},
                         headers=self.headers)

        events = self.review_log()
        self.assertEqual([e["type"] for e in events], ["status", "title", "trim", "bulk-reject", "undo"])
        self.assertTrue(all(e["t"].endswith("Z") for e in events))
        status = events[0]
        self.assertEqual((status["clip"], status["from"], status["to"]), ("1", "pending", "group1"))
        self.assertEqual({k: status[k] for k in ("source", "order", "filter", "rank", "score", "explore", "score_version")},
                         {"source": "keyboard", "order": "likely-desc", "filter": "unsorted", "rank": 3,
                          "score": 87.2, "explore": True, "score_version": "builtin-v1"})
        self.assertNotIn("junk", status)
        self.assertEqual((events[1]["from"], events[1]["to"]), ("First", "Better"))
        self.assertEqual((events[2]["from_ms"], events[2]["to_ms"]), ([1000, 2000], [1100, 2000]))
        self.assertEqual((events[3]["clips"], events[3]["source"]), (["2"], "pointer"))
        self.assertEqual((events[4]["restored"], events[4]["source"]), ({"2": "pending"}, "gamepad"))

    def test_review_log_accepts_only_valid_client_views(self):
        self.open()
        audio = str(self.audio.resolve())
        response = self.client.post("/api/review-log", json={"events": [
            {"type": "view", "audio": audio, "clip": "1", "dwell_ms": 2400, "plays": 2, "autoplay": True,
             "started_at": int(time.time() * 1000) - 5000, "ended_by": "idle",
             "context": {"source": "gamepad", "rank": 1, "score": 50}},
            {"type": "view", "audio": audio, "clip": "2", "dwell_ms": -5, "ended_by": "lunch"},
            {"type": "status", "audio": audio, "clip": "2", "dwell_ms": 100},
            {"type": "view", "audio": audio, "dwell_ms": 100},
            # A view of a previously open recording must not land in this one's log.
            {"type": "view", "audio": "/elsewhere/other.mp3", "clip": "1", "dwell_ms": 100},
        ]}, headers=self.headers)
        self.assertEqual(response.json(), {"accepted": 2})
        events = self.review_log()
        self.assertEqual([(e["clip"], e["dwell_ms"], e["plays"]) for e in events], [("1", 2400, 2), ("2", 0, 0)])
        self.assertEqual((events[0]["source"], events[0]["rank"], events[0]["score"]), ("gamepad", 1, 50.0))
        self.assertLess(events[0]["start"], events[0]["t"])
        self.assertTrue(events[0]["autoplay"])
        self.assertEqual(events[0]["ended_by"], "idle")
        self.assertNotIn("start", events[1])
        self.assertNotIn("ended_by", events[1])
        too_many = self.client.post("/api/review-log", json={"events": [{}] * 201}, headers=self.headers)
        self.assertEqual(too_many.status_code, 422)

    def test_round_stats_count_views_and_changes_made_during_the_round(self):
        self.open()
        audio = str(self.audio.resolve())
        before = {"type": "view", "audio": audio, "clip": "1", "dwell_ms": 50_000, "context": {"filter": "triage"}}
        self.client.post("/api/review-log", json={"events": [before]}, headers=self.headers)
        self.measure_clip_features()
        state = self.client.post("/api/session/rounds", json={"size": 10, "random_share": 0.2},
                                 headers=self.headers).json()
        self.client.post("/api/review-log", json={"events": [
            {"type": "view", "audio": audio, "clip": "1", "dwell_ms": 3000, "context": {"filter": "triage"}},
            {"type": "view", "audio": audio, "clip": "2", "dwell_ms": 9000, "context": {"filter": "group1"}},
        ]}, headers=self.headers)
        self.client.patch("/api/clips/1", json={"expected_revision": state["revision"], "status": "rejected",
                                                "context": {"filter": "triage"}}, headers=self.headers)
        summary = self.client.get("/api/session/rounds").json()["rounds"][0]
        # The view from before the round started is left out.
        self.assertEqual([(row["stage"], row["ms"], row["clips"], row["changes"]) for row in summary["stages"]],
                         [("triage", 3000, 1, 1), ("polish", 9000, 1, 0), ("publish", 0, 0, 0)])
        self.assertEqual(summary["time_ms"], 12000)
        self.assertEqual(self.client.get("/api/session/stage-times").status_code, 404)

    def test_start_over_backs_up_the_session_and_starts_from_the_chosen_srt(self):
        state = self.open()
        self.assertEqual(state["clip_sources"], ["lines"])
        edited = self.client.patch("/api/clips/1", json={
            "expected_revision": state["revision"], "status": "group1",
        }, headers=self.headers).json()
        candidates_srt_path(self.srt).write_text("1\n00:00:00,800 --> 00:00:02,100\nFirst\n\n", encoding="utf-8")
        self.assertEqual(self.client.get("/api/session").json()["clip_sources"], ["lines", "generated"])

        stale = self.client.post("/api/session/start-over", json={
            "expected_revision": state["revision"], "clip_source": "generated",
        }, headers=self.headers)
        self.assertEqual(stale.status_code, 409)
        response = self.client.post("/api/session/start-over", json={
            "expected_revision": edited["revision"], "clip_source": "generated",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        fresh = response.json()
        self.assertEqual(fresh["srt"], str(candidates_srt_path(self.srt.resolve())))
        self.assertEqual([(c["start"], c["status"]) for c in fresh["candidates"]], [("00:00:00.800", "pending")])
        self.assertFalse(fresh["can_undo"])
        self.assertEqual([e["type"] for e in self.events()], ["import"])

        backup = Path(fresh["start_over_backup"])
        self.assertEqual(backup.parent, self.audio.resolve().parent)
        old = RecordingStore(backup)
        self.addCleanup(old.close)
        self.assertEqual(old.load().get_candidate("1").status, "group1")

        # Reopening keeps the new session and its generated SRT.
        self.assertEqual(self.open()["srt"], fresh["srt"])
        again = self.client.post("/api/session/start-over", json={
            "expected_revision": fresh["revision"], "clip_source": "lines",
        }, headers=self.headers).json()
        self.assertEqual(len(again["candidates"]), 2)

    def test_start_over_needs_a_saved_transcript(self):
        state = self.open()
        response = self.client.post("/api/session/start-over", json={
            "expected_revision": state["revision"], "clip_source": "generated",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/session").json()["revision"], state["revision"])

    def measure_clip_features(self):
        path = "/api/session/clip-features"
        measured = [ClipFeatures(-12.0, -3.0, -25.0), ClipFeatures(-35.0, -9.0, -6.0)]
        with patch("jipandan.web.service.compute_clip_features", return_value=measured):
            self.client.post(path, headers=self.headers)
            self.wait_for_job(path, "completed")

    def test_rounds_are_picked_in_turn_from_clips_no_round_took(self):
        self.srt.write_text("".join(
            f"{n}\n00:00:0{n},000 --> 00:00:0{n},500\nLine {n}\n\n" for n in range(1, 5)), encoding="utf-8")
        self.open()
        start = {"size": 10, "random_share": 0.5}
        self.assertEqual(self.client.post("/api/session/rounds", json=start, headers=self.headers).status_code, 409)
        path = "/api/session/clip-features"
        measured = [ClipFeatures(-12.0, -3.0, -25.0), ClipFeatures(-35.0, -9.0, -6.0),
                    ClipFeatures(-20.0, -5.0, -15.0), ClipFeatures(-30.0, -8.0, -9.0)]
        with patch("jipandan.web.service.compute_clip_features", return_value=measured):
            self.client.post(path, headers=self.headers)
            self.wait_for_job(path, "completed")
        self.assertEqual(self.client.post("/api/session/rounds", json={"size": 9, "random_share": 0.2},
                                          headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/api/session/rounds", json={"size": 10, "random_share": 1.5},
                                          headers=self.headers).status_code, 422)
        plan = self.client.get("/api/session/rounds?size=10&random_share=0.5").json()
        self.assertEqual((plan["pool"], plan["next"]["number"], plan["next"]["size"], plan["next"]["random_count"]),
                         (4, 1, 4, 2))
        self.assertIsNone(plan["stream"])

        state = self.client.post("/api/session/rounds", json={"size": 10, "random_share": 0.5},
                                 headers=self.headers).json()
        self.assertEqual({key: state["review_round"][key] for key in ("number", "size", "random_share", "unprocessed")},
                         {"number": 1, "size": 4, "random_share": 0.5, "unprocessed": 4})
        self.assertEqual(sorted(c["round_role"] for c in state["candidates"]), ["random", "random", "top", "top"])
        event = self.events("review-round")[0]
        self.assertEqual((event["number"], event["pool"], event["score_version"]), (1, 4, "builtin-v1"))
        # Asking again keeps the open round.
        again = self.client.post("/api/session/rounds", json={"size": 50, "random_share": 0.2}, headers=self.headers)
        self.assertEqual(again.json()["review_round"]["size"], 4)

        revision = state["revision"]
        for clip_id in ("1", "2"):
            revision = self.client.patch(f"/api/clips/{clip_id}", json={
                "expected_revision": revision, "status": "rejected",
                "context": {"review_set": "top", "round": 1, "filter": "triage"},
            }, headers=self.headers).json()["revision"]
        self.assertEqual((self.events("status")[0]["review_set"], self.events("status")[0]["round"]), ("top", 1))
        self.assertEqual(self.open()["review_round"]["unprocessed"], 2)

        completed = self.client.post("/api/session/rounds/complete", headers=self.headers).json()
        self.assertIsNone(completed["review_round"])
        self.assertEqual(completed["rounds_done"], 1)
        self.assertEqual([c["round_role"] for c in completed["candidates"]], [None] * 4)
        self.assertEqual(self.events("review-round-complete")[0]["unprocessed"], 2)
        self.assertEqual(self.client.post("/api/session/rounds/complete", headers=self.headers).status_code, 422)
        summary = self.client.get("/api/session/rounds").json()["rounds"][0]
        self.assertEqual((summary["number"], summary["processed"], summary["kept"]), (1, 2, 0))
        self.assertIsNone(self.open()["review_round"])
        # Round 1 ended with two clips left Unsorted; round 2 takes them, as no other clip is left.
        self.assertEqual(self.client.get("/api/session/rounds").json()["pool"], 2)
        second = self.client.post("/api/session/rounds", json=start, headers=self.headers).json()
        self.assertEqual((second["review_round"]["number"], second["review_round"]["size"]), (2, 2))
        self.assertEqual(sorted(c["clip_id"] for c in second["candidates"] if c["round_role"]), ["3", "4"])
        self.assertEqual(revision, self.client.get("/api/session").json()["revision"])

    def test_a_review_set_from_before_rounds_opens_as_round_one(self):
        self.open()
        legacy = {"size": 2, "total": 2, "random_share": 0.2, "seed": "a1b2c3d4", "score_version": "builtin-v1",
                  "top": ["1", "2"], "random": [], "roles": {"1": "top", "2": "top"}, "completed": None}
        db = sqlite3.connect(self.service.store.path)
        with db:
            db.execute("INSERT INTO meta (key, value) VALUES ('review_set', ?)", (json.dumps(legacy),))
        db.close()
        state = self.open()
        self.assertEqual((state["review_round"]["number"], state["review_round"]["unprocessed"]), (1, 2))
        self.assertEqual([c["round_role"] for c in state["candidates"]], ["top", "top"])

    def test_clip_features_score_clips_and_persist_without_undo(self):
        self.open()
        path = "/api/session/clip-features"
        measured = [ClipFeatures(-12.0, -3.0, -25.0), ClipFeatures(-35.0, -9.0, -6.0)]
        with patch("jipandan.web.service.compute_clip_features", return_value=measured) as compute:
            response = self.client.post(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            job = self.wait_for_job(path, "completed")
        self.assertEqual(job["total"], 2)
        self.assertEqual(compute.call_args.args[1], [(1.0, 2.0), (3.0, 4.0)])
        state = self.client.get("/api/session").json()
        self.assertTrue(state["clip_features_complete"])
        self.assertFalse(state["can_undo"])
        self.assertEqual([clip["likely_keep"] for clip in state["candidates"]], [100.0, 0.0])
        persisted = self.stored()
        self.assertEqual(persisted.candidates[1].peak_db, -35.0)
        self.assertEqual(persisted.clip_features_version, 1)
        # Measurements are not review decisions, so they leave no event behind.
        self.assertEqual([e["type"] for e in self.events()], ["import"])
        with patch("jipandan.web.service.compute_clip_features") as compute:
            self.assertEqual(self.client.post(path, headers=self.headers).json()["state"], "completed")
            compute.assert_not_called()

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

    def test_decisions_apply_while_background_jobs_save(self):
        self.open()
        entered, release = threading.Event(), threading.Event()

        def detect(_audio, start, _end):
            if start == 3000:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release detector")
            return start + 400

        path = "/api/session/leading-silence-detection"
        with patch("jipandan.web.service.LEADING_SILENCE_BATCH_SIZE", 1), patch(
            "jipandan.web.service.detect_leading_silence_start", side_effect=detect,
        ):
            self.client.post(path, headers=self.headers)
            try:
                self.assertTrue(entered.wait(5))
                # Clip 1 was re-trimmed by a background save after revision 1 was read.
                self.assertEqual(self.service.snapshot()["revision"], 2)
                status = self.client.patch("/api/clips/2", json={"expected_revision": 1, "status": "rejected"},
                                           headers=self.headers)
                self.assertEqual(status.status_code, 200, status.text)
                # The user's trim of a clip the background job just changed still wins.
                trim = self.client.patch("/api/clips/1", json={"expected_revision": 1, "start_ms": 1200},
                                         headers=self.headers)
                self.assertEqual(trim.status_code, 200, trim.text)
            finally:
                release.set()
            self.wait_for_job(path, "completed")
        state = self.service.snapshot()
        self.assertEqual([c["status"] for c in state["candidates"]], ["pending", "rejected"])
        self.assertEqual(state["candidates"][0]["start_ms"], 1200)

    def test_preview_title_change_reuses_render_and_waveform(self):
        self.open()
        envelope = WaveformEnvelopeCache(
            times=np.array([0.4]), mins=np.array([-0.25]), maxs=np.array([0.5]),
            duration=0.8, buckets=1,
        )

        def render(_audio, _candidate, _options, output):
            output.write_bytes(b"rendered audio")
            return {"source_duration_ms": 1000, "duration_ms": 800, "kept_ranges_ms": [[100, 900]]}

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
            self.assertEqual(renamed.json()["trim_map"], completed["trim_map"])
            self.assertEqual(completed["trim_map"]["kept_ranges_ms"], [[100, 900]])
            restarted = PreviewJobs(self.root / "previews")
            self.addCleanup(restarted._executor.shutdown)
            cached = restarted.start(self.audio, self.service.session.candidates[0], 1, ExportOptions("as_is"), "First")
            self.assertEqual(cached.state, "completed")
            self.assertEqual(cached.trim_map, completed["trim_map"])
            renderer.assert_called_once()

    def test_bulk_reject_and_invalid_bounds(self):
        self.open()
        bad = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "start_ms": 2000, "end_ms": 2000},
            headers=self.headers,
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.service.snapshot()["revision"], 1)
        rejected = self.client.post(
            "/api/clips/bulk-reject",
            json={"expected_revision": 1, "clip_ids": ["1", "2"]}, headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["changed_clip_ids"], ["1", "2"])
        self.assertEqual(rejected.json()["counts"]["rejected"], 2)
        unsure = self.client.patch("/api/clips/1", json={"expected_revision": 2, "status": "unsure"},
                                   headers=self.headers)
        self.assertEqual(unsure.status_code, 422)
        self.assertEqual(self.service.snapshot()["revision"], 2)
        undone = self.client.post("/api/session/undo", json={"expected_revision": 2}, headers=self.headers)
        self.assertEqual(undone.json()["counts"]["pending"], 2)
        self.assertNotIn("unsure", undone.json()["counts"])

    def test_open_resets_legacy_unsure_clips_to_unsorted(self):
        legacy_store = RecordingStore(store_path(self.audio))
        legacy_store.create(Session.from_srt(self.audio, self.srt, self.root / "clips"))
        (data,) = legacy_store._db.execute("SELECT data FROM clip WHERE clip_id = ?", ("1",)).fetchone()
        legacy = json.loads(data)
        legacy["status"] = "unsure"
        legacy_store._db.execute("UPDATE clip SET data = ? WHERE clip_id = ?", (json.dumps(legacy), "1"))
        legacy_store.close()

        opened = self.open()

        self.assertEqual(opened["revision"], 2)
        self.assertEqual(opened["candidates"][0]["status"], "pending")
        self.assertNotIn("unsure", opened["counts"])
        self.assertEqual(self.stored().get_candidate("1").status, "pending")

    def test_millisecond_trim_survives_reload_and_rejects_invalid_duration(self):
        self.open()
        trimmed = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "start_ms": 1101, "end_ms": 1907},
            headers=self.headers,
        )
        self.assertEqual(trimmed.status_code, 200)
        self.assertEqual(trimmed.json()["candidates"][0]["start_ms"], 1101)
        self.assertEqual(trimmed.json()["candidates"][0]["end_ms"], 1907)
        reopened = SessionService(self.root / "clips", app_paths=self.paths)
        self.assertEqual(reopened.open_audio(self.audio)["candidates"][0]["end_ms"], 1907)
        reopened.close()
        invalid = self.client.patch(
            "/api/clips/1", json={"expected_revision": 2, "start_ms": 1900, "end_ms": 1909},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.service.snapshot()["revision"], 2)

    def test_sessions_without_snap_points_return_none(self):
        self.assertEqual(self.client.get("/api/session/snap-points").status_code, 409)
        self.open()
        self.assertEqual(self.client.get("/api/session/snap-points").json(), {WORD_START: [], SPEECH_END: []})

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
        # Removing entries is undoable instead of relying on a backup copy.
        restored = self.client.post("/api/session/undo", json={"expected_revision": 0}, headers=self.headers)
        self.assertEqual(len(restored.json()["candidates"]), 2)

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
        second_service = SessionService(self.root / "clips", app_paths=self.paths)
        second_service.open_audio(self.audio)
        second_client = TestClient(create_app(second_service, allowed_hosts={"testserver"}))
        second_token = second_client.get("/api/bootstrap").json()["token"]
        first = self.client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "group1"},
            headers=self.headers,
        )
        self.assertEqual(first.status_code, 200)
        stale = second_client.patch(
            "/api/clips/1", json={"expected_revision": 1, "status": "rejected"},
            headers={"x-jipandan-token": second_token},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["session"]["candidates"][0]["status"], "group1")
        second_client.close()
        second_service.close()

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

    def test_real_waveforms_and_all_export_modes_survive_reload(self):
        self.probe.stop()
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=5", str(self.audio),
        ], check=True)
        state = self.open()
        waveform = self.client.get(
            "/api/waveforms/1", params={"start_ms": 1000, "end_ms": 2000, "buckets": 128},
        )
        self.assertEqual(waveform.status_code, 200, waveform.text)
        self.assertGreater(max(waveform.json()["maxs"]), 0)

        for mode in ("as_is", "trim_edges", "trim_all"):
            with self.subTest(mode=mode):
                response = self.client.post("/api/previews", json={
                    "clip_id": "1", "expected_revision": state["revision"],
                    "mode": mode, "title": "First",
                }, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                job_id = response.json()["id"]
                preview = self.wait_for_job(f"/api/previews/{job_id}", "completed")
                self.assertGreater(preview["duration_ms"], 0)
                self.assertIsNotNone(preview["waveform"])
                self.assertGreater(max(preview["waveform"]["maxs"]), 0)
                published = self.client.post("/api/exports", json={
                    "preview_id": job_id, "expected_revision": state["revision"],
                }, headers=self.headers)
                self.assertEqual(published.status_code, 200, published.text)
                state = published.json()
                self.assertGreater(Path(state["output_path"]).stat().st_size, 0)

        self.assertEqual(len(list((self.root / "clips").glob("*.mp3"))), 3)
        reopened = self.open()
        self.assertEqual(reopened["candidates"][0]["status"], "exported")
        self.assertEqual(reopened["candidates"][0]["last_export_path"], state["output_path"])
        self.assertEqual(reopened["candidates"][0]["export_state"], "matching")
        previous_path = reopened["candidates"][0]["last_export_path"]
        renamed = self.client.patch("/api/clips/1?delta=true", json={
            "expected_revision": reopened["revision"], "title": "Changed title",
        }, headers=self.headers).json()
        self.assertEqual(renamed["clips"][0]["export_state"], "changed")
        self.assertEqual(renamed["clips"][0]["last_export_title"], "First")
        self.assertEqual(renamed["clips"][0]["last_export_path"], previous_path)
        undone = self.client.post("/api/session/undo", json={"expected_revision": renamed["revision"]}, headers=self.headers).json()
        self.assertEqual(undone["candidates"][0]["export_state"], "matching")
        edited = self.client.patch("/api/clips/1", json={
            "expected_revision": undone["revision"], "start_ms": 1010,
        }, headers=self.headers).json()
        self.assertEqual(edited["candidates"][0]["export_state"], "changed")
        reloaded = self.open()
        self.assertEqual(reloaded["candidates"][0]["export_state"], "changed")
        fresh = self.client.post("/api/previews", json={
            "clip_id": "1", "expected_revision": reloaded["revision"], "mode": "trim_edges", "title": "First",
        }, headers=self.headers).json()
        self.wait_for_job(f"/api/previews/{fresh['id']}", "completed")
        exported = self.client.post("/api/exports", json={
            "preview_id": fresh["id"], "expected_revision": reloaded["revision"],
        }, headers=self.headers).json()
        self.assertEqual(exported["candidates"][0]["export_state"], "matching")
        self.assertEqual(exported["candidates"][0]["last_export_snapshot"]["mode"], "trim_edges")
        self.assertTrue(Path(previous_path).is_file())

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
            # A single export from Publish is not an Undo step; the trim before it is.
            self.assertEqual(self.events("undo"), [])

    def test_export_all_run_undoes_as_one_step_and_keeps_files(self):
        state = self.open()
        for clip_id in ("1", "2"):
            state = self.client.patch(f"/api/clips/{clip_id}", json={
                "expected_revision": state["revision"], "status": "group2",
            }, headers=self.headers).json()
        valid_mp3 = self.root / "valid.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.8", str(valid_mp3),
        ], check=True)

        def render(_audio, _candidate, _options, output):
            shutil.copyfile(valid_mp3, output)

        run = "0f8e2c4a-5b1d-4e7f-9a3c-2d6b8e1f0a47"
        with patch("jipandan.web.preview.render_export_preview", side_effect=render):
            for clip_id, title in (("1", "First"), ("2", "Second")):
                job_id = self.client.post("/api/previews", json={
                    "clip_id": clip_id, "expected_revision": state["revision"], "mode": "as_is", "title": title,
                }, headers=self.headers).json()["id"]
                self.wait_for_job(f"/api/previews/{job_id}", "completed")
                state = self.client.post("/api/exports", json={
                    "preview_id": job_id, "expected_revision": state["revision"], "export_all": run,
                }, headers=self.headers).json()
        self.assertEqual([clip["status"] for clip in state["candidates"]], ["exported", "exported"])
        undone = self.client.post("/api/session/undo", json={"expected_revision": state["revision"]},
                                  headers=self.headers).json()
        self.assertEqual([clip["status"] for clip in undone["candidates"]], ["group2", "group2"])
        self.assertEqual(len(list((self.root / "clips").glob("*.mp3"))), 2)
        self.assertEqual(self.events("undo")[0]["label"], "Export all")
        bad = self.client.post("/api/exports", json={
            "preview_id": "x", "expected_revision": undone["revision"], "export_all": "../x",
        }, headers=self.headers)
        self.assertEqual(bad.status_code, 422)

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
            self.assertTrue(Path(failed["log_file"]).is_relative_to((self.root / "app-logs").resolve()))
            self.assertFalse(self.srt.exists())

        def succeed(_manager, job):
            job.output.write_text(SRT, encoding="utf-8")
            write_segment_scores(job.output, [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.8}])
            write_snap_points(job.output, {WORD_START: [1000, 3000], SPEECH_END: [2100]})
            return 0

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", succeed):
            retried = self.client.post(
                f"/api/transcriptions/{started.json()['id']}/retry", headers=self.headers,
            )
            self.assertEqual(retried.status_code, 200, retried.text)
            completed = self.wait_for_job(f"/api/transcriptions/{retried.json()['id']}", "completed")
            self.assertEqual(completed["entry_count"], 2)
            self.assertEqual(self.srt.read_text(encoding="utf-8"), SRT)
            published = self.client.get("/api/session").json()["candidates"]
            self.assertEqual([clip["no_speech_prob"] for clip in published], [0.1, 0.8])
            self.assertEqual([clip["likely_keep"] for clip in published], [100.0, 0.0])
            store = RecordingStore(store_path(self.audio))
            try:
                self.assertEqual(store.snap_points(WORD_START), [1000, 3000])
                self.assertEqual(store.snap_points(SPEECH_END), [2100])
            finally:
                store.close()
            self.assertEqual(self.client.get("/api/session/snap-points").json(),
                             {WORD_START: [1000, 3000], SPEECH_END: [2100]})
            self.assertEqual(self.client.post(
                "/api/transcriptions", json=settings, headers=self.headers,
            ).status_code, 409)

    def test_removed_transcript_allows_transcribing_again(self):
        self.srt.unlink()
        self.open()
        settings = {"audio": str(self.audio.resolve()), "model_name": "large-v3", "language": None,
                    "temperature": 0, "max_context": 0, "entropy_thold": 3}

        def succeed(_manager, job):
            job.output.write_text(SRT, encoding="utf-8")
            return 0

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", succeed):
            started = self.client.post("/api/transcriptions", json=settings, headers=self.headers)
            self.wait_for_job(f"/api/transcriptions/{started.json()['id']}", "completed")
        self.assertEqual(self.client.get("/api/session").json()["transcription"]["state"], "completed")

        # The owner deletes the SRT and session to start over.
        self.service.store.close()
        self.srt.unlink()
        store_path(self.audio).unlink()
        reopened = self.open()
        self.assertTrue(reopened["needs_transcription"])
        self.assertIsNone(reopened["transcription"])
        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", succeed):
            again = self.client.post("/api/transcriptions", json=settings, headers=self.headers)
            self.assertEqual(again.status_code, 200, again.text)
            self.wait_for_job(f"/api/transcriptions/{again.json()['id']}", "completed")

    def test_generated_clip_source_builds_the_session_from_candidates(self):
        self.srt.unlink()
        self.open()
        settings = {"audio": str(self.audio.resolve()), "model_name": "large-v3", "language": None,
                    "temperature": 0, "max_context": 0, "entropy_thold": 3, "clip_source": "generated"}
        generated = "1\n00:00:00,800 --> 00:00:02,100\nFirst\n\n"

        def without_candidates(_manager, job):
            job.output.write_text(SRT, encoding="utf-8")
            return 0

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", without_candidates):
            started = self.client.post("/api/transcriptions", json=settings, headers=self.headers)
            failed = self.wait_for_job(f"/api/transcriptions/{started.json()['id']}", "failed")
            self.assertIn("voice activity detection failed", failed["error"])
            self.assertFalse(self.srt.exists())

        def succeed(_manager, job):
            job.output.write_text(SRT, encoding="utf-8")
            candidates = candidates_srt_path(job.output)
            candidates.write_text(generated, encoding="utf-8")
            write_segment_scores(candidates, [{"no_speech_prob": 0.3}])
            write_snap_points(candidates, {WORD_START: [1000], SPEECH_END: [2100]})
            return 0

        with patch("jipandan.web.transcription.TranscriptionJobs._run_process", succeed):
            retried = self.client.post(
                f"/api/transcriptions/{started.json()['id']}/retry", headers=self.headers,
            )
            completed = self.wait_for_job(f"/api/transcriptions/{retried.json()['id']}", "completed")
        self.assertEqual(completed["entry_count"], 1)
        candidates = candidates_srt_path(self.srt.resolve())
        self.assertEqual(self.srt.read_text(encoding="utf-8"), SRT)
        self.assertEqual(candidates.read_text(encoding="utf-8"), generated)
        state = self.client.get("/api/session").json()
        self.assertEqual(state["srt"], str(candidates))
        self.assertEqual([(c["start"], c["no_speech_prob"]) for c in state["candidates"]],
                         [("00:00:00.800", 0.3)])
        self.assertEqual(self.client.get("/api/session/snap-points").json(),
                         {WORD_START: [1000], SPEECH_END: [2100]})

        # Reopening follows the generated SRT, so it is not offered as a changed transcript.
        reopened = self.open()
        self.assertEqual(reopened["srt"], str(candidates))
        self.assertFalse(reopened["merge_preview"]["file_changed"])

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
            with patch("jipandan.web.service.RecordingStore.commit", side_effect=OSError("disk full")):
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
            self.root / "other-previews", self.root / "transcriptions", app_paths=self.paths,
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
