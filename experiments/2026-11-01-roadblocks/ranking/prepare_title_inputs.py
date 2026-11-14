"""Build the approved-title rows of the title experiments.

One row per approved source clip: ``text`` is the transcript the clip started from, ``approved``
the title the owner exported it with, and ``edited`` whether the two differ once punctuation,
spaces and symbols are ignored.

* Legacy recordings: every (recording, index) whose first entry in the EmbeddingGemma metadata
  has the status ``exported`` or ``group2`` (Ready), in the metadata's order. Only the first entry
  of a clip counts, so a clip whose first entry has another status is left out even when a later
  entry is approved. ``srt_text`` is the transcript and ``title`` the approved title.
* Generated 0903 session: every review-set clip of the frozen snapshot whose status is
  ``exported`` or ``group2``, in the snapshot's stored order (``rowid``), after the legacy rows. The
  transcript is ``source_text`` and the approved title the last exported title, or the current
  title when the clip was never exported.

Needs work clips are left out: their titles were not approved. ``experiment_titles.py`` and
``evaluate_title_alternatives.py`` draw their samples from these rows in this order.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

import frozen_inputs

APPROVED = ("exported", "group2")


def normalize(text: str) -> str:
    # The same rule as model_scoring/experiment_titles.py, which measures edits with it.
    return "".join(c for c in unicodedata.normalize("NFKC", text)
                   if not unicodedata.category(c).startswith(("P", "Z", "S")))


def row(row_id: str, recording: str, text: str, approved: str) -> dict:
    return dict(id=row_id, recording=recording, text=text, approved=approved,
                edited=normalize(approved) != normalize(text))


def legacy_rows(meta: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for m in meta:
        key = (m["rec"], m["idx"])
        if key in seen:
            continue
        seen.add(key)
        if m["status"] in APPROVED:
            rows.append(row(f"{key[0]}:{key[1]}", key[0], m["srt_text"], m["title"]))
    return rows


def generated_rows(snapshot: Path) -> list[dict]:
    # Read-only: the snapshot is a frozen copy and must never be written.
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as con:
        clips = [(cid, json.loads(data)) for cid, data in con.execute("select clip_id,data from clip order by rowid")]
        roles = json.loads(con.execute("select value from meta where key='review_set'").fetchone()[0])["roles"]
    return [row("0903:" + cid, "0903", c["source_text"], c.get("last_export_title") or c["title"])
            for cid, c in clips if cid in roles and c["status"] in APPROVED]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--eg2-meta", type=Path, required=True,
                        help="eg2_meta.json from the 2026-10-12 EmbeddingGemma experiment")
    parser.add_argument("--snapshot", type=Path, required=True, help="frozen 0903 .jipandan.db copy")
    parser.add_argument("--out", type=Path, required=True, help="title-input.json")
    parser.add_argument("--input-hashes", type=Path, default=frozen_inputs.PINNED,
                        help="recorded hashes of the frozen inputs (default: this experiment's)")
    args = parser.parse_args(argv)
    frozen_inputs.check({"eg2_meta": args.eg2_meta, "snapshot_0903": args.snapshot}, args.input_hashes)
    if args.out.exists():
        parser.error(f"{args.out} already exists; use a new path")

    rows = legacy_rows(json.loads(args.eg2_meta.read_text())) + generated_rows(args.snapshot)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    for recording in sorted({r["recording"] for r in rows}):
        subset = [r for r in rows if r["recording"] == recording]
        print(recording, len(subset), "approved,", sum(r["edited"] for r in subset), "edited", flush=True)
    print("sha256", frozen_inputs.sha256(args.out), flush=True)


if __name__ == "__main__":
    main()
