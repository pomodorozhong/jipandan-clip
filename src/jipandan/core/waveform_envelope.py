"""Decode audio to min/max envelope arrays for textual-plot rendering."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jipandan.core import ffmpeg

_DEFAULT_SAMPLE_RATE = 8000
_DEFAULT_BUCKETS = 800
WAVEFORM_ENVELOPE_SUFFIX = ".wenv.npz"
MAX_ENVELOPE_CACHE_BUCKETS = 4096


@dataclass(frozen=True)
class WaveformEnvelopeCache:
    times: np.ndarray
    mins: np.ndarray
    maxs: np.ndarray
    duration: float
    buckets: int


def is_waveform_envelope_cache(path: Path) -> bool:
    return path.suffixes == [".wenv", ".npz"] or path.name.endswith(WAVEFORM_ENVELOPE_SUFFIX)


def save_envelope_cache(
    path: Path,
    *,
    times: np.ndarray,
    mins: np.ndarray,
    maxs: np.ndarray,
    duration: float,
    buckets: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        times=times,
        mins=mins,
        maxs=maxs,
        duration=np.float64(duration),
        buckets=np.int32(buckets),
    )


def load_envelope_cache(path: Path) -> WaveformEnvelopeCache:
    with np.load(path, allow_pickle=False) as data:
        return WaveformEnvelopeCache(
            times=data["times"],
            mins=data["mins"],
            maxs=data["maxs"],
            duration=float(data["duration"]),
            buckets=int(data["buckets"]),
        )


def resample_envelope_to_buckets(
    times: np.ndarray,
    mins: np.ndarray,
    maxs: np.ndarray,
    duration: float,
    target_buckets: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Merge cached buckets down to ``target_buckets`` (never upsamples)."""
    if target_buckets <= 0:
        raise ValueError("target_buckets must be positive")
    source_buckets = len(mins)
    if source_buckets <= target_buckets:
        return times, mins, maxs

    ratio = source_buckets / target_buckets
    new_mins: list[float] = []
    new_maxs: list[float] = []
    for index in range(target_buckets):
        start_idx = int(index * ratio)
        end_idx = max(start_idx + 1, int((index + 1) * ratio))
        new_mins.append(float(mins[start_idx:end_idx].min()))
        new_maxs.append(float(maxs[start_idx:end_idx].max()))

    count = len(new_mins)
    new_times = (np.arange(count, dtype=np.float64) + 0.5) * duration / count
    return new_times, np.asarray(new_mins, dtype=np.float64), np.asarray(new_maxs, dtype=np.float64)


def build_envelope_from_audio_slice(
    audio: Path,
    start_seconds: float,
    duration_seconds: float,
    buckets: int,
    *,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> WaveformEnvelopeCache:
    samples = decode_audio_slice_mono_f32(
        audio, start_seconds, duration_seconds, sample_rate=sample_rate
    )
    times, mins, maxs = downsample_envelope(samples, duration_seconds, buckets)
    return WaveformEnvelopeCache(
        times=times,
        mins=mins,
        maxs=maxs,
        duration=duration_seconds,
        buckets=len(mins),
    )


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


def envelope_from_mp3(
    mp3: Path,
    *,
    buckets: int = _DEFAULT_BUCKETS,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode ``mp3`` and return ``(times, mins, maxs)`` in seconds/amplitude."""
    duration = ffmpeg.probe_duration_seconds(mp3)
    samples = decode_mp3_mono_f32(mp3, sample_rate=sample_rate)
    return downsample_envelope(samples, duration, buckets)
