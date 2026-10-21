"""Per-recording SQLite store: current clip state plus an append-only history.

Each recording gets ``<audio>.jipandan.db`` beside it. The ``clip`` table holds
the current state of every clip; the ``event`` table records every change and
review action in order. A change ("mutation") is written in one transaction with
its events, and its first event keeps the affected clips' prior state so it can
be undone, even after a restart. Training reads the same history.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jipandan.core.models import ClipCandidate, Session, clip_candidate_from_dict

STORE_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clip (
    clip_id TEXT PRIMARY KEY,
    idx INTEGER NOT NULL,
    suffix INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS clip_order ON clip (idx, suffix);
CREATE TABLE IF NOT EXISTS event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    t TEXT NOT NULL,
    type TEXT NOT NULL,
    clip_id TEXT,
    -- First event of the change it belongs to; NULL for events that change nothing (views).
    mutation INTEGER,
    label TEXT,
    undo_group TEXT,
    undoable INTEGER NOT NULL DEFAULT 0,
    undone_by INTEGER,
    -- Affected clips before the change, as {clip_id: clip or null}; set on a change's first event.
    before TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_undo ON event (undoable, undone_by, seq);
CREATE TABLE IF NOT EXISTS suggestion (clip_id TEXT PRIMARY KEY, title TEXT NOT NULL);
-- Clip edge snap points (word starts, speech ends) measured once per recording.
CREATE TABLE IF NOT EXISTS snap_point (kind TEXT NOT NULL, ms INTEGER NOT NULL, PRIMARY KEY (kind, ms)) WITHOUT ROWID;
"""

_META_FIELDS = (
    "audio", "srt", "clip_dir", "export_dirs", "srt_fingerprint", "leading_silence_detection_complete",
    "clip_features_complete", "clip_features_version",
)


class StoreConflict(RuntimeError):
    """Another process changed the store since this copy was loaded."""


def store_path(audio: Path) -> Path:
    return audio.with_suffix(".jipandan.db")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clip_json(candidate: ClipCandidate | None) -> dict | None:
    return None if candidate is None else asdict(candidate)


class RecordingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # Session state ---------------------------------------------------------

    def _meta(self) -> dict[str, object]:
        return {key: json.loads(value) for key, value in self._db.execute("SELECT key, value FROM meta")}

    def _write_meta(self, session: Session, revision: int) -> None:
        values = {
            "store_version": STORE_VERSION, "revision": revision,
            "audio": str(session.audio), "srt": str(session.srt), "clip_dir": str(session.clip_dir),
            "export_dirs": [str(d) for d in dict.fromkeys([*session.export_dirs, session.clip_dir])],
            "srt_fingerprint": session.srt_fingerprint,
            "leading_silence_detection_complete": session.leading_silence_detection_complete,
            "clip_features_complete": session.clip_features_complete,
            "clip_features_version": session.clip_features_version,
        }
        self._db.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                             [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])

    def _write_clips(self, session: Session, clip_ids: set[str] | None) -> None:
        current = {c.clip_id: c for c in session.candidates}
        targets = current.keys() if clip_ids is None else clip_ids
        for clip_id in targets:
            candidate = current.get(clip_id)
            if candidate is None:
                self._db.execute("DELETE FROM clip WHERE clip_id = ?", (clip_id,))
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO clip (clip_id, idx, suffix, data) VALUES (?, ?, ?, ?)",
                    (clip_id, candidate.index, candidate.suffix, json.dumps(asdict(candidate), ensure_ascii=False)),
                )

    def is_initialized(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM meta WHERE key = 'revision'").fetchone() is not None

    def create(self, session: Session, snap_points: dict[str, list[int]] | None = None) -> None:
        """Store a freshly imported session as revision 1, with its snap points by kind."""
        with self._lock, self._transaction():
            if self._db.execute("SELECT 1 FROM meta WHERE key = 'revision'").fetchone():
                raise StoreConflict(f"{self.path.name} already holds a recording")
            self._write_meta(session, 1)
            self._write_clips(session, None)
            self._db.executemany(
                "INSERT OR IGNORE INTO snap_point (kind, ms) VALUES (?, ?)",
                [(kind, ms) for kind, points in (snap_points or {}).items() for ms in points],
            )
            self._insert_event("import", None, {"clips": len(session.candidates)}, mutation=None)
        session.revision = 1

    def review_set(self) -> dict | None:
        """Return the session's review set, or None when it has none."""
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'review_set'").fetchone()
        return json.loads(row[0]) if row else None

    def save_review_set(self, review_set: dict, event: dict) -> None:
        """Save the review set and log ``event`` in one transaction; neither changes a clip or can be undone."""
        with self._lock, self._transaction():
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('review_set', ?)",
                             (json.dumps(review_set, ensure_ascii=False),))
            fields = dict(event)
            self._insert_event(str(fields.pop("type")), None, fields, mutation=None)

    def snap_points(self, kind: str) -> list[int]:
        """Return the recording's snap points of ``kind`` in milliseconds, in order."""
        with self._lock:
            return [ms for (ms,) in self._db.execute(
                "SELECT ms FROM snap_point WHERE kind = ? ORDER BY ms", (kind,))]

    def load(self) -> Session:
        with self._lock, self._transaction():
            meta = self._meta()
            if meta.get("store_version") != STORE_VERSION:
                raise StoreConflict(f"{self.path.name} uses an unsupported format")
            rows = self._db.execute("SELECT clip_id, data FROM clip ORDER BY idx, suffix").fetchall()
            legacy_unsure = {
                clip_id for clip_id, data in rows if json.loads(data).get("status") == "unsure"
            }
            candidates = [
                clip_candidate_from_dict(json.loads(data)) for _, data in rows
            ]
            session = Session(
                audio=Path(str(meta["audio"])), srt=Path(str(meta["srt"])), clip_dir=Path(str(meta["clip_dir"])),
                export_dirs=[Path(d) for d in meta.get("export_dirs") or [meta["clip_dir"]]],
                candidates=candidates, revision=int(meta["revision"]),
                srt_fingerprint=meta.get("srt_fingerprint"),
                leading_silence_detection_complete=bool(meta.get("leading_silence_detection_complete")),
                clip_features_complete=bool(meta.get("clip_features_complete")),
                clip_features_version=meta.get("clip_features_version"),
            )
            if legacy_unsure:
                session.revision += 1
                self._write_meta(session, session.revision)
                self._write_clips(session, legacy_unsure)
                self._insert_event("legacy_status_reset", None, {"clips": len(legacy_unsure)}, mutation=None)
            return session

    def commit(
        self, draft: Session, before: dict[str, ClipCandidate | None], events: list[dict], *,
        label: str | None = None, undo_group: str | None = None, undoable: bool = False,
        all_clips: bool = False, undoes: list[int] | None = None,
    ) -> int:
        """Save ``draft`` and its events as one change; returns the new revision.

        ``before`` holds the prior state of every clip the change touched (None for
        clips it created). ``undoes`` marks earlier changes as reverted by this one.
        Raises StoreConflict when another writer got there first.
        """
        with self._lock, self._transaction():
            stored = self._db.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
            if stored is None or json.loads(stored[0]) != draft.revision:
                raise StoreConflict(
                    f"Recording is at revision {stored and json.loads(stored[0])}; opened revision {draft.revision}"
                )
            revision = draft.revision + 1
            self._write_meta(draft, revision)
            self._write_clips(draft, None if all_clips else set(before))
            first: int | None = None
            for position, event in enumerate(events or [{"type": "change"}]):
                fields = dict(event)
                kind = str(fields.pop("type"))
                clip_id = fields.pop("clip", None)
                if position == 0:
                    first = self._insert_event(
                        kind, clip_id, fields, mutation=None, label=label, undo_group=undo_group,
                        undoable=undoable, before={k: _clip_json(v) for k, v in before.items()},
                    )
                    self._db.execute("UPDATE event SET mutation = seq WHERE seq = ?", (first,))
                    self._db.executemany("UPDATE event SET undone_by = ? WHERE seq = ?",
                                         [(first, target) for target in undoes or []])
                else:
                    self._insert_event(kind, clip_id, fields, mutation=first)
        draft.revision = revision
        return revision

    def update_clips(self, draft: Session, clip_ids: set[str]) -> int:
        """Save background measurements without recording them as a reviewable change."""
        with self._lock, self._transaction():
            stored = self._db.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
            if stored is None or json.loads(stored[0]) != draft.revision:
                raise StoreConflict("Recording changed while measurements were saved")
            revision = draft.revision + 1
            self._write_meta(draft, revision)
            self._write_clips(draft, clip_ids)
        draft.revision = revision
        return revision

    # Events ----------------------------------------------------------------

    def _insert_event(
        self, kind: str, clip_id: str | None, data: dict, *, mutation: int | None, label: str | None = None,
        undo_group: str | None = None, undoable: bool = False, before: dict | None = None,
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO event (t, type, clip_id, mutation, label, undo_group, undoable, before, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (utc_now(), kind, clip_id, mutation, label, undo_group, int(undoable),
             None if before is None else json.dumps(before, ensure_ascii=False),
             json.dumps(data, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)

    def append_events(self, events: list[dict]) -> None:
        """Record events that change no clip, such as views."""
        if not events:
            return
        with self._lock, self._transaction():
            for event in events:
                fields = dict(event)
                kind = str(fields.pop("type"))
                self._insert_event(kind, fields.pop("clip", None), fields, mutation=None)

    def events(self, *, kinds: tuple[str, ...] | None = None) -> list[dict]:
        """Every event in order, as dicts (for tests and offline training)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT seq, t, type, clip_id, mutation, label, undo_group, undoable, undone_by, data "
                "FROM event ORDER BY seq"
            ).fetchall()
        result = []
        for seq, t, kind, clip_id, mutation, label, group, undoable, undone_by, data in rows:
            if kinds is not None and kind not in kinds:
                continue
            result.append({
                "seq": seq, "t": t, "type": kind, "clip": clip_id, "mutation": mutation, "label": label,
                "undo_group": group, "undoable": bool(undoable), "undone_by": undone_by, **json.loads(data),
            })
        return result

    def can_undo(self) -> bool:
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM event WHERE undoable = 1 AND undone_by IS NULL LIMIT 1"
            ).fetchone() is not None

    def undo_target(self) -> tuple[list[int], str, dict[str, ClipCandidate | None]] | None:
        """The latest change still undoable, merged with the earlier changes in its group.

        Returns the changes' sequence numbers, a label, and each clip's state before
        the earliest of them.
        """
        with self._lock:
            latest = self._db.execute(
                "SELECT seq, label, undo_group FROM event WHERE undoable = 1 AND undone_by IS NULL "
                "ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                return None
            seq, label, group = latest
            if group is None:
                rows = self._db.execute("SELECT seq, before FROM event WHERE seq = ?", (seq,)).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT seq, before FROM event WHERE undoable = 1 AND undone_by IS NULL AND undo_group = ? "
                    "ORDER BY seq", (group,),
                ).fetchall()
        restored: dict[str, ClipCandidate | None] = {}
        for _, before in rows:
            for clip_id, state in json.loads(before or "{}").items():
                restored.setdefault(clip_id, None if state is None else clip_candidate_from_dict(state))
        return [row[0] for row in rows], label or "change", restored

    def last_seq(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(seq) FROM event").fetchone()
            return int(row[0] or 0)

    # Title suggestions -----------------------------------------------------

    def suggestions(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db.execute("SELECT clip_id, title FROM suggestion"))

    def set_suggestion(self, clip_id: str, title: str | None) -> None:
        with self._lock, self._transaction():
            if title is None:
                self._db.execute("DELETE FROM suggestion WHERE clip_id = ?", (clip_id,))
            else:
                self._db.execute("INSERT OR REPLACE INTO suggestion (clip_id, title) VALUES (?, ?)", (clip_id, title))

    # Housekeeping ----------------------------------------------------------

    def backup(self, destination: Path) -> None:
        with self._lock:
            target = sqlite3.connect(destination)
            try:
                self._db.backup(target)
            finally:
                target.close()

    def _transaction(self):
        return _Transaction(self._db)


class _Transaction:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def __enter__(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb) -> None:
        self._db.execute("COMMIT" if exc_type is None else "ROLLBACK")
