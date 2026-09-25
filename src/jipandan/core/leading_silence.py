"""Conservative detection of long leading gaps before clip speech."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from jipandan.core.waveform_envelope import decode_audio_slice_mono_f32

_SAMPLE_RATE = 8_000
_FRAME_MS = 20
_HOP_MS = 10
_MIN_LEADING_GAP_MS = 300
_SPEECH_PREROLL_MS = 120
_SUSTAINED_ACTIVITY_MS = 60
_MAX_SCAN_MS = 30_000


def detect_leading_silence_start(audio: Path, start_ms: int, end_ms: int) -> int | None:
    """Return a safer start before sustained audio activity, or ``None``.

    This is a conservative, noise-adaptive energy gate: it only proposes a
    change after a measurable quiet lead-in followed by sustained activity.
    The pre-roll helps retain soft consonants and breaths before louder speech.
    """
    scan_end_ms = min(end_ms, start_ms + _MAX_SCAN_MS)
    if scan_end_ms - start_ms <= _MIN_LEADING_GAP_MS:
        return None
    samples = decode_audio_slice_mono_f32(
        audio, start_ms / 1000, (scan_end_ms - start_ms) / 1000, sample_rate=_SAMPLE_RATE,
    )
    frame_samples = _SAMPLE_RATE * _FRAME_MS // 1000
    hop_samples = _SAMPLE_RATE * _HOP_MS // 1000
    if samples.size < frame_samples:
        return None

    windows = np.lib.stride_tricks.sliding_window_view(samples, frame_samples)[::hop_samples]
    rms = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
    db = 20.0 * np.log10(np.maximum(rms, 1e-6))

    # Estimate the local noise floor from the start of this SRT interval. The
    # clamp avoids treating quiet room noise as speech or demanding a loud voice.
    noise_sample_count = min(db.size, 1000 // _HOP_MS)
    noise_floor_db = float(np.percentile(db[:noise_sample_count], 30))
    threshold_db = max(-48.0, min(-26.0, noise_floor_db + 10.0))
    active = db >= threshold_db

    sustained_frames = max(1, _SUSTAINED_ACTIVITY_MS // _HOP_MS)
    active_runs = np.convolve(
        active.astype(np.int16), np.ones(sustained_frames, dtype=np.int16), mode="valid",
    )
    onset_frames = np.flatnonzero(active_runs == sustained_frames)
    if onset_frames.size == 0:
        return None

    onset_ms = int(onset_frames[0]) * _HOP_MS
    if onset_ms < _MIN_LEADING_GAP_MS:
        return None

    proposed = max(start_ms, start_ms + onset_ms - _SPEECH_PREROLL_MS)
    return proposed if end_ms - proposed >= 10 else None
