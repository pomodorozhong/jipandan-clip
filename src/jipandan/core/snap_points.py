"""Clip edge snap points: Whisper word starts and voice-activity speech ends."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

SNAP_POINTS_VERSION = 1
WORD_START = "word_start"
SPEECH_END = "speech_end"
KINDS = (WORD_START, SPEECH_END)


def snap_points_path(srt_path: Path) -> Path:
    """Sidecar holding the snap points computed while transcribing ``srt_path``."""
    return srt_path.with_suffix(".snap.json")


def word_starts_ms(segments: list[dict]) -> list[int]:
    """Return the sorted, distinct start of every word in Whisper ``segments``, in milliseconds."""
    starts: set[int] = set()
    for segment in segments:
        for word in segment.get("words") or []:
            try:
                start = float(word["start"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(start) and start >= 0:
                starts.add(round(start * 1000))
    return sorted(starts)


def write_snap_points(srt_path: Path, points: dict[str, list[int]]) -> None:
    """Save ``points`` by kind beside ``srt_path``, tied to its exact contents."""
    payload = {
        "version": SNAP_POINTS_VERSION,
        "srt_sha256": hashlib.sha256(srt_path.read_bytes()).hexdigest(),
        **{kind: sorted(set(points[kind])) for kind in KINDS if kind in points},
    }
    destination = snap_points_path(srt_path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent,
        prefix=f".{destination.name}.", suffix=".tmp", delete=False,
    ) as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, destination)


def load_snap_points(srt_path: Path, srt_fingerprint: str | None) -> dict[str, list[int]]:
    """Return snap points by kind when the sidecar matches this exact SRT, else {}."""
    try:
        data = json.loads(snap_points_path(srt_path).read_text(encoding="utf-8"))
        if data.get("version") != SNAP_POINTS_VERSION or data.get("srt_sha256") != srt_fingerprint:
            return {}
        return {kind: [int(ms) for ms in data[kind]] for kind in KINDS if kind in data}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
