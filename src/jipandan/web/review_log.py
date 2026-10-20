"""Validation for review-activity fields stored with each recording's events.

Clients report clip views and the ranking context of their decisions; these
helpers keep only known fields with sane types and sizes before the store
records them for training the keep score.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {"keyboard", "gamepad", "pointer"}
# Why a view ended: another clip was selected, the page was hidden or lost focus, or input stopped.
VIEW_END_REASONS = {"clip_change", "hidden", "blur", "idle"}
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
    for key in ("order", "filter", "score_version"):
        if (value := _short(raw.get(key))) is not None:
            context[key] = value
    if (rank := _int(raw.get("rank"), 1, 1_000_000)) is not None:
        context["rank"] = rank
    score = raw.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
        context["score"] = round(float(score), 1)
    if isinstance(raw.get("explore"), bool):
        context["explore"] = raw["explore"]
    return context


def clean_client_event(raw: object, audio: Path) -> dict | None:
    """Validate an event reported by the browser; only clip views of the open audio are accepted."""
    if not isinstance(raw, dict) or raw.get("type") != "view" or raw.get("audio") != str(audio):
        return None
    clip = _short(raw.get("clip"), 32)
    dwell = _int(raw.get("dwell_ms"), 0, MAX_DWELL_MS)
    if clip is None or dwell is None:
        return None
    # Views are sent in batches, so keep when the view started, not just when it was written.
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    started = _int(raw.get("started_at"), int(now_ms - 86_400_000), int(now_ms + 60_000))
    return {
        "type": "view", "clip": clip, "dwell_ms": dwell,
        **({"start": _iso(started / 1000)} if started is not None else {}),
        "plays": _int(raw.get("plays"), 0, 10_000) or 0,
        **({"autoplay": raw["autoplay"]} if isinstance(raw.get("autoplay"), bool) else {}),
        **({"ended_by": raw["ended_by"]} if raw.get("ended_by") in VIEW_END_REASONS else {}),
        **clean_context(raw.get("context")),
    }


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
