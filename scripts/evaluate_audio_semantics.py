"""Compare paired text/audio semantic scores using fixed recording-held-out rankers.

Requires scikit-learn. All model fits exclude the held recording; 0903 is never training
data. Sampling limits and repeated use of these historic recordings make this exploratory.
The three audio features are available in the current app, unlike legacy per-clip Whisper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from evaluate_semantic_ranking import metrics, paired_auc_ci


def load_scores(path, rows):
    raw = [json.loads(line) for line in path.read_text().splitlines()]
    by_id = {r["id"]: r for r in raw}
    if len(by_id) != len(raw) or set(by_id) != {r["id"] for r in rows}:
        raise ValueError("score ids do not exactly match inputs")
    for row in rows:
        if by_id[row["id"]]["text_sha256"] != hashlib.sha256(row["text"].encode()).hexdigest():
            raise ValueError("text hash mismatch")
    return np.array([[by_id[r["id"]]["scores"][k] for k in
                      ("reusable", "standalone", "expressive")] for r in rows])


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rows", type=Path, required=True)
    p.add_argument("--text-scores", type=Path, required=True)
    p.add_argument("--audio-scores", type=Path, required=True)
    p.add_argument("--pipeline-features", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    rows = json.loads(args.rows.read_text())
    text_scores, audio_scores = load_scores(args.text_scores, rows), load_scores(args.audio_scores, rows)
    data = np.load(args.pipeline_features)
    lookup = {str(x): i for i, x in enumerate(data["ids"])}
    indices = np.array([lookup[r["id"]] for r in rows])
    X = data["X"][indices][:, [0, 2, 3]]
    y, rec, role = (data[k][indices] for k in ("y", "recording", "role"))
    pred = {"builtin": data["builtin_available"][indices],
            "text_reusable": text_scores[:, 0], "audio_reusable": audio_scores[:, 0]}
    features = {"audio_features": X, "features_plus_text": np.c_[X, text_scores],
                "features_plus_audio": np.c_[X, audio_scores]}
    for name in features:
        pred[name] = np.zeros(len(rows))
    for recording in sorted(set(rec)):
        train, test = (rec != recording) & (rec != "0903"), rec == recording
        for name, featureset in features.items():
            model = HistGradientBoostingClassifier(
                max_iter=150, max_leaf_nodes=7, l2_regularization=5,
                class_weight="balanced", random_state=47,
            )
            pred[name][test] = model.fit(featureset[train], y[train]).predict_proba(featureset[test])[:, 1]
    result = {"legacy": {}, "generated": {}}
    for recording in sorted(set(rec)):
        for subset in (["random", "top"] if recording == "0903" else ["legacy"]):
            mask = (rec == recording) & (role == subset)
            target = result["generated" if recording == "0903" else "legacy"]
            target[subset if recording == "0903" else recording] = {
                "n": int(mask.sum()), "kept": int(y[mask].sum()), "models": {
                    name: metrics(y[mask], scores[mask]) for name, scores in pred.items()
                },
            }
            if recording == "0903":
                for name in pred:
                    target[subset]["models"][name].update(paired_auc_ci(y[mask], pred["builtin"][mask], pred[name][mask]))
                target[subset]["paired_audio_minus_text"] = paired_auc_ci(
                    y[mask], pred["text_reusable"][mask], pred["audio_reusable"][mask])
    result["legacy_macro"] = {name: {
        metric: float(np.mean([r["models"][name][metric] for r in result["legacy"].values()]))
        for metric in ("auc", "recall20", "recall50", "review80")
    } for name in pred}
    result["input_sha256"] = {key: hashlib.sha256(getattr(args, key).read_bytes()).hexdigest()
                               for key in ("rows", "text_scores", "audio_scores", "pipeline_features")}
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
