import json
import tempfile
import unittest
from pathlib import Path

from jipandan.core.models import Session
from jipandan.core.snap_points import SPEECH_END, WORD_START
from jipandan.core.store import RecordingStore, StoreConflict, store_path


SRT = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"


class RecordingStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.audio = self.root / "audio.mp3"
        self.audio.write_bytes(b"audio")
        self.srt = self.root / "audio.srt"
        self.srt.write_text(SRT, encoding="utf-8")
        self.path = store_path(self.audio)
        self.store = RecordingStore(self.path)
        self.session = Session.from_srt(self.audio, self.srt, self.root / "clips")
        self.store.create(self.session)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_snap_points_are_stored_with_a_new_session(self):
        self.assertEqual(self.store.snap_points(WORD_START), [])
        other = RecordingStore(self.root / "other.jipandan.db")
        try:
            other.create(self.session, {WORD_START: [3000, 1000, 1000], SPEECH_END: [2500]})
            self.assertEqual(other.snap_points(WORD_START), [1000, 3000])
            self.assertEqual(other.snap_points(SPEECH_END), [2500])
        finally:
            other.close()
        reopened = RecordingStore(self.root / "other.jipandan.db")
        try:
            self.assertEqual(reopened.snap_points(SPEECH_END), [2500])
        finally:
            reopened.close()

    def change(self, session, mutate, events, **options):
        import copy
        draft = copy.deepcopy(session)
        mutate(draft)
        before = {c.clip_id: c for c in session.candidates}
        after = {c.clip_id: c for c in draft.candidates}
        changed = {i: before.get(i) for i in before.keys() | after.keys() if before.get(i) != after.get(i)}
        self.store.commit(draft, changed, events, **options)
        return draft

    def test_history_gives_each_change_with_its_clips_right_after_it(self):
        def decide(status):
            def mutate(draft):
                draft.get_candidate("1").status = status
            return mutate

        start = self.store.last_seq()
        session = self.change(self.session, decide("group1"), [{"type": "status", "clip": "1", "to": "group1"}],
                              label="1", undoable=True)
        self.store.append_events([{"type": "view", "clip": "1", "dwell_ms": 900}])
        session = self.change(session, decide("rejected"), [{"type": "status", "clip": "1", "to": "rejected"}],
                              label="1", undoable=True)
        rejected = self.store.last_seq()
        target = self.store.undo_target()
        session = self.change(session, decide("group1"), [{"type": "undo", "targets": target.seqs}], undoes=target.seqs)
        def split(draft):
            draft.duplicate_candidate("1")
        self.change(session, split, [{"type": "duplicate", "clip": "1", "created": "1-2"}])

        changes, events = self.store.history(start, self.store.last_seq())
        self.assertEqual([(c["type"], c["after"]["1"]["status"] if "1" in c["after"] else None) for c in changes],
                         [("status", "group1"), ("status", "rejected"), ("undo", "group1"), ("duplicate", None)])
        self.assertEqual(changes[2]["undoes"], [rejected])
        self.assertEqual(changes[3]["after"]["1-2"]["status"], "group1")
        self.assertEqual([(e["type"], e["clip"], e["dwell_ms"]) for e in events], [("view", "1", 900)])
        # A window that ends early still gives the clips as they were right after each change in it.
        early, _ = self.store.history(start, rejected)
        self.assertEqual([c["after"]["1"]["status"] for c in early], ["group1", "rejected"])
        self.assertEqual(self.store.clips_at(start)["1"]["status"], "pending")
        self.assertIsNone(self.store.clips_at(start)["1-2"])
        self.assertNotIn("2", self.store.clips_at(start))
        self.assertEqual([ids for _, ids in self.store.changed_after(rejected)], [["1"], ["1-2"]])
        self.assertEqual(self.store.seq_at("2000-01-01T00:00:00Z"), 0)
        self.assertEqual(self.store.seq_at("2999-01-01T00:00:00Z"), self.store.last_seq())

    def test_state_and_undo_survive_reopening(self):
        def decide(draft):
            draft.get_candidate("1").status = "group1"
        session = self.change(self.session, decide, [{"type": "status", "clip": "1", "to": "group1"}],
                              label="1", undoable=True)
        self.store.close()

        self.store = RecordingStore(self.path)
        reloaded = self.store.load()
        self.assertEqual((reloaded.revision, reloaded.get_candidate("1").status), (2, "group1"))
        target = self.store.undo_target()
        seqs, label, restored = target.seqs, target.label, target.restored
        self.assertEqual((label, restored["1"].status), ("1", "pending"))

        def restore(draft):
            draft.candidates[0] = restored["1"]
        self.change(reloaded, restore, [{"type": "undo", "targets": seqs}], undoes=seqs)
        self.assertEqual(self.store.load().get_candidate("1").status, "pending")
        self.assertFalse(self.store.can_undo())
        events = self.store.events()
        self.assertEqual([e["type"] for e in events], ["import", "status", "undo"])
        self.assertEqual(events[1]["undone_by"], events[2]["seq"])
        self.assertEqual(events[1]["to"], "group1")
        self.assertEqual(session.revision, 2)

    def test_legacy_unsure_status_is_reset_to_pending_on_load(self):
        (data,) = self.store._db.execute("SELECT data FROM clip WHERE clip_id = ?", ("1",)).fetchone()
        legacy = json.loads(data)
        legacy["status"] = "unsure"
        self.store._db.execute("UPDATE clip SET data = ? WHERE clip_id = ?", (json.dumps(legacy), "1"))

        loaded = self.store.load()

        self.assertEqual((loaded.revision, loaded.get_candidate("1").status), (2, "pending"))
        (stored,) = self.store._db.execute("SELECT data FROM clip WHERE clip_id = ?", ("1",)).fetchone()
        self.assertEqual(json.loads(stored)["status"], "pending")
        self.assertEqual(self.store.load().revision, 2)
        self.assertEqual([event["type"] for event in self.store.events()], ["import", "legacy_status_reset"])
        self.assertFalse(self.store.can_undo())

    def test_undo_of_legacy_unsure_state_restores_pending(self):
        def mark_unsure(draft):
            setattr(draft.get_candidate("1"), "status", "unsure")

        unsure = self.change(
            self.session, mark_unsure, [{"type": "status", "clip": "1", "to": "unsure"}],
            label="1", undoable=True,
        )

        def mark_ready(draft):
            draft.get_candidate("1").status = "group2"

        ready = self.change(
            unsure, mark_ready, [{"type": "status", "clip": "1", "from": "unsure", "to": "group2"}],
            label="1", undoable=True,
        )
        target = self.store.undo_target()
        seqs, _, restored = target.seqs, target.label, target.restored
        self.assertEqual(restored["1"].status, "pending")

        def restore(draft):
            draft.get_candidate("1").status = restored["1"].status

        undone = self.change(ready, restore, [{"type": "undo", "targets": seqs}], undoes=seqs)
        target = self.store.undo_target()
        seqs, _, restored = target.seqs, target.label, target.restored
        self.assertEqual(restored["1"].status, "pending")

        def restore_legacy(draft):
            draft.get_candidate("1").status = restored["1"].status

        final = self.change(undone, restore_legacy, [{"type": "undo", "targets": seqs}], undoes=seqs)
        self.assertEqual(final.get_candidate("1").status, "pending")

    def test_grouped_changes_undo_together_and_created_clips_are_removed(self):
        def first(draft):
            draft.get_candidate("1").status = "rejected"
        def second(draft):
            draft.duplicate_candidate("2")
        session = self.change(self.session, first, [{"type": "a"}], label="run", undo_group="g", undoable=True)
        self.change(session, second, [{"type": "b"}], label="run", undo_group="g", undoable=True)
        target = self.store.undo_target()
        seqs, _, restored = target.seqs, target.label, target.restored
        self.assertEqual(len(seqs), 2)
        self.assertEqual(restored["1"].status, "pending")
        self.assertIsNone(restored["2-2"])

    def test_undo_records_changed_fields_and_skips_background_runs(self):
        def trim(draft):
            clip = draft.get_candidate("1")
            clip.status, clip.title = "group1", "Renamed"
        session = self.change(self.session, trim, [{"type": "status"}], label="1", undoable=True)

        def detect(draft):
            draft.get_candidate("2").start = "00:00:03.400"
        # Older stores saved background runs as undoable; Undo still skips them.
        self.change(session, detect, [{"type": "detect-silence"}], label="Detect leading silence",
                    undo_group="leading-silence:job", undoable=True)
        target = self.store.undo_target()
        self.assertEqual(target.label, "1")
        self.assertEqual(target.fields, {"1": {"status", "title"}})
        self.assertEqual(target.restored["1"].title, "First")

    def test_changes_saved_without_fields_restore_the_whole_clip(self):
        def decide(draft):
            draft.get_candidate("1").status = "group1"
        self.change(self.session, decide, [{"type": "status"}], label="1", undoable=True)
        self.store._db.execute("UPDATE event SET changes = NULL")
        target = self.store.undo_target()
        self.assertEqual((target.fields, target.restored["1"].status), ({}, "pending"))

    def test_older_stores_gain_the_changes_column(self):
        self.store._db.execute("ALTER TABLE event DROP COLUMN changes")
        self.store.close()
        self.store = RecordingStore(self.path)
        columns = {row[1] for row in self.store._db.execute("PRAGMA table_info(event)")}
        self.assertIn("changes", columns)

    def test_suggestions_of_one_run_undo_together(self):
        self.store.record_suggestion("1", None, "Better", {"type": "suggest-title"}, label="Re-transcribe titles",
                                     undo_group="clip-transcription:a")
        self.store.record_suggestion("1", "Better", "Best", {"type": "suggest-title"},
                                     label="Re-transcribe titles", undo_group="clip-transcription:a")
        self.store.record_suggestion("2", "Old", "New", {"type": "suggest-title"}, label="Re-transcribe titles",
                                     undo_group="clip-transcription:a")
        self.assertTrue(self.store.can_undo())
        target = self.store.undo_target()
        self.assertEqual(len(target.seqs), 3)
        self.assertEqual(target.restored, {})
        self.assertEqual(target.suggestions, {"1": (None, "Best"), "2": ("Old", "New")})

    def test_stale_writer_is_rejected(self):
        other = RecordingStore(self.path)
        try:
            stale = other.load()

            def decide(draft):
                draft.get_candidate("1").status = "group2"
            self.change(self.session, decide, [{"type": "status"}])
            stale.get_candidate("1").status = "rejected"
            with self.assertRaises(StoreConflict):
                other.commit(stale, {"1": self.session.get_candidate("1")}, [{"type": "status"}])
            self.assertEqual(self.store.load().get_candidate("1").status, "group2")
        finally:
            other.close()

    def test_views_are_recorded_without_changing_state(self):
        self.store.append_events([{"type": "view", "clip": "2", "dwell_ms": 1500}])
        self.assertEqual(self.store.load().revision, 1)
        view = self.store.events(kinds=("view",))[0]
        self.assertEqual((view["clip"], view["dwell_ms"], view["mutation"]), ("2", 1500, None))


if __name__ == "__main__":
    unittest.main()
