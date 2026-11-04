"""Build the corrected legacy feature matrix and recording-held-out baseline predictions.

Inputs: ``ranking-input.json`` (from prepare_inputs.py) and the three legacy feature archives
of the 2026-10-11 ranking experiment (``feats.json``, ``playback.json``, ``whisperfeat.json``).
Outputs in --out-dir:

* ``ranking-features.npz``: the 42-column corrected matrix ``X`` (``fully_clean``), labels,
  recordings, row IDs and the held-out predictions of five feature sets.
* ``ranking-leakage.json``: per-recording AUC and recall for those five sets.
* ``ranking-current.json``: the generated 0903 session scored with the application's built-in
  ranks before and after the tied-rank correction, with bootstrap intervals.

Two edited-title leaks are removed. Text-shape features (columns 20-23) and the
Whisper-versus-text agreement (last column) are recomputed from the original SRT text, not from
the edited title kept in the old archive. Needs the repository's ``src`` on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from jipandan.core.clip_features import SCORE_SIGNALS, likely_keep_scores

AUDIO_FEATURES = ["dur", "db_mean", "db_max", "db_std", "db_p90", "rel_ctx", "rel_floor", "active_frac",
                  "pre_db", "post_db", "gap_prev", "voiced", "f0_med", "f0_std", "f0_range", "f0_slope",
                  "centroid", "flat", "zcr", "onsets"]
PLAYBACK_FEATURES = ["b_lo", "b_lomid", "b_mid", "b_himid", "b_hi", "tilt", "lo_minus_hi", "centroid_loud",
                     "env_rise_p90", "env_fall_p10", "dyn_range", "mod_2_8", "flux"]


def text_shape(text: str, duration: float) -> list[float]:
    n = len(text)
    return [n, n / max(duration, .1),
            max((text.count(text[i:i + 2]) for i in range(max(n - 1, 1))), default=0),
            int(bool(re.search(r"[!！?？]", text)))]


def agreement(a: str, b: str) -> float:
    a, b = set(a), set(b)
    return len(a & b) / max(len(a | b), 1)


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    order = np.argsort(-p, kind="stable")
    cs = y[order].cumsum() / y.sum()
    return dict(auc=roc_auc_score(y, p), recall20=cs[max(0, int(.2 * len(y)) - 1)],
                recall50=cs[len(y) // 2 - 1], review80=(np.searchsorted(cs, .8) + 1) / len(y))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rows", type=Path, required=True, help="ranking-input.json")
    parser.add_argument("--legacy-dir", type=Path, required=True,
                        help="data/ folder holding feats.json, playback.json and whisperfeat.json")
    parser.add_argument("--snapshot", type=Path, required=True, help="frozen 0903 .jipandan.db copy")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = json.loads(args.rows.read_text())
    texts = {r["id"]: r["text"] for r in rows}
    D = [d for d in json.loads((args.legacy_dir / "feats.json").read_text())
         if d["status"] != "pending" and d["rec"] != "0903"]
    key = [(d["rec"], d["idx"]) for d in D]
    y = np.array([int(d["status"] != "skipped") for d in D])
    rec = np.array([d["rec"] for d in D])
    playback = {(d["rec"], d["idx"]): d for d in json.loads((args.legacy_dir / "playback.json").read_text())}
    whisper = {(d["rec"], d["idx"]): d for d in json.loads((args.legacy_dir / "whisperfeat.json").read_text())}

    A = np.array([[d.get(f, np.nan) for f in AUDIO_FEATURES] + text_shape(d["txt"], d["dur"])
                  + [playback[k].get(f, np.nan) for f in PLAYBACK_FEATURES] for d, k in zip(D, key)])
    W = np.array([[whisper[k]["avg_logprob"], whisper[k]["no_speech_prob"], whisper[k]["compression_ratio"],
                   len(whisper[k]["wtext"].strip()), agreement(whisper[k]["wtext"], d["txt"])]
                  for d, k in zip(D, key)])
    old_x = np.c_[A, W]
    claimed = old_x.copy()  # only the text-shape leak removed
    clean = old_x.copy()    # text-shape and agreement leaks removed
    for i, (d, k) in enumerate(zip(D, key)):
        text = texts[f"{k[0]}:{k[1]}"]
        clean[i, 20:24] = claimed[i, 20:24] = text_shape(text, d["dur"])
        clean[i, -1] = agreement(whisper[k]["wtext"], text)

    def model(X, train, test):
        return HistGradientBoostingClassifier(
            max_iter=300, learning_rate=.05, max_leaf_nodes=15, l2_regularization=1.,
            class_weight="balanced", random_state=0).fit(X[train], y[train]).predict_proba(X[test])[:, 1]

    results, pred = {}, {}
    for name, X in [("old_title_leak", old_x), ("previous_clean_still_agreement_leak", claimed),
                    ("fully_clean", clean), ("audio_only", clean[:, :20]),
                    ("single_clip_confidence", clean[:, -5:-1])]:
        pred[name] = np.zeros(len(y))
        results[name] = {}
        for r in sorted(set(rec)):
            train = np.flatnonzero(rec != r)
            test = np.flatnonzero(rec == r)
            p = model(X, train, test)
            pred[name][test] = p
            results[name][r] = metrics(y[test], p)
        print(name, results[name], flush=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(args.out_dir / "ranking-features.npz", X=clean, y=y, recording=rec,
             ids=np.array([f"{r}:{i}" for r, i in key]), **pred)
    (args.out_dir / "ranking-leakage.json").write_text(json.dumps(results, indent=2))

    # Exact tie correction and missing-feature diagnostics on the real generated session.
    with sqlite3.connect(f"file:{args.snapshot}?mode=ro", uri=True) as con:
        clips = {k: json.loads(d) for k, d in con.execute("select clip_id,data from clip")}
        review = json.loads(con.execute("select value from meta where key='review_set'").fetchone()[0])
    ids = sorted(clips, key=lambda k: (clips[k]["index"], clips[k]["suffix"]))
    objs = [SimpleNamespace(**clips[k]) for k in ids]
    before = np.array(likely_keep_scores(objs))
    after = np.zeros(len(ids))
    counts = np.zeros(len(ids))
    diag = {}
    for field, higher_is_better in SCORE_SIGNALS:
        v = np.array([getattr(o, field, None) if getattr(o, field, None) is not None else np.nan for o in objs])
        present = np.isfinite(v)
        after[present] += (rankdata(v[present] if higher_is_better else -v[present]) - 1) / (present.sum() - 1)
        counts[present] += 1
        diag[field] = dict(missing=int((~present).sum()), unique=int(len(np.unique(v[present]))),
                           rows=int(present.sum()))
    after = np.round(100 * after / counts, 1)
    index = {k: i for i, k in enumerate(ids)}
    current = {"features": diag, "mean_absolute_score_change": float(abs(after - before).mean()),
               "top240_replaced": int(len(set(np.argsort(-before)[:240]) - set(np.argsort(-after)[:240]))),
               "subsets": {}}
    rng = np.random.default_rng(47)
    for group in ["random", "top"]:
        sel = np.array([index[k] for k in review[group]])
        yy = np.array([clips[ids[i]]["status"] != "rejected" for i in sel], int)
        b, a = before[sel], after[sel]
        boots, deltas = [], []
        for _ in range(2000):
            j = rng.integers(0, len(yy), len(yy))
            if len(set(yy[j])) < 2:
                continue
            boots.append(roc_auc_score(yy[j], a[j]))
            deltas.append(roc_auc_score(yy[j], a[j]) - roc_auc_score(yy[j], b[j]))
        current["subsets"][group] = {
            "n": len(sel), "kept": int(yy.sum()), "before": metrics(yy, b), "tie_corrected": metrics(yy, a),
            "auc_ci95": np.quantile(boots, [.025, .975]).tolist(),
            "auc_delta_ci95": np.quantile(deltas, [.025, .975]).tolist()}
    print("generated", current, flush=True)
    (args.out_dir / "ranking-current.json").write_text(json.dumps(current, indent=2))


if __name__ == "__main__":
    main()
