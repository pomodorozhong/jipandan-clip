import tempfile
import unittest
from pathlib import Path

from jipandan.core.models import Session
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

    def change(self, session, mutate, events, **options):
        import copy
        draft = copy.deepcopy(session)
        mutate(draft)
        before = {c.clip_id: c for c in session.candidates}
        after = {c.clip_id: c for c in draft.candidates}
        changed = {i: before.get(i) for i in before.keys() | after.keys() if before.get(i) != after.get(i)}
        self.store.commit(draft, changed, events, **options)
        return draft

    def test_state_and_undo_survive_reopening(self):
        def decide(draft):
            draft.get_candidate("1").status = "group1"
        session = self.change(self.session, decide, [{"type": "status", "clip": "1", "to": "group1"}],
                              label="1", undoable=True)
        self.store.close()

        self.store = RecordingStore(self.path)
        reloaded = self.store.load()
        self.assertEqual((reloaded.revision, reloaded.get_candidate("1").status), (2, "group1"))
        seqs, label, restored = self.store.undo_target()
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

    def test_grouped_changes_undo_together_and_created_clips_are_removed(self):
        def first(draft):
            draft.get_candidate("1").status = "rejected"
        def second(draft):
            draft.duplicate_candidate("2")
        session = self.change(self.session, first, [{"type": "a"}], label="run", undo_group="g", undoable=True)
        self.change(session, second, [{"type": "b"}], label="run", undo_group="g", undoable=True)
        seqs, _, restored = self.store.undo_target()
        self.assertEqual(len(seqs), 2)
        self.assertEqual(restored["1"].status, "pending")
        self.assertIsNone(restored["2-2"])

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
