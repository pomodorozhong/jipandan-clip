"""The application's Likely keep score as it was before the tied-rank correction, frozen here.

This is ``likely_keep_scores`` from ``src/jipandan/core/clip_features.py`` at ``9d55038^``, the
last commit before the correction of #125 (score version ``builtin-v1``). It ranks equal values
by input position, so tied clips get different scores. ``build_baseline.py`` uses it for the
"before" side of its comparison. The application's own function has carried the correction since
``9d55038`` and keeps changing with the application, so the experiment must not import it for
this: do not update this copy.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

# (field, higher is better), as the application had them at that commit.
SCORE_SIGNALS: tuple[tuple[str, bool], ...] = (
    ("peak_db", True),
    ("no_speech_prob", False),
    ("mid_share_db", True),
    ("bass_share_db", False),
)


def likely_keep_scores(rows: Sequence[object]) -> list[float | None]:
    """Return a 0–100 score per row: the mean percentile rank over available signals."""
    totals = np.zeros(len(rows))
    counts = np.zeros(len(rows))
    for name, higher_is_better in SCORE_SIGNALS:
        values = np.array([
            np.nan if (value := getattr(row, name, None)) is None else float(value)
            for row in rows
        ])
        present = np.flatnonzero(np.isfinite(values))
        if present.size < 2:
            continue
        signed = values[present] if higher_is_better else -values[present]
        ranks = signed.argsort(kind="stable").argsort()
        totals[present] += ranks / (present.size - 1)
        counts[present] += 1
    return [
        round(float(total / count) * 100, 1) if count else None
        for total, count in zip(totals, counts)
    ]
