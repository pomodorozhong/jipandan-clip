"""Validation for review-activity fields stored with each recording's events.

Clients report clip views, Publish preview waits, and the ranking context of their decisions; these
helpers keep only known fields with sane types and sizes before the store
records them for training the keep score.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {"keyboard", "gamepad", "pointer"}
STAGES = {"triage", "polish", "publish"}
# Why a view ended: another clip was selected, the stage changed, Settings or Help covered the clip,
# the page was hidden or lost focus, input stopped, or the round ended.
VIEW_END_REASONS = {"clip_change", "stage_change", "covered", "hidden", "blur", "idle", "round_end"}
# A Publish preview the viewer waited for: rendered, failed, or left before it was ready.
PREVIEW_KINDS = {"candidate", "reference"}
PREVIEW_OUTCOMES = {"ready", "failed", "cancelled"}
MAX_CLIENT_EVENTS = 200
MAX_DWELL_MS = 6 * 60 * 60 * 1000


def _short(value: object, limit: int = 40) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _int(value: object, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(min(high, max(low, value)))


def clean_context(raw: object) -> dict:
    """Keep only the known ranking-context fields, with sane types and sizes."""
    if not isinstance(raw, dict):
        return {}
    context: dict[str, object] = {}
    if raw.get("source") in SOURCES:
        context["source"] = raw["source"]
    if raw.get("stage") in STAGES:
        context["stage"] = raw["stage"]
    for key in ("order", "filter", "score_version", "review_set"):
        if (value := _short(raw.get(key))) is not None:
            context[key] = value
    if (number := _int(raw.get("round"), 1, 100_000)) is not None:
        context["round"] = number
    if (rank := _int(raw.get("rank"), 1, 1_000_000)) is not None:
        context["rank"] = rank
    score = raw.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
        context["score"] = round(float(score), 1)
    if isinstance(raw.get("explore"), bool):
        context["explore"] = raw["explore"]
    return context


def clean_client_event(raw: object, audio: Path) -> dict | None:
    """Validate an event reported by the browser: a clip view or a preview wait for the open audio.

    Each event carries the browser's ``id`` so a batch sent again after a lost reply is stored once.
    """
    if not isinstance(raw, dict) or raw.get("type") not in ("view", "preview_wait") or raw.get("audio") != str(audio):
        return None
    clip = _short(raw.get("clip"), 32)
    if clip is None:
        return None
    # Events are sent in batches, so keep when they started, not just when they were written.
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    started = _int(raw.get("started_at"), int(now_ms - 86_400_000), int(now_ms + 60_000))
    common = {
        "clip": clip,
        **({"id": event_id} if (event_id := _short(raw.get("id"), 64)) is not None else {}),
        **({"start": _iso(started / 1000)} if started is not None else {}),
    }
    if raw["type"] == "preview_wait":
        wait = _int(raw.get("wait_ms"), 0, MAX_DWELL_MS)
        if wait is None or raw.get("preview") not in PREVIEW_KINDS or raw.get("outcome") not in PREVIEW_OUTCOMES:
            return None
        return {"type": "preview_wait", **common, "wait_ms": wait, "preview": raw["preview"],
                "outcome": raw["outcome"], **clean_context(raw.get("context"))}
    dwell = _int(raw.get("dwell_ms"), 0, MAX_DWELL_MS)
    if dwell is None:
        return None
    return {
        "type": "view", **common, "dwell_ms": dwell,
        "plays": _int(raw.get("plays"), 0, 10_000) or 0,
        **({"autoplay": raw["autoplay"]} if isinstance(raw.get("autoplay"), bool) else {}),
        **({"ended_by": raw["ended_by"]} if raw.get("ended_by") in VIEW_END_REASONS else {}),
        **clean_context(raw.get("context")),
    }


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
