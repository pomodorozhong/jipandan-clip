"""Compare paired text/audio semantic scores using fixed recording-held-out rankers.

Requires scikit-learn. All model fits exclude the held recording; 0903 is never training
data. Sampling limits and repeated use of these historic recordings make this exploratory.
The three audio features are available in the current app, unlike legacy per-clip Whisper.

The two score files must be a true pair. Each is read with the ``.manifest.json`` the scorer
wrote beside it: one run text-only and one with audio, on this exact rows file, with the fixed
questions of ``omni-questions.json``, the same data type and the same pinned checkpoint, and with
the same token budget when both manifests record one (the original audio run predates that field). Every audio score must carry the
SHA-256 of the excerpt it heard, which is checked against the file at the row's ``audio_path``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

import frozen_inputs
from evaluate_semantic_ranking import metrics, paired_auc_ci


MODEL = "d1-Omni-2B"
SAME_IN_BOTH_RUNS = ("questions", "model_revision", "checkpoint_sha256", "custom_code_sha256", "dtype")


def load_scores(path, rows, audio=False):
    """Scores in row order. ``audio`` says which arm this is: the audio arm must have heard each
    row's current excerpt, and the text arm must not have heard anything."""
    raw = [json.loads(line) for line in path.read_text().splitlines()]
    by_id = {r["id"]: r for r in raw}
    if len(by_id) != len(raw) or set(by_id) != {r["id"] for r in rows}:
        raise ValueError("score ids do not exactly match inputs")
    for row in rows:
        score = by_id[row["id"]]
        if score["text_sha256"] != hashlib.sha256(row["text"].encode()).hexdigest():
            raise ValueError("text hash mismatch")
        if not audio:
            if "audio_sha256" in score:
                raise ValueError(f"text-only score for {row['id']} was made with audio")
            continue
        if not score.get("audio_sha256"):
            raise ValueError(f"audio score for {row['id']} has no audio hash")
        excerpt = Path(row.get("audio_path") or "")
        if not excerpt.is_file():
            raise ValueError(f"audio excerpt for {row['id']} is missing; its score cannot be checked")
        if score["audio_sha256"] != frozen_inputs.sha256(excerpt):
            raise ValueError(f"audio hash mismatch for {row['id']}: its excerpt changed after scoring")
    return np.array([[by_id[r["id"]]["scores"][k] for k in
                      ("reusable", "standalone", "expressive")] for r in rows])


def check_paired_runs(text_run: dict, audio_run: dict, rows_sha256: str, n_rows: int, pinned: dict,
                      questions: dict) -> None:
    """Reject score files that are not a text-only and a text-plus-audio run of one experiment."""
    if text_run.get("audio") is not False:
        raise ValueError("the text scores were not made by a text-only run")
    if audio_run.get("audio") is not True:
        raise ValueError("the audio scores were not made by a run with audio")
    for key in SAME_IN_BOTH_RUNS:
        if key not in text_run or key not in audio_run or text_run[key] != audio_run[key]:
            raise ValueError(f"the paired runs differ in {key}")
    if text_run["questions"] != questions:
        raise ValueError("the paired runs did not use the fixed questions of omni-questions.json")
    if "token_budget" in text_run and "token_budget" in audio_run and text_run["token_budget"] != audio_run["token_budget"]:
        raise ValueError("the paired runs differ in token_budget")
    for arm, run in (("text", text_run), ("audio", audio_run)):
        if run.get("input_sha256") != rows_sha256:
            raise ValueError(f"the {arm} run scored a different rows file")
        if run.get("rows") != n_rows:
            raise ValueError(f"the {arm} run scored {run.get('rows')} of {n_rows} rows")
        for key in ("revision", "checkpoint_sha256", "custom_code_sha256"):
            if run["model_revision" if key == "revision" else key] != pinned[key]:
                raise ValueError(f"the {arm} run did not use the pinned {MODEL} ({key})")


def manifest(scores: Path) -> dict:
    path = scores.with_suffix(".manifest.json")
    if not path.is_file():
        raise ValueError(f"{path.name} is missing: the run settings of {scores.name} cannot be checked")
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rows", type=Path, required=True)
    p.add_argument("--text-scores", type=Path, required=True)
    p.add_argument("--audio-scores", type=Path, required=True)
    p.add_argument("--pipeline-features", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model-revisions", type=Path,
                   default=Path(__file__).resolve().parents[1] / "model-revisions.json",
                   help="pinned model revisions and hashes (default: this experiment's)")
    p.add_argument("--questions", type=Path,
                   default=Path(__file__).resolve().parents[1] / "omni-questions.json",
                   help="the questions both runs must have used (default: this experiment's)")
    args = p.parse_args(argv)
    rows = json.loads(args.rows.read_text())
    check_paired_runs(manifest(args.text_scores), manifest(args.audio_scores), frozen_inputs.sha256(args.rows),
                      len(rows), json.loads(args.model_revisions.read_text())["models"][MODEL],
                      json.loads(args.questions.read_text()))
    text_scores = load_scores(args.text_scores, rows)
    audio_scores = load_scores(args.audio_scores, rows, audio=True)
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
