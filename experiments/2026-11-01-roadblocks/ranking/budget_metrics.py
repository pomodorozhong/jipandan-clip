"""AUC and review-budget metrics shared by every ranking evaluator of this experiment.

Review order within a score tie is unknown, so the budget metrics use the expected outcome
under a uniform random order inside each tie: every row of a tie counts as the tie's mean
label. Sorting alone would let the input row order decide which tied rows fall inside the
budget, and a constant score could look useful when the rows happen to be grouped by label.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score


def metrics(y, scores) -> dict[str, float]:
    """``auc`` (tie-aware), ``recall20`` and ``recall50`` (share of keepers found after reviewing
    the first 20% and 50% of rows) and ``review80`` (share of rows reviewed to find 80%)."""
    y, scores = np.asarray(y), np.asarray(scores)
    if len(y) != len(scores) or len(np.unique(y)) != 2 or not np.isfinite(scores).all():
        raise ValueError("metrics require aligned finite scores and both outcome classes")
    order = np.argsort(-scores, kind="stable")
    sorted_scores, expected = scores[order], y[order].astype(float)
    boundaries = np.r_[0, np.flatnonzero(np.diff(sorted_scores)) + 1, len(y)]
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        expected[a:b] = expected[a:b].mean()
    cumulative = expected.cumsum() / y.sum()
    return {"auc": float(roc_auc_score(y, scores)),
            "recall20": float(cumulative[max(0, int(.2 * len(y)) - 1)]),
            "recall50": float(cumulative[max(0, len(y) // 2 - 1)]),
            # The tolerance keeps a sum that reaches exactly 80% from rounding to just below it.
            "review80": float((np.searchsorted(cumulative, .8 - 1e-9) + 1) / len(y))}
