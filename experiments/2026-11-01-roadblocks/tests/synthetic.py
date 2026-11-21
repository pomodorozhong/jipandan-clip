"""Small synthetic stand-ins for the private ranking inputs; no recordings or model downloads.

``make_inputs`` writes the three legacy archives, the EmbeddingGemma metadata and a 0903
database snapshot with the same fields the preparation scripts read. All values are random
(seeded) and carry no real transcript text.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

LEGACY = ["0511", "0526", "0602", "0614"]
PER_RECORDING = 40
GENERATED = 50
AUDIO = ["dur", "db_mean", "db_max", "db_std", "db_p90", "rel_ctx", "rel_floor", "active_frac", "pre_db",
         "post_db", "gap_prev", "voiced", "f0_med", "f0_std", "f0_range", "f0_slope", "centroid", "flat",
         "zcr", "onsets"]
PLAYBACK = ["b_lo", "b_lomid", "b_mid", "b_himid", "b_hi", "tilt", "lo_minus_hi", "centroid_loud",
            "env_rise_p90", "env_fall_p10", "dyn_range", "mod_2_8", "flux"]


def make_inputs(root: Path, seed: int = 7) -> dict[str, Path]:
    rng = np.random.default_rng(seed)
    legacy_dir = root / "legacy"
    legacy_dir.mkdir(parents=True)
    feats, playback, whisper, meta = [], [], [], []
    for rec in LEGACY:
        for idx in range(1, PER_RECORDING + 1):
            status = ["exported", "skipped", "skipped", "pending"][int(rng.integers(0, 4))]
            keep = status != "skipped"
            row = {"rec": rec, "idx": idx, "status": status, "txt": f"edited title {rec} {idx}" * (1 + idx % 3)}
            row.update({k: float(rng.normal(loc=0.8 * keep)) for k in AUDIO})
            row["dur"] = float(rng.uniform(.5, 6))
            feats.append(row)
            playback.append({"rec": rec, "idx": idx, **{k: float(rng.normal()) for k in PLAYBACK}})
            whisper.append({"rec": rec, "idx": idx, "avg_logprob": float(rng.normal()),
                            "no_speech_prob": float(rng.uniform()), "compression_ratio": float(rng.uniform(.5, 2)),
                            "wtext": "abcdefg"[: 1 + idx % 6]})
            meta.append({"rec": rec, "idx": idx, "srt_text": "original text " + "ab" * (idx % 5 + 1)})
    (legacy_dir / "feats.json").write_text(json.dumps(feats))
    (legacy_dir / "playback.json").write_text(json.dumps(playback))
    (legacy_dir / "whisperfeat.json").write_text(json.dumps(whisper))
    eg2 = root / "eg2_meta.json"
    eg2.write_text(json.dumps(meta))

    snapshot = root / "0903.jipandan.db"
    random_ids = [str(i) for i in range(1, GENERATED // 2 + 1)]
    top_ids = [str(i) for i in range(GENERATED // 2 + 1, GENERATED + 1)]
    with closing(sqlite3.connect(snapshot)) as con, con:
        con.execute("create table clip(clip_id text primary key, data text)")
        con.execute("create table meta(key text primary key, value text)")
        for cid in random_ids + top_ids:
            kept = int(rng.integers(0, 2))
            con.execute("insert into clip values (?, ?)", (cid, json.dumps({
                "index": int(cid), "suffix": "", "status": ["rejected", "exported"][kept],
                "source_text": "generated " + cid,
                # Repeated values exercise the tied-rank correction.
                "peak_db": float(round(rng.normal() + kept, 1)), "no_speech_prob": float(rng.uniform()),
                "mid_share_db": float(round(rng.normal(), 1)), "bass_share_db": float(round(rng.normal(), 1)),
            })))
        review = {"roles": {**{c: "random" for c in random_ids}, **{c: "top" for c in top_ids}},
                  "random": random_ids, "top": top_ids}
        con.execute("insert into meta values ('review_set', ?)", (json.dumps(review),))
    inputs = {"legacy_dir": legacy_dir, "feats": legacy_dir / "feats.json", "eg2": eg2, "snapshot": snapshot,
              "hashes": root / "input-hashes.json"}
    pin(inputs)
    return inputs


def pin(inputs: dict[str, Path]) -> None:
    """Record the synthetic inputs' hashes, as the tracked ``input-hashes.json`` does for the real ones."""
    files = {"legacy_features": inputs["feats"], "legacy_playback": inputs["legacy_dir"] / "playback.json",
             "legacy_whisper": inputs["legacy_dir"] / "whisperfeat.json", "eg2_meta": inputs["eg2"],
             "snapshot_0903": inputs["snapshot"]}
    inputs["hashes"].write_text(json.dumps({"frozen_inputs": {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}))


def write_pipeline_features(folder: Path, seed: int = 11) -> None:
    """Legacy-recording pipeline features keyed like the real files: ``<rec>:<index>``."""
    rng = np.random.default_rng(seed)
    folder.mkdir(parents=True, exist_ok=True)
    for rec in LEGACY:
        rows = [{"id": f"{rec}:{idx}", "peak_db": float(rng.normal()), "no_speech_prob": float(rng.uniform()),
                 "mid_share_db": float(rng.normal()), "bass_share_db": float(rng.normal())}
                for idx in range(1, PER_RECORDING + 1)]
        (folder / f"{rec}.pipeline-features.json").write_text(json.dumps(rows))
