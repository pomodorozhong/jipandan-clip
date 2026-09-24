"""Bounded, reusable waveform windows for the browser editor."""

from __future__ import annotations

import subprocess
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from jipandan.core.waveform_envelope import build_envelope_from_audio_slice

MAX_WINDOW_MS = 120_000
MIN_BUCKETS = 64
MAX_BUCKETS = 1600
MAX_CACHED_WINDOWS = 64


class WaveformDecodeError(RuntimeError):
    """FFmpeg could not decode the requested part of the opened audio."""


class WaveformCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: OrderedDict[tuple, dict] = OrderedDict()

    def get(self, audio: Path, start_ms: int, end_ms: int, buckets: int) -> dict:
        """Decode only the requested viewport, keyed by source identity and resolution."""
        try:
            identity = audio.stat()
        except OSError as exc:
            raise WaveformDecodeError("Opened audio is unavailable") from exc
        key = (
            str(audio), identity.st_size, identity.st_mtime_ns,
            start_ms, end_ms, buckets,
        )
        with self._lock:
            cached = self._windows.get(key)
            if cached is not None:
                self._windows.move_to_end(key)
                return cached
            try:
                envelope = build_envelope_from_audio_slice(
                    audio, start_ms / 1000, (end_ms - start_ms) / 1000, buckets,
                )
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                raise WaveformDecodeError("Could not decode this waveform window") from exc
            result = {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "mins": np.nan_to_num(envelope.mins, nan=0, posinf=0, neginf=0).round(4).tolist(),
                "maxs": np.nan_to_num(envelope.maxs, nan=0, posinf=0, neginf=0).round(4).tolist(),
            }
            self._windows[key] = result
            if len(self._windows) > MAX_CACHED_WINDOWS:
                self._windows.popitem(last=False)
            return result
