"""Rank the application's current clip features and fit recording-held-out baselines.

Reads ``ranking-input.json`` and every ``*.pipeline-features.json`` in --work-dir and writes
``pipeline-ranking.npz`` (feature ranks and baseline predictions for the same row IDs) and
``pipeline-evaluation.json`` to --out-dir. Feature order: peak, full-transcription no-speech
probability (sign flipped), mid-band share, bass share (sign flipped); each is a percentile
rank within its own recording. The old per-clip Whisper confidence is not available here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FIELDS = ["peak_db", "no_speech_prob", "mid_share_db", "bass_share_db"]
SIGNS = [1, -1, 1, -1]
RECORDINGS = ["0511", "0526", "0602", "0614", "0903"]


def ranked_features(path: Path) -> dict[str, np.ndarray]:
    rows = json.loads(path.read_text())
    values = np.array([[x.get(k) if x.get(k) is not None else np.nan for k in FIELDS] for x in rows])
    ranks = np.full_like(values, np.nan)
    for j, sign in enumerate(SIGNS):
        present = np.isfinite(values[:, j])
        ranks[present, j] = (rankdata(values[present, j] * sign) - 1) / (present.sum() - 1)
    return {row["id"]: rank for row, rank in zip(rows, ranks)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = json.loads((args.work_dir / "ranking-input.json").read_text())
    by_id: dict[str, np.ndarray] = {}
    for path in args.work_dir.glob("*.pipeline-features.json"):
        by_id.update(ranked_features(path))
    X = np.array([by_id[r["id"]] for r in rows])
    y = np.array([r["label"] for r in rows])
    recs = np.array([r["recording"] for r in rows])
    ids = np.array([r["id"] for r in rows])
    role = np.array([r["role"] for r in rows])

    pred = {
        "builtin_available": np.nanmean(X, axis=1), "audio_builtin": np.nanmean(X[:, [0, 2, 3]], axis=1),
        "peak": X[:, 0], "speech_confidence": X[:, 1], "mid_share": X[:, 2], "bass_share": X[:, 3],
        "refit_logistic": np.zeros(len(rows)), "refit_gbm": np.zeros(len(rows)),
    }
    out = {}
    for r in RECORDINGS:
        train = (recs != r) & (recs != "0903")
        test = recs == r
        refits = [
            ("refit_logistic", make_pipeline(SimpleImputer(), StandardScaler(),
                                             LogisticRegression(C=.1, class_weight="balanced", max_iter=1000))),
            ("refit_gbm", HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=7, l2_regularization=5,
                                                          class_weight="balanced", random_state=47)),
        ]
        for name, model in refits:
            fit_x = np.nan_to_num(X[train][:, [0, 2, 3]], nan=.5)
            test_x = np.nan_to_num(X[test][:, [0, 2, 3]], nan=.5)
            pred[name][test] = model.fit(fit_x, y[train]).predict_proba(test_x)[:, 1]
        for subset in (["legacy"] if r != "0903" else ["random", "top"]):
            mask = test & (role == subset)
            yy = y[mask]
            key = r + "_" + subset
            out[key] = {"n": int(mask.sum()), "kept": int(yy.sum()), "models": {}}
            for name, p in pred.items():
                pp = p[mask]
                valid = np.isfinite(pp)
                if not valid.any():
                    out[key]["models"][name] = {"unavailable": True}
                    continue
                pp = np.where(valid, pp, np.nanmedian(pp))
                order = np.argsort(-pp, kind="stable")
                cs = yy[order].cumsum() / yy.sum()
                out[key]["models"][name] = {
                    "auc": roc_auc_score(yy, pp), "recall20": float(cs[max(0, int(.2 * len(yy)) - 1)]),
                    "recall50": float(cs[len(yy) // 2 - 1]),
                    "review80": float((np.searchsorted(cs, .8) + 1) / len(yy)),
                }
        print(r, out[r + "_" + ("legacy" if r != "0903" else "random")], flush=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(args.out_dir / "pipeline-ranking.npz", X=X, y=y, recording=recs, ids=ids, role=role, **pred)
    (args.out_dir / "pipeline-evaluation.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
