"""Review rounds: fixed batches of clips, each the top Likely keep clips not yet reviewed plus a random sample.

Reviewing only the top of the ranking would leave no labels on clips the score ranks low,
so a model retrained on them could not correct its own blind spots. Each round takes the
highest-scored clips of its pool (the clips no round has decided) and then a uniform sample
of the rest, drawn regardless of score: top clips were certain to be reviewed and every other
pool clip had the same recorded chance, so the review log can be reweighted to stand for the
pool (inverse propensity weighting). The random labels also estimate how many keepers the
stream holds. See doc/app-rebuild-plan.md, "Review rounds".
"""

from __future__ import annotations

import math
import random
import secrets
from collections.abc import Iterable, Sequence
from datetime import datetime

from jipandan.core.stage_times import CHANGE_TYPES, STAGES, event_stage, stage_breakdown

DEFAULT_SIZE = 300
RANDOM_SHARE = 0.2
MIN_SIZE = 10
MAX_SIZE = 5000
TOP, RANDOM = "top", "random"
# How rounds are picked. 1 (rounds without a ``sampling`` field): the random part was drawn from the
# whole pool first and the top part filled from what it left, so a top clip's chance depended on how
# many better clips the draw took. 2: the top part first, then a uniform sample of the rest (#104).
SAMPLING = 2
# Random labels wanted before refitting Likely keep's weights (about 4–5 rounds of 300 at 20%).
LABELS_TARGET = 250
# Seconds per clip, all stages together, until a round has been timed.
DEFAULT_SECONDS_PER_CLIP = 30
KEPT = frozenset({"group1", "group2", "exported"})
PROCESSED = frozenset({"exported", "rejected"})


def pick_round(
    pool: Sequence[tuple[str, int, float | None]], size: int, *, random_share: float = RANDOM_SHARE,
    seed: str | None = None,
) -> dict:
    """Pick a round from ``pool``, given as (clip_id, index, score) for every clip it may take.

    The top part is the highest scores in the pool (unscored clips last, ties by index); the random
    part is a uniform sample of the rest, each of which had ``random_chance`` of being drawn.
    Membership is kept by SRT index, so clips later split off a round clip belong to the round too.
    """
    seed = seed or secrets.token_hex(8)
    size = min(size, len(pool))
    random_count = round(size * random_share)
    ranked = sorted(
        range(len(pool)),
        key=lambda position: (pool[position][2] is None, -(pool[position][2] or 0.0), pool[position][1]),
    )
    top, rest = ranked[: size - random_count], ranked[size - random_count:]
    rng = random.Random(seed)
    sampled = [rest[position] for position in rng.sample(range(len(rest)), random_count)]
    return {
        "size": size, "pool": len(pool), "random_share": random_share, "seed": seed, "sampling": SAMPLING,
        "random_chance": random_count / len(rest) if rest else None,
        "top": [pool[position][0] for position in top],
        "random": [pool[position][0] for position in sampled],
        "roles": {
            **{str(pool[position][1]): TOP for position in top},
            **{str(pool[position][1]): RANDOM for position in sampled},
        },
        "completed": None,
    }


def pick_chance(item: dict, index: int) -> float | None:
    """The chance clip ``index`` had of joining round ``item``, given that it was in the round's pool.

    Known for rounds picked with sampling 2: 1 for top clips and the round's ``random_chance`` for
    random ones. Rounds picked before (sampling 1) saved too little to tell, so this is None.
    """
    if item.get("sampling") != SAMPLING:
        return None
    role = item["roles"].get(str(index))
    return 1.0 if role == TOP else item["random_chance"] if role == RANDOM else None


def from_review_set(review_set: dict, started: str | None) -> dict:
    """Read a session's review set from before rounds (#100) as its round 1, picked from every clip."""
    return {
        "number": 1, "size": review_set["size"], "pool": review_set["total"], "total": review_set["total"],
        "random_share": review_set["random_share"], "seed": review_set["seed"],
        "score_version": review_set.get("score_version"), "top": review_set["top"],
        "random": review_set["random"], "roles": review_set["roles"], "started": started,
        "completed": review_set["completed"],
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
    """Where a round clip sits in the round's shuffled order, as ``orderRound`` shows it on every screen."""
    return unit_hash(f"{seed}:order:{index}")


def unprocessed(roles: dict[str, str], clips: Sequence[tuple[int, str]]) -> int:
    """Count round clips, given as (index, status), that are not yet exported or rejected."""
    return sum(1 for index, status in clips if str(index) in roles and status not in PROCESSED)


def in_pool(rounds: Sequence[dict], clips: Sequence[tuple[int, str]]) -> set[int]:
    """SRT indexes a new round may take: every clip with the index still Unsorted, and not in the open round.

    A finished round's clips are all exported or rejected; clips a round ended early left Unsorted
    go back to the pool, since nobody reviewed them.
    """
    taken = {int(index) for item in rounds if not item.get("completed") for index in item["roles"]}
    decided = {index for index, status in clips if status != "pending"}
    return {index for index, _ in clips} - taken - decided


def closing_statuses(roles: dict[str, str], clips: Iterable[tuple[str, int, str]]) -> dict[str, str]:
    """The round's clips, given as (clip_id, index, status), as {clip_id: status} to save when it ends.

    A finished round reports what it found while it was open: a clip it left Unsorted and that is
    decided later, in another round or in free review, doesn't count toward it.
    """
    return {clip_id: status for clip_id, index, status in clips if str(index) in roles}


# What a round file's outcome stands for when its clip is still Unsorted here.
OUTCOME_STATUS = {"kept": "exported", "rejected": "rejected", "unfinished": "pending"}
# A clip here cut from part of a round file's decided clip: out of later rounds, but neither a keeper nor a label.
COVERED = "covered"


def round_statuses(item: dict, clips: Sequence[tuple[str, int, str, float | None]]) -> list[str]:
    """The statuses a round's summary counts: its saved clips, or for a round read from a file, the file's clips."""
    if item.get("file_clips") is not None:
        return [OUTCOME_STATUS[clip["outcome"]] for clip in item["file_clips"]]
    return [status for _, _, status in round_members(item, clips)]


def round_members(item: dict, clips: Sequence[tuple[str, int, str, float | None]]) -> list[tuple[str, int, str]]:
    """A round's clips as (clip_id, index, status): as they were when it ended, or as they are while it is open."""
    closed = item.get("closed_status")
    if item.get("completed") and closed is not None:
        return [(clip_id, int(clip_id.split("-")[0]), status) for clip_id, status in closed.items()]
    return [(clip_id, index, status) for clip_id, index, status, _ in clips if str(index) in item["roles"]]


def random_labels(rounds: Sequence[dict], clips: Sequence[tuple[str, int, str, float | None]]) -> list[tuple[float, bool]]:
    """One (score, kept) label per random clip decided in its round.

    A label stands for one random draw: a clip drawn again after a round left it Unsorted counts once,
    in the round that decided it, and clips later split from it add no labels of their own. It is kept
    when any part of it was kept, and scored as the clip was first cut.
    """
    scores: dict[int, float | None] = {}
    for clip_id, index, _, score in clips:
        if index not in scores or clip_id == str(index):
            scores[index] = score
    labels: dict[int, tuple[float, bool]] = {}
    from_files: list[tuple[float, bool]] = []
    for item in rounds:
        if item.get("file_clips") is not None:
            # A round read from a file: one label per random clip the other project decided, with its score there.
            from_files.extend((clip["score"], clip["outcome"] == "kept") for clip in item["file_clips"]
                              if clip["role"] == RANDOM and clip["outcome"] != "unfinished" and clip["score"] is not None)
            continue
        statuses: dict[int, list[str]] = {}
        for _, index, status in round_members(item, clips):
            statuses.setdefault(index, []).append(status)
        for key, role in item["roles"].items():
            index = int(key)
            decided = [status for status in statuses.get(index, []) if status != "pending"]
            if role != RANDOM or index in labels or not decided or scores.get(index) is None:
                continue
            labels[index] = (scores[index], any(status in KEPT for status in decided))
    return [*labels.values(), *from_files]


def keep_curve(samples: Sequence[tuple[float, bool]]) -> tuple[float, float] | None:
    """Fit P(kept | score) as a logistic curve on random clips' (score, kept) labels.

    Random clips were drawn regardless of score, so their decisions show how the keep rate
    changes with the score across the whole pool. A small ridge keeps the fit finite when every
    label agrees. Returns (intercept, slope) on score / 100, or None without labels.
    """
    if not samples:
        return None
    a = b = 0.0
    ridge = 0.1
    for _ in range(50):
        ga = gb = haa = hab = hbb = 0.0
        for score, kept in samples:
            x = score / 100
            p = 1 / (1 + math.exp(-(a + b * x)))
            ga += p - kept
            gb += (p - kept) * x
            w = p * (1 - p)
            haa += w
            hab += w * x
            hbb += w * x * x
        ga += ridge * a
        gb += ridge * b
        haa += ridge
        hbb += ridge
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        step_a = (hbb * ga - hab * gb) / det
        step_b = (haa * gb - hab * ga) / det
        a, b = a - step_a, b - step_b
        if abs(step_a) + abs(step_b) < 1e-9:
            break
    return a, b


def keep_chance(curve: tuple[float, float], score: float | None, fallback: float) -> float:
    if score is None:
        return fallback
    return 1 / (1 + math.exp(-(curve[0] + curve[1] * score / 100)))


def margin_points(labels: int) -> float | None:
    """How closely ``labels`` random decisions pin a keep rate: the 95% interval at 50%, in points."""
    return round(98 / math.sqrt(labels), 1) if labels else None


# Events a round's review stats count: clip views, and the changes and exports made to its clips.
STAT_EVENTS = ("view", "export", *sorted(CHANGE_TYPES))


def _ms(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp() * 1000


def round_events(item: dict, clip_index: dict[str, int], events: Iterable[dict]) -> list[dict]:
    """The views of and changes to a round's clips made while it was open; earlier ones are left out.

    A view that runs across the round's start or end counts only its part inside the round, so its
    ``dwell_ms`` is cut to that part.
    """
    started = item.get("started")
    ended = (item.get("completed") or {}).get("t")
    roles = item["roles"]
    if started is None:
        return []
    opened, closed = _ms(started), None if ended is None else _ms(ended)
    kept = []
    for event in events:
        index = clip_index.get(event.get("clip") or "")
        if index is None or str(index) not in roles:
            continue
        if event["type"] != "view":
            start = _ms(event.get("start", event["t"]))
            if start >= opened and (closed is None or start <= closed):
                kept.append(event)
            continue
        # A view without a start time was logged as it ended.
        start = _ms(event["start"]) if "start" in event else _ms(event["t"]) - event["dwell_ms"]
        end = start + event["dwell_ms"]
        inside = min(end, closed if closed is not None else end) - max(start, opened)
        if inside > 0:
            kept.append(event if inside >= event["dwell_ms"] else {**event, "dwell_ms": round(inside)})
    return kept


def clip_times(item: dict, clip_index: dict[str, int], events: Iterable[dict]) -> dict[str, dict[str, int]]:
    """Milliseconds per stage on each of a round's clips, by clip ID, while it was open; earlier views are left out."""
    times: dict[str, dict[str, int]] = {}
    for event in round_events(item, clip_index, events):
        if event["type"] != "view":
            continue
        stage = event_stage(event)
        if stage in STAGES:
            clip = times.setdefault(event["clip"], dict.fromkeys(STAGES, 0))
            clip[stage] += event["dwell_ms"]
    return times


def round_time(item: dict, clip_index: dict[str, int], events: Iterable[dict]) -> dict[str, int]:
    """Milliseconds spent per stage on a round's clips while it was open; a round read from a file brings its own."""
    if item.get("stage_ms") is not None:
        return dict(item["stage_ms"])
    totals = dict.fromkeys(STAGES, 0)
    for clip in clip_times(item, clip_index, events).values():
        for stage, ms in clip.items():
            totals[stage] += ms
    return totals


def effective_clips(
    rounds: Sequence[dict], clips: Sequence[tuple[str, int, str, float | None]],
) -> list[tuple[str, int, str, float | None]]:
    """Clips with the outcome a round file recorded standing in for Unsorted, so imported decisions count.

    Clips only covered by a file clip another clip here took the outcome of read as ``covered``.
    """
    outcomes = {int(index): COVERED for item in rounds for index in item.get("covered") or []}
    outcomes.update({int(index): OUTCOME_STATUS[outcome] for item in rounds
                     for index, outcome in (item.get("outcomes") or {}).items()})
    return [(clip_id, index, outcomes.get(index, status) if status == "pending" else status, score)
            for clip_id, index, status, score in clips]


def overview(
    rounds: Sequence[dict], clips: Sequence[tuple[str, int, str, float | None]], events: Sequence[dict],
    size: int, random_share: float,
) -> dict:
    """Summarize earlier rounds and estimate the next one.

    ``clips`` is every clip as (clip_id, index, status, score). The stream's keepers are the
    clips already kept plus, for every Unsorted clip, its chance of being kept from the keep
    curve; the next round adds the expected keepers among the clips it would pick.
    """
    clips = effective_clips(rounds, clips)
    clip_index = {clip_id: index for clip_id, index, _, _ in clips}
    labels = random_labels(rounds, clips)
    curve = keep_curve(labels)
    fallback = sum(kept for _, kept in labels) / len(labels) if labels else 0.0

    pending = [score for _, _, status, score in clips if status == "pending"]
    known = sum(1 for _, _, status, _ in clips if status in KEPT)
    stream = None
    if curve is not None:
        chances = [keep_chance(curve, score, fallback) for score in pending]
        expected = sum(chances)
        mean = expected / len(chances) if chances else 0.0
        spread = 1.96 * len(chances) * math.sqrt(mean * (1 - mean) / len(labels))
        stream = {"keepers": round(known + expected), "low": round(known + max(0.0, expected - spread)),
                  "high": round(known + min(len(chances), expected + spread))}

    def share_of_stream(count: int) -> float | None:
        return count / stream["keepers"] if stream and stream["keepers"] else None

    summaries = []
    for item in rounds:
        members = round_statuses(item, clips)
        kept = sum(status in KEPT for status in members)
        times = round_time(item, clip_index, events)
        # A round read from a file has no views or changes here to break down.
        stages = None if item.get("stage_ms") is not None else [
            row for row in stage_breakdown(round_events(item, clip_index, events))["stages"] if row["stage"] != "unknown"]
        summaries.append({
            "number": item["number"], "size": item["size"], "clips": len(members), "random_share": item["random_share"],
            "started": item.get("started"), "completed": item["completed"],
            "file": item.get("file"), "imported": item.get("imported"),
            "kept": kept, "processed": sum(status in PROCESSED for status in members),
            "decided": sum(status != "pending" for status in members),
            "time_ms": sum(times.values()), "stage_ms": times, "stages": stages, "captured": share_of_stream(kept),
        })

    # Pace per decided clip, so a round ended early doesn't look faster than it was.
    timed = [s for s in summaries if s["completed"] and s["time_ms"] and s["decided"]][-3:]
    if timed:
        clips_timed = sum(s["decided"] for s in timed)
        pace = {"source": "rounds", "rounds": [s["number"] for s in timed],
                "stage_ms": {stage: round(sum(s["stage_ms"][stage] for s in timed) / clips_timed) for stage in STAGES}}
        pace["ms"] = sum(pace["stage_ms"].values())
    else:
        pace = {"source": "default", "rounds": [], "stage_ms": None, "ms": DEFAULT_SECONDS_PER_CLIP * 1000}

    pool_indexes = in_pool(rounds, [(index, status) for _, index, status, _ in clips])
    pool = [score for _, index, _, score in clips if index in pool_indexes]
    next_size = min(size, len(pool))
    random_count = round(next_size * random_share)
    adds = None
    expected_keepers = None
    if curve is not None and next_size:
        chances = sorted((keep_chance(curve, score, fallback) for score in pool), reverse=True)
        top = chances[: next_size - random_count]
        rest = chances[next_size - random_count:]
        expected_keepers = sum(top) + (random_count * sum(rest) / len(rest) if rest else 0.0)
        adds = share_of_stream(round(expected_keepers))

    in_rounds = sum(s["kept"] for s in summaries)
    return {
        "rounds": summaries,
        "stream": stream,
        "captured": share_of_stream(in_rounds),
        "pace": pace,
        "pool": len(pool), "total": len(clips),
        "labels": {"so_far": len(labels), "target": LABELS_TARGET,
                   "margin": margin_points(len(labels)), "margin_after": margin_points(len(labels) + random_count)},
        "next": {
            "number": len(rounds) + 1, "size": next_size, "random_share": random_share, "random_count": random_count,
            "expected_keepers": round(expected_keepers) if expected_keepers is not None else None,
            "adds": adds, "ms": pace["ms"] * next_size,
        },
    }
