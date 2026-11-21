"""Build the ranking input rows and hash the frozen inputs they came from.

Rows are the reviewed legacy clips (0511, 0526, 0602, 0614; pending clips excluded) plus the
decided clips of the generated 0903 review set. Legacy text is the original SRT text recovered
from the EmbeddingGemma metadata, never an edited title. Labels are kept (1) versus skipped or
rejected (0) and are never shown to a model. Private inputs are read from paths given on the
command line; nothing is written next to them. They must match the hashes recorded in
``input-hashes.json`` (--input-hashes); the hashes read are written to
``ranking-input.sources.json`` beside the rows.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from collections import Counter
from pathlib import Path

import frozen_inputs

GENERATED_DECIDED = ("exported", "group1", "group2", "rejected")


def legacy_rows(features: list[dict], srt_texts: dict[tuple[str, int], str]) -> list[dict]:
    rows = []
    for d in features:
        if d["rec"] == "0903" or d["status"] == "pending":
            continue
        rows.append(dict(
            id=f"{d['rec']}:{d['idx']}", recording=d["rec"], text=srt_texts[d["rec"], d["idx"]],
            label=int(d["status"] != "skipped"), role="legacy", source="transcript",
        ))
    return rows


def generated_rows(snapshot: Path) -> list[dict]:
    """Decided clips of the 0903 snapshot, with the role (random or top) of the review set."""
    rows = []
    # Read-only: the snapshot is a frozen copy and must never be written.
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as con:
        clips = {cid: json.loads(data) for cid, data in con.execute("select clip_id,data from clip")}
        review = json.loads(con.execute("select value from meta where key='review_set'").fetchone()[0])
    for cid, role in review["roles"].items():
        clip = clips[cid]
        if clip["status"] not in GENERATED_DECIDED:
            continue
        rows.append(dict(
            id="0903:" + cid, recording="0903", text=clip["source_text"],
            label=int(clip["status"] != "rejected"), role=role, source="generated",
        ))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--legacy-features", type=Path, required=True,
                        help="feats.json from the 2026-10-11 ranking experiment")
    parser.add_argument("--eg2-meta", type=Path, required=True,
                        help="eg2_meta.json from the 2026-10-12 EmbeddingGemma experiment")
    parser.add_argument("--snapshot", type=Path, required=True, help="frozen 0903 .jipandan.db copy")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--input-hashes", type=Path, default=frozen_inputs.PINNED,
                        help="recorded hashes of the frozen inputs (default: this experiment's)")
    args = parser.parse_args(argv)
    hashes = frozen_inputs.check({"legacy_features": args.legacy_features, "eg2_meta": args.eg2_meta,
                                  "snapshot_0903": args.snapshot}, args.input_hashes)

    srt_texts: dict[tuple[str, int], str] = {}
    for m in json.loads(args.eg2_meta.read_text()):
        srt_texts.setdefault((m["rec"], m["idx"]), m["srt_text"])
    rows = legacy_rows(json.loads(args.legacy_features.read_text()), srt_texts)
    rows += generated_rows(args.snapshot)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ranking-input.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    (args.out_dir / "ranking-input.sources.json").write_text(json.dumps(hashes, indent=2))
    print("rows", len(rows), "by recording", Counter(r["recording"] for r in rows))


if __name__ == "__main__":
    main()
