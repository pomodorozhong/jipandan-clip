"""Decode audio to min/max envelope arrays for textual-plot rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from jipandan.core import ffmpeg

_DEFAULT_SAMPLE_RATE = 8000
_DEFAULT_BUCKETS = 800


def decode_mp3_mono_f32(
    mp3: Path,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Decode ``mp3`` to mono float32 PCM via ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(mp3),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def downsample_envelope(
    samples: np.ndarray,
    duration: float,
    buckets: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-bucket min/max envelope mimicking showwavespic columns."""
    if buckets <= 0:
        raise ValueError("buckets must be positive")
    if duration <= 0:
        times = np.zeros(0, dtype=np.float64)
        empty = np.zeros(0, dtype=np.float64)
        return times, empty, empty
    if samples.size == 0:
        times = np.linspace(0.0, duration, buckets, endpoint=False)
        zeros = np.zeros(buckets, dtype=np.float64)
        return times, zeros, zeros

    bucket_size = max(1, int(np.ceil(samples.size / buckets)))
    mins: list[float] = []
    maxs: list[float] = []
    for start in range(0, samples.size, bucket_size):
        chunk = samples[start : start + bucket_size]
        mins.append(float(chunk.min()))
        maxs.append(float(chunk.max()))

    count = len(mins)
    times = (np.arange(count, dtype=np.float64) + 0.5) * duration / count
    return times, np.asarray(mins, dtype=np.float64), np.asarray(maxs, dtype=np.float64)


def load_waveform_envelope(
    mp3: Path,
    *,
    buckets: int = _DEFAULT_BUCKETS,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load ``mp3`` and return ``(times, mins, maxs)`` in seconds/amplitude."""
    duration = ffmpeg.probe_duration_seconds(mp3)
    samples = decode_mp3_mono_f32(mp3, sample_rate=sample_rate)
    return downsample_envelope(samples, duration, buckets)
