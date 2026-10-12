"""Append-only record of review activity, kept beside each session.

The session file holds the current state of every clip. This log keeps the
history that training the keep score needs: which clips were actually looked
at, how each decision was made, and where the clip sat in the ranking at the
time. Writing to it must never break editing, so failures are only logged.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_VERSION = 1
SOURCES = {"keyboard", "gamepad", "pointer"}
MAX_CLIENT_EVENTS = 200
MAX_DWELL_MS = 6 * 60 * 60 * 1000


def log_path(audio: Path) -> Path:
    return audio.with_suffix(".review-log.jsonl")


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
    return {
        "type": "view", "clip": clip, "dwell_ms": dwell,
        "plays": _int(raw.get("plays"), 0, 10_000) or 0,
        **clean_context(raw.get("context")),
    }


class ReviewLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def append(self, audio: Path | None, events: list[dict]) -> None:
        if audio is None or not events:
            return
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        lines = "".join(
            json.dumps({"v": LOG_VERSION, "t": stamp, **event}, ensure_ascii=False) + "\n" for event in events
        )
        try:
            with self._lock, log_path(audio).open("a", encoding="utf-8") as handle:
                handle.write(lines)
        except OSError:
            logger.exception("Could not write review log for %s", audio)
