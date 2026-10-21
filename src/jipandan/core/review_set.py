"""Pick a fixed review set: the top Likely keep clips plus a random sample of all clips.

Reviewing only the top of the ranking would leave no labels on clips the score ranks low,
so a model retrained on them could not correct its own blind spots. The random part is a
uniform sample of every candidate, drawn regardless of score: each clip outside the top part
had a known chance of being reviewed, so the review log can be reweighted to stand for the
whole recording (inverse propensity weighting). See doc/app-rebuild-plan.md, "Review sets".
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence

DEFAULT_SIZE = 300
RANDOM_SHARE = 0.2
MIN_SIZE = 10
MAX_SIZE = 5000
TOP, RANDOM = "top", "random"


def pick_review_set(
    clips: Sequence[tuple[str, int, float | None]], size: int, *, random_share: float = RANDOM_SHARE,
    seed: str | None = None,
) -> dict:
    """Return the set for ``clips`` given as (clip_id, index, score).

    The random part is drawn first from every clip; the top part is filled with the highest
    scores among the rest. Membership is kept by SRT index, so clips later split off a set
    clip belong to the set too.
    """
    seed = seed or secrets.token_hex(8)
    size = min(size, len(clips))
    random_count = round(size * random_share)
    rng = random.Random(seed)
    sampled = rng.sample(range(len(clips)), random_count)
    picked = set(sampled)
    rest = sorted(
        (position for position in range(len(clips)) if position not in picked),
        key=lambda position: (clips[position][2] is None, -(clips[position][2] or 0.0), clips[position][1]),
    )
    top = rest[: size - random_count]
    return {
        "size": size, "total": len(clips), "random_share": random_share, "seed": seed,
        "top": [clips[position][0] for position in top],
        "random": [clips[position][0] for position in sampled],
        "roles": {
            **{str(clips[position][1]): TOP for position in top},
            **{str(clips[position][1]): RANDOM for position in sampled},
        },
        "completed": None,
    }


def unit_hash(text: str) -> float:
    """Map ``text`` to [0, 1) exactly like ``unitHash`` in frontend/src/reviewOrder.ts."""
    value = 0x811C9DC5
    data = text.encode("utf-16-le")
    for position in range(0, len(data), 2):
        value ^= data[position] | data[position + 1] << 8
        value = (value * 0x01000193) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x85EBCA6B) & 0xFFFFFFFF
    value ^= value >> 13
    value = (value * 0xC2B2AE35) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0x1_0000_0000


def set_order_key(seed: str, index: int) -> float:
    """Where a set clip sits in the set's shuffled order, as ``orderReviewSet`` shows it on every screen."""
    return unit_hash(f"{seed}:order:{index}")


def unprocessed(roles: dict[str, str], clips: Sequence[tuple[int, str]]) -> int:
    """Count set clips, given as (index, status), that are not yet exported or rejected."""
    return sum(1 for index, status in clips if str(index) in roles and status not in {"exported", "rejected"})
