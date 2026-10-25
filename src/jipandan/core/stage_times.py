"""Break a session's review time down by stage (Triage, Polish, Publish) from its event log.

Time is the sum of clip views: how long each clip was on screen while the app had focus and
input, so idle stretches and time outside review are left out. A view's stage is the ``stage``
the browser recorded with it, or for views from before stages were recorded, its ``filter``;
changes are attributed the same way, and exports always belong to Publish.
"""

from __future__ import annotations

STAGES = ("triage", "polish", "publish")
# Change events that record the stage they were made in.
CHANGE_TYPES = {"status", "title", "trim", "duplicate", "bulk-reject"}


def event_stage(event: dict) -> str | None:
    """Return the stage an event was recorded in, or None for events from before stages were logged."""
    if event["type"] == "export":
        return "publish"
    if event.get("stage") in STAGES:
        return event["stage"]
    stage = event.get("filter")
    if stage in ("triage", "publish"):
        return stage
    # Polish records its status filter (Unsorted, Group 1, ...) instead of its name.
    return "polish" if isinstance(stage, str) else None


def stage_breakdown(events: list[dict]) -> dict:
    """Sum view time, clips viewed, and changes per stage."""
    totals = {stage: {"ms": 0, "views": 0, "clips": set(), "changes": 0} for stage in (*STAGES, "unknown")}
    first, last = None, None
    for event in events:
        if event["type"] == "view":
            row = totals[event_stage(event) or "unknown"]
            row["ms"] += event["dwell_ms"]
            row["views"] += 1
            row["clips"].add(event["clip"])
            start = event.get("start", event["t"])
            first = start if first is None or start < first else first
            last = event["t"] if last is None or event["t"] > last else last
        elif event["type"] in CHANGE_TYPES or event["type"] == "export":
            totals[event_stage(event) or "unknown"]["changes"] += 1
    stages = [
        {"stage": stage, "ms": row["ms"], "views": row["views"], "clips": len(row["clips"]),
         "changes": row["changes"]}
        for stage, row in totals.items() if stage != "unknown" or row["views"] or row["changes"]
    ]
    return {"stages": stages, "total_ms": sum(row["ms"] for row in stages), "first_view": first, "last_view": last}
