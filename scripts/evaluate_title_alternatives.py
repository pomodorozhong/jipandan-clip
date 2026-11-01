"""Compare title copy, model output, aligned words and optional cached clip transcriptions.

Uses the same selected title rows as experiment_titles.py. Aligned words use the owner's
final range, so this tests title assistance after trimming, not prediction of final timing.
Approved titles are editorial references, not verbatim transcription labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from experiment_titles import distance, normalize
from jipandan.core.srt import srt_time_to_seconds


def words_in_range(words, start, end):
    return "".join(w["word"] for w in words
                   if w.get("end", 0) > w.get("start", 0)
                   and start <= (w["start"] + w["end"]) / 2 < end).strip()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--titles", type=Path, required=True)
    p.add_argument("--outputs", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--cached-whisper", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    titles = {r["id"]: r for r in json.loads(args.titles.read_text())}
    chosen = [json.loads(line) for line in args.outputs.read_text().splitlines()]
    if len({r["id"] for r in chosen}) != len(chosen):
        raise ValueError("duplicate selected title ids")
    for row in chosen:
        reference = titles[row["id"]]
        if row["text_sha256"] != hashlib.sha256(reference["text"].encode()).hexdigest():
            raise ValueError("title output does not match its source transcript")
        row["edited"] = normalize(reference["text"]) != normalize(reference["approved"])
    cached = {f"{r['rec']}:{r['idx']}": r["wtext"] for r in
              json.loads(args.cached_whisper.read_text())} if args.cached_whisper else {}
    results = []
    for config in json.loads(args.config.read_text()):
        segments = json.loads(Path(config["words"]).read_text())["segments"]
        words = sorted([w for s in segments for w in s.get("words", [])], key=lambda w: w["start"])
        session = Path(config["session"])
        if session.suffix == ".db":
            with sqlite3.connect(f"file:{session.resolve()}?mode=ro", uri=True) as connection:
                clips = [json.loads(d) for (d,) in connection.execute("SELECT data FROM clip")]
        else:
            clips = json.loads(session.read_text())["candidates"]
        clips = {str(c["index"]): c for c in clips if not c.get("suffix")}
        for row in chosen:
            if row["recording"] != config["name"]:
                continue
            reference, clip = titles[row["id"]], clips[row["id"].split(":", 1)[1]]
            start = srt_time_to_seconds(clip["start"].replace(".", ","))
            aligned = words_in_range(words, start, start + float(clip["duration"]))
            proposed = {"copy": reference["text"], "lfm3": row["title"],
                        "words_in_final_range": aligned or reference["text"]}
            if row["id"] in cached:
                proposed["cached_clip_whisper"] = cached[row["id"]]
            results.append({"recording": row["recording"], "edited": row["edited"],
                            "empty_aligned": not aligned, "distance": {
                                name: distance(normalize(text), normalize(reference["approved"]))
                                for name, text in proposed.items()}})
    summary = {}
    for recording in sorted({r["recording"] for r in results}):
        summary[recording] = {}
        for edited in (False, True):
            group = [r for r in results if r["recording"] == recording and r["edited"] == edited]
            if not group:
                continue
            entry = {"n": len(group), "empty_aligned": sum(r["empty_aligned"] for r in group), "models": {}}
            for name in group[0]["distance"]:
                values = np.array([r["distance"][name] for r in group])
                baseline = np.array([r["distance"]["copy"] for r in group])
                entry["models"][name] = {"distance": float(values.mean()),
                                         "improved": int((values < baseline).sum()),
                                         "worsened": int((values > baseline).sum()),
                                         "exact": int((values == 0).sum())}
            summary[recording]["edited" if edited else "unchanged"] = entry
    if len(results) != len(chosen):
        raise ValueError("configs must cover every selected title row exactly once")
    args.out.write_text(json.dumps({"summary": summary}, indent=2) + "\n")


if __name__ == "__main__":
    main()
