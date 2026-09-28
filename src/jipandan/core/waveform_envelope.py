"""Decode audio slices to min/max envelopes for browser waveforms."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_DEFAULT_SAMPLE_RATE = 8000


@dataclass(frozen=True)
class WaveformEnvelopeCache:
    times: np.ndarray
    mins: np.ndarray
    maxs: np.ndarray
    duration: float
    buckets: int


def build_envelope_from_audio_slice(
    audio: Path,
    start_seconds: float,
    duration_seconds: float,
    buckets: int,
    *,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
    accurate: bool = True,
) -> WaveformEnvelopeCache:
    samples = decode_audio_slice_mono_f32(
        audio,
        start_seconds,
        duration_seconds,
        sample_rate=sample_rate,
        accurate=accurate,
    )
    actual_duration = samples_duration_seconds(samples.size, sample_rate)
    if actual_duration <= 0:
        actual_duration = duration_seconds
    times, mins, maxs = downsample_envelope(samples, actual_duration, buckets)
    return WaveformEnvelopeCache(
        times=times,
        mins=mins,
        maxs=maxs,
        duration=actual_duration,
        buckets=len(mins),
    )


def decode_audio_slice_mono_f32(
    audio: Path,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
    *,
    accurate: bool = True,
) -> np.ndarray:
    """Decode a slice of ``audio`` to mono float32 PCM via ffmpeg."""
    if duration_seconds <= 0:
        return np.zeros(0, dtype=np.float32)

    start_seconds = max(0.0, start_seconds)
    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "quiet"]

    if start_seconds > 0.0:
        if accurate:
            preroll = min(start_seconds, 2.0)
            cmd.extend(["-ss", f"{start_seconds - preroll:.6f}"])
        else:
            cmd.extend(["-ss", f"{start_seconds:.3f}"])

    cmd.extend(["-i", str(audio)])

    if start_seconds > 0.0 and accurate:
        preroll = min(start_seconds, 2.0)
        cmd.extend(["-ss", f"{preroll:.6f}"])

    cmd.extend(
        [
            "-t",
            f"{duration_seconds:.6f}",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def samples_duration_seconds(
    sample_count: int, sample_rate: int = _DEFAULT_SAMPLE_RATE
) -> float:
    if sample_count <= 0:
        return 0.0
    return sample_count / sample_rate


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
