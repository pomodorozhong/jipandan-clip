"""Per-clip audio features and the rank-based "likely keep" review score.

Kept clips tend to be close-mic speech: louder, with more 500–2000 Hz voice
energy and less 50–200 Hz game-audio bass, and with a low Whisper no-speech
probability. The score averages each clip's percentile rank on those signals
within one session, so it needs no trained model and adapts to each recording's
mic gain.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Bump when the measurements change, so stored values from older versions are not mixed in.
CLIP_FEATURES_VERSION = 1
# Identifies the ranking formula in the review log; bump when likely_keep_scores changes.
LIKELY_KEEP_VERSION = "builtin-v1"
SAMPLE_RATE = 8_000
_HOP = SAMPLE_RATE // 100  # 10 ms
_FFT = 256
_MAX_CLIP_SECONDS = 30.0
_READ_SAMPLES = SAMPLE_RATE * 60
_LOUD_FRAME_PERCENTILE = 60
_FREQUENCIES = np.fft.rfftfreq(_FFT, 1 / SAMPLE_RATE)
_WINDOW = np.hanning(_FFT)


@dataclass(frozen=True)
class ClipFeatures:
    peak_db: float
    mid_share_db: float | None
    bass_share_db: float | None


def features_from_samples(samples: np.ndarray) -> ClipFeatures | None:
    """Measure one clip's mono PCM at ``SAMPLE_RATE``."""
    if samples.size < _HOP:
        return None
    blocks = samples[: samples.size // _HOP * _HOP].astype(np.float64).reshape(-1, _HOP)
    peak_db = float(20 * np.log10(max(np.sqrt(np.mean(blocks**2, axis=1)).max(), 1e-6)))
    if samples.size < _FFT * 4:
        return ClipFeatures(peak_db, None, None)

    frames = np.lib.stride_tricks.sliding_window_view(samples.astype(np.float64), _FFT)[::_HOP]
    power = np.abs(np.fft.rfft(frames * _WINDOW, axis=1)) ** 2 + 1e-12
    frame_db = 10 * np.log10(power.sum(axis=1))
    # Use the loudest frames so the dominant source, not pauses, sets the tone.
    loud = power[frame_db >= np.percentile(frame_db, _LOUD_FRAME_PERCENTILE)].mean(axis=0)

    def band_db(low: float, high: float) -> float:
        return float(10 * np.log10(loud[(_FREQUENCIES >= low) & (_FREQUENCIES < high)].sum()))

    total_db = band_db(50, SAMPLE_RATE / 2 + 1)
    return ClipFeatures(peak_db, band_db(500, 2000) - total_db, band_db(50, 200) - total_db)


def compute_clip_features(
    audio: Path,
    spans: Sequence[tuple[float, float]],
    *,
    progress: Callable[[int], bool] | None = None,
) -> list[ClipFeatures | None]:
    """Measure each ``(start, end)`` span in seconds with one sequential decode.

    ``progress`` receives the number of finished spans and may return False to
    stop early; unfinished spans are then returned as None.
    """
    results: list[ClipFeatures | None] = [None] * len(spans)
    order = sorted(range(len(spans)), key=lambda position: spans[position][0])
    process = subprocess.Popen(
        ["ffmpeg", "-loglevel", "quiet", "-i", str(audio), "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    buffer = np.zeros(0, dtype=np.float32)
    buffer_start = 0
    exhausted = False
    try:
        for finished, position in enumerate(order, 1):
            start, end = spans[position]
            first = max(0, round(start * SAMPLE_RATE))
            last = max(first, round(min(end, start + _MAX_CLIP_SECONDS) * SAMPLE_RATE))
            while True:
                # Spans arrive in start order, so samples before this start are no longer needed.
                drop = min(buffer.size, first - buffer_start)
                if drop > 0:
                    buffer = buffer[drop:]
                    buffer_start += drop
                if exhausted or buffer_start + buffer.size >= last:
                    break
                # A buffered pipe read returns the full size until end of stream.
                chunk = process.stdout.read(_READ_SAMPLES * 4)
                if not chunk:
                    exhausted = True
                    continue
                buffer = np.concatenate([buffer, np.frombuffer(chunk[: len(chunk) // 4 * 4], np.float32)])
            results[position] = features_from_samples(
                buffer[first - buffer_start:last - buffer_start]
            )
            if progress is not None and progress(finished) is False:
                break
    finally:
        process.stdout.close()
        process.kill()
        process.wait()
    return results


# (field name, True when a higher value suggests a keep)
SCORE_SIGNALS: tuple[tuple[str, bool], ...] = (
    ("peak_db", True),
    ("no_speech_prob", False),
    ("mid_share_db", True),
    ("bass_share_db", False),
)


def likely_keep_scores(rows: Sequence[object]) -> list[float | None]:
    """Return a 0–100 score per row: the mean percentile rank over available signals."""
    totals = np.zeros(len(rows))
    counts = np.zeros(len(rows))
    for name, higher_is_better in SCORE_SIGNALS:
        values = np.array([
            np.nan if (value := getattr(row, name, None)) is None else float(value)
            for row in rows
        ])
        present = np.flatnonzero(np.isfinite(values))
        if present.size < 2:
            continue
        signed = values[present] if higher_is_better else -values[present]
        ranks = signed.argsort(kind="stable").argsort()
        totals[present] += ranks / (present.size - 1)
        counts[present] += 1
    return [
        round(float(total / count) * 100, 1) if count else None
        for total, count in zip(totals, counts)
    ]
