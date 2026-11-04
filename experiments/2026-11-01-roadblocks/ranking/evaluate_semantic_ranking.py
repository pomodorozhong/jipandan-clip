"""Evaluate fixed semantic scores with recording-held-out ranking baselines.

The legacy benchmark has unknown review propensities: treat its results as diagnostic.
The newer recording is a separate holdout; evaluate its random sample separately from top
selections. Never tune prompts, blend weights or model parameters on that holdout.
Requires scikit-learn and scipy in a disposable uv environment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

BLENDS = (0., .1, .25, .5, .75, 1.)


def metrics(y, scores):
    y, scores = np.asarray(y), np.asarray(scores)
    if len(y) != len(scores) or len(np.unique(y)) != 2 or not np.isfinite(scores).all():
        raise ValueError("metrics require aligned finite scores and both outcome classes")
    order = np.argsort(-scores, kind="stable")
    # Expected recall under a uniform ordering within score ties. Stable row order can
    # otherwise make a constant score look useful when the input is grouped by label.
    sorted_scores, expected = scores[order], y[order].astype(float)
    boundaries = np.r_[0, np.flatnonzero(np.diff(sorted_scores)) + 1, len(y)]
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        expected[a:b] = expected[a:b].mean()
    cumulative = expected.cumsum() / y.sum()
    return {"auc": float(roc_auc_score(y, scores)),
            "recall20": float(cumulative[max(0, int(.2 * len(y)) - 1)]),
            "recall50": float(cumulative[max(0, len(y) // 2 - 1)]),
            "review80": float((np.searchsorted(cumulative, .8) + 1) / len(y))}


def fit(X, y, train, test):
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=.05, max_leaf_nodes=15, l2_regularization=1.,
        class_weight="balanced", random_state=0,
    ).fit(X[train], y[train]).predict_proba(X[test])[:, 1]


def paired_auc_ci(y, baseline, candidate, iterations=2000):
    rng = np.random.default_rng(47)
    aucs, differences = [], []
    for _ in range(iterations):
        sample = rng.integers(0, len(y), len(y))
        yy = y[sample]
        if len(np.unique(yy)) < 2:
            continue
        a = roc_auc_score(yy, candidate[sample])
        aucs.append(a)
        differences.append(a - roc_auc_score(yy, baseline[sample]))
    return {"auc_ci95": np.quantile(aucs, [.025, .975]).tolist(),
            "delta_auc_ci95": np.quantile(differences, [.025, .975]).tolist()}


def choose_blend(y, rec, base, semantic, recordings):
    means = []
    for weight in BLENDS:
        means.append(np.mean([
            roc_auc_score(y[rec == r], (1 - weight) * base[rec == r]
                          + weight * semantic[rec == r]) for r in recordings
        ]))
    return BLENDS[int(np.argmax(means))]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rows", type=Path, required=True)
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--legacy-features", type=Path, required=True)
    p.add_argument("--pipeline-features", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    rows = json.loads(args.rows.read_text())
    scored_rows = [json.loads(line) for line in args.scores.read_text().splitlines()]
    scores = {r["id"]: r for r in scored_rows}
    if len({r["id"] for r in rows}) != len(rows) or len(scores) != len(scored_rows) or set(scores) != {r["id"] for r in rows}:
        raise ValueError("scores must match every unique input row exactly once")
    for row in rows:
        if scores[row["id"]]["text_sha256"] != hashlib.sha256(row["text"].encode()).hexdigest():
            raise ValueError("semantic scores do not match the input text")
    legacy = np.load(args.legacy_features)
    X, y, rec, ids = (legacy[k] for k in ("X", "y", "recording", "ids"))
    semantic = np.array([[scores[str(i)]["scores"][k] for k in ("reusable", "standalone", "expressive")] for i in ids])
    pred = {"baseline": legacy["fully_clean"], "semantic_reusable": semantic[:, 0],
            "semantic_mean": semantic.mean(1), "baseline_plus_semantics": np.zeros(len(y)),
            "nested_blend": np.zeros(len(y))}
    blend_weights = {}
    recordings = sorted(set(rec))
    for held in recordings:
        train = np.flatnonzero(rec != held)
        test = np.flatnonzero(rec == held)
        pred["baseline_plus_semantics"][test] = fit(np.c_[X, semantic], y, train, test)
        # Inner predictions never train on the outer held-out recording.
        inner = np.zeros(len(y))
        training_recordings = [r for r in recordings if r != held]
        for validation in training_recordings:
            tr = np.flatnonzero((rec != held) & (rec != validation))
            va = np.flatnonzero(rec == validation)
            inner[va] = fit(X, y, tr, va)
        weight = choose_blend(y, rec, inner, semantic[:, 0], training_recordings)
        blend_weights[str(held)] = weight
        pred["nested_blend"][test] = (1 - weight) * pred["baseline"][test] + weight * semantic[test, 0]
        print("legacy", held, "done", flush=True)
    result = {"legacy": {}, "nested_weights": blend_weights,
              "limitations": ["Legacy review propensities unknown; results are diagnostic.",
                              "Four legacy recordings do not establish generalization to new streams.",
                              "The generated holdout has one recording and only 60 random labels.",
                              "Whisper confidence from full transcriptions is unavailable in legacy word caches."]}
    for name, pp in pred.items():
        result["legacy"][name] = {str(r): metrics(y[rec == r], pp[rec == r]) for r in recordings}
        result["legacy"][name]["macro"] = {k: float(np.mean([result["legacy"][name][str(r)][k] for r in recordings])) for k in ("auc", "recall20", "recall50", "review80")}
    pipeline = np.load(args.pipeline_features)
    iy, ir, ip, roles = (pipeline[k] for k in ("y", "recording", "ids", "role"))
    sem = np.array([scores[str(i)]["scores"]["reusable"] for i in ip])
    baseline = np.nan_to_num(pipeline["builtin_available"], nan=.5)
    # Weight selection uses legacy recordings only, with no generated-session labels.
    weight = choose_blend(iy, ir, baseline, sem, recordings)
    result["generated_blend_weight_from_legacy"] = weight
    result["generated"] = {}
    generated = ir == "0903"
    for subset in ("random", "top"):
        mask = generated & (roles == subset)
        yy, bb, ss = iy[mask], baseline[mask], sem[mask]
        # Use the already-scaled score and probability, without fitting a transform on
        # this selected review sample. All 6,071 candidates would be needed for a new CDF.
        mixture = (1 - weight) * baseline[generated] + weight * sem[generated]
        selected = roles[generated] == subset
        result["generated"][subset] = {"n": int(mask.sum()), "kept": int(yy.sum()), "models": {}}
        for name, pp in {"builtin": bb, "semantic": ss, "legacy_selected_blend": mixture[selected]}.items():
            result["generated"][subset]["models"][name] = {**metrics(yy, pp), **paired_auc_ci(yy, bb, pp)}
    # Follow-up: a deployable feature comparison, without old per-clip Whisper decodes.
    # Same small GBM configuration as the audio-only pipeline audit; no parameter search.
    PX = pipeline["X"][:, [0, 2, 3]]
    PS = np.array([[scores[str(i)]["scores"][k] for k in
                    ("reusable", "standalone", "expressive")] for i in ip])
    result["production_features"] = {}
    for name, features in {"audio_only": PX, "audio_plus_semantics": np.c_[PX, PS]}.items():
        predictions = np.zeros(len(iy))
        for held in sorted(set(ir)):
            tr, te = (ir != held) & (ir != "0903"), ir == held
            model = HistGradientBoostingClassifier(
                max_iter=150, max_leaf_nodes=7, l2_regularization=5,
                class_weight="balanced", random_state=47,
            )
            predictions[te] = model.fit(features[tr], iy[tr]).predict_proba(features[te])[:, 1]
        entries = {str(r): metrics(iy[ir == r], predictions[ir == r]) for r in recordings}
        entries["legacy_macro"] = {k: float(np.mean([entries[str(r)][k] for r in recordings]))
                                   for k in ("auc", "recall20", "recall50", "review80")}
        for subset in ("random", "top"):
            mask = generated & (roles == subset)
            entries["generated_" + subset] = {
                **metrics(iy[mask], predictions[mask]),
                **paired_auc_ci(iy[mask], baseline[mask], predictions[mask]),
            }
        result["production_features"][name] = entries
    result["input_sha256"] = {key: hashlib.sha256(getattr(args, key).read_bytes()).hexdigest()
                               for key in ("rows", "scores", "legacy_features", "pipeline_features")}
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    np.savez(args.out.with_suffix(".predictions.npz"), y=y, recording=rec, ids=ids, **pred)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
