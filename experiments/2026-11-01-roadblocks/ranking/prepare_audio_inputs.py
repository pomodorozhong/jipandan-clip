"""Build the rows and audio excerpts of the paired text/audio (Omni) comparison.

Rows come from ``ranking-input.json``: a uniform random sample of each legacy recording's rows
(128 per recording, seed 128), drawn without looking at labels, plus every row of the generated
0903 review set. Each row gets ``audio_path``, a 16 kHz mono 16-bit PCM WAV of the clip's
original bounds (``original_start`` to ``original_end``, before any trimming), cut with the
application's exact-seek arguments. The row order is the recordings in name order, and within
each the order of ``ranking-input.json``.

The config is the JSON list of {name, session, audio} that ``prepare_pipeline_features.py``
reads; 0903 clips are read from the frozen snapshot instead of a session file. ``audio_path``
is absolute, so ``audio-input.json`` only keeps its recorded hash when --audio-dir is the same
folder as in the original run. An excerpt that already exists stops the run unless
--reuse-excerpts is given: ``evaluate_audio_semantics.py`` later checks every excerpt against
the hash its audio score recorded. Needs ffmpeg on PATH and the repository's ``src`` on
PYTHONPATH.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import numpy as np

import frozen_inputs
from jipandan.core.ffmpeg import seek_arguments
from prepare_pipeline_features import seconds

PER_RECORDING = 128
SEED = 128
GENERATED = "0903"


def select_rows(rows: list[dict], per_recording: int = PER_RECORDING, seed: int = SEED) -> list[dict]:
    """The sampled legacy rows and all generated rows. One generator runs through the recordings
    in name order, so the sample of a recording depends on the row counts of those before it."""
    rng = np.random.default_rng(seed)
    chosen = []
    for recording in sorted({r["recording"] for r in rows}):
        subset = [r for r in rows if r["recording"] == recording]
        if recording != GENERATED:
            picks = rng.choice(len(subset), min(per_recording, len(subset)), replace=False)
            subset = [subset[i] for i in sorted(picks)]
        chosen += subset
    return chosen


def original_spans(recording: str, cfg: dict, snapshot: Path) -> dict[str, tuple[float, float]]:
    """Original start and end in seconds of every unsplit clip, keyed by clip index."""
    if recording == GENERATED:
        # Read-only: the snapshot is a frozen copy and must never be written.
        with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as con:
            clips = [json.loads(data) for (data,) in con.execute("select data from clip")]
    else:
        clips = json.loads(Path(cfg["session"]).read_text())["candidates"]
    return {str(c["index"]): (seconds(c["original_start"]), seconds(c["original_end"]))
            for c in clips if not c.get("suffix")}


def extract(audio: Path, start: float, end: float, dest: Path) -> None:
    """Cut one excerpt. It appears under its final name only once ffmpeg has finished, so an
    interrupted run never leaves a truncated excerpt for --reuse-excerpts to keep."""
    before, after = seek_arguments(audio, start)
    partial = dest.with_name(dest.stem + ".part.wav")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *before, "-i", str(audio), *after,
                        "-t", str(max(.01, end - start)), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                        str(partial)], check=True)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rows", type=Path, required=True, help="ranking-input.json")
    parser.add_argument("--config", type=Path, required=True, help="recordings.json")
    parser.add_argument("--snapshot", type=Path, required=True, help="frozen 0903 .jipandan.db copy")
    parser.add_argument("--audio-dir", type=Path, required=True, help="folder for the WAV excerpts")
    parser.add_argument("--out", type=Path, required=True, help="audio-input.json")
    parser.add_argument("--reuse-excerpts", action="store_true",
                        help="keep excerpts that already exist in --audio-dir instead of stopping")
    parser.add_argument("--input-hashes", type=Path, default=frozen_inputs.PINNED,
                        help="recorded hashes of the frozen inputs (default: this experiment's)")
    args = parser.parse_args(argv)
    frozen_inputs.check({"snapshot_0903": args.snapshot}, args.input_hashes)
    if args.out.exists():
        parser.error(f"{args.out} already exists; use a new path")

    chosen = select_rows(json.loads(args.rows.read_text()))
    cfg = {c["name"]: c for c in json.loads(args.config.read_text())}
    dests = {r["id"]: args.audio_dir / (r["id"].replace(":", "_") + ".wav") for r in chosen}
    existing = [d.name for d in dests.values() if d.exists()]
    if existing and not args.reuse_excerpts:
        parser.error(f"{len(existing)} excerpts already exist in {args.audio_dir} (first: {existing[0]}); "
                     "pass --reuse-excerpts to keep them, or use a new --audio-dir")
    args.audio_dir.mkdir(parents=True, exist_ok=True)

    # Check the config and find every row's bounds before cutting anything, so a missing entry or a
    # row without bounds stops the run at once instead of after the excerpts before it.
    recordings = sorted({r["recording"] for r in chosen})
    for recording in recordings:
        entry = cfg.get(recording, {})
        if recording != GENERATED and not entry.get("session"):
            parser.error(f"{args.config.name} has no session file for {recording}")
        to_cut = any(not dests[r["id"]].exists() for r in chosen if r["recording"] == recording)
        if to_cut and not (entry.get("audio") and Path(entry["audio"]).is_file()):
            parser.error(f"{args.config.name} has no existing audio file for {recording}, whose excerpts must be cut")
    spans = {recording: original_spans(recording, cfg.get(recording, {}), args.snapshot) for recording in recordings}
    unknown = [r["id"] for r in chosen if r["id"].split(":")[1] not in spans[r["recording"]]]
    if unknown:
        parser.error(f"{len(unknown)} rows have no unsplit clip to cut (first: {unknown[0]}); "
                     "split clips are not supported")

    out = []
    for recording in recordings:
        rows = [r for r in chosen if r["recording"] == recording]
        reused = 0
        for row in rows:
            dest = dests[row["id"]]
            if dest.exists():
                reused += 1
            else:
                extract(Path(cfg[recording]["audio"]), *spans[recording][row["id"].split(":")[1]], dest)
            out.append({**row, "audio_path": str(dest.resolve())})
        print(recording, len(rows), "rows,", len(rows) - reused, "extracted,", reused, "reused", flush=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print("sha256", frozen_inputs.sha256(args.out), flush=True)


if __name__ == "__main__":
    main()
