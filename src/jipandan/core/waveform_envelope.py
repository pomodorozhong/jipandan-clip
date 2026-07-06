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


def decode_audio_slice_mono_f32(
    audio: Path,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Decode a slice of ``audio`` to mono float32 PCM via ffmpeg."""
    if duration_seconds <= 0:
        return np.zeros(0, dtype=np.float32)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-ss",
            f"{max(0.0, start_seconds):.3f}",
            "-i",
            str(audio),
            "-t",
            f"{duration_seconds:.3f}",
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


def padded_extract_range(
    visible_start: float,
    visible_end: float,
    source_duration: float,
) -> tuple[float, float]:
    """Return extract bounds with padding equal to the visible span on each side."""
    span = max(visible_end - visible_start, 1e-6)
    pad = span
    start = max(0.0, visible_start - pad)
    end = min(source_duration, visible_end + pad)
    return start, end


def extract_covers_visible(
    extract_start: float,
    extract_end: float,
    visible_start: float,
    visible_end: float,
) -> bool:
    """Return whether ``extract_*`` already has viewport-width padding around visible."""
    span = max(visible_end - visible_start, 1e-6)
    pad = span
    return (
        visible_start - pad >= extract_start - 1e-6
        and visible_end + pad <= extract_end + 1e-6
    )


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
