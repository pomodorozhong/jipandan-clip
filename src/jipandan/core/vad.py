"""Silero voice activity detection through ONNX Runtime, for clip edge snap points."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from jipandan.core.paths import get_app_paths

# Silero VAD v6.2.3, the version the 2026-10-16 snap-point experiment used (#58).
MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/"
    "v6.2.3/src/silero_vad/data/silero_vad.onnx"
)
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
CONTEXT_SAMPLES = 64
FRAME_MS = FRAME_SAMPLES * 1000 / SAMPLE_RATE
# Audio is cut into chunks that run as one batch, each starting from a fresh state.
CHUNK_SAMPLES = SAMPLE_RATE * 600

THRESHOLD = 0.5
MIN_GAP_MS = 100
MIN_RUN_MS = 100


def model_path() -> Path:
    """Return the cached Silero model, downloading and verifying it on first use."""
    destination = get_app_paths().cache_dir / "models" / f"silero_vad-{MODEL_SHA256[:12]}.onnx"
    if destination.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError(f"Silero VAD model checksum mismatch: {digest}")
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as handle:
        handle.write(data)
    os.replace(handle.name, destination)
    return destination


def decode_audio(audio: Path) -> np.ndarray:
    """Decode ``audio`` to 16 kHz mono float32 samples."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(result.stdout, np.float32)


def speech_probabilities(samples: np.ndarray, model: Path | None = None) -> np.ndarray:
    """Return Silero's speech probability for each 32 ms frame of 16 kHz ``samples``."""
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 4
    session = onnxruntime.InferenceSession(
        str(model or model_path()), options, providers=["CPUExecutionProvider"],
    )
    frames = -(-len(samples) // FRAME_SAMPLES)
    if frames == 0:
        return np.zeros(0, np.float32)
    chunk_frames = CHUNK_SAMPLES // FRAME_SAMPLES
    chunks = -(-frames // chunk_frames)
    padded = np.zeros(chunks * chunk_frames * FRAME_SAMPLES, np.float32)
    padded[:len(samples)] = samples
    batch = padded.reshape(chunks, chunk_frames, FRAME_SAMPLES)

    state = np.zeros((2, chunks, 128), np.float32)
    context = np.zeros((chunks, CONTEXT_SAMPLES), np.float32)
    rate = np.array(SAMPLE_RATE, np.int64)
    probabilities = np.empty((chunks, chunk_frames), np.float32)
    for index in range(chunk_frames):
        frame = batch[:, index]
        output, state = session.run(
            None, {"input": np.concatenate([context, frame], axis=1), "state": state, "sr": rate},
        )
        probabilities[:, index] = output[:, 0]
        context = frame[:, -CONTEXT_SAMPLES:]
    return probabilities.reshape(-1)[:frames]


def speech_runs(
    probabilities: np.ndarray,
    threshold: float = THRESHOLD,
    min_gap_ms: float = MIN_GAP_MS,
    min_run_ms: float = MIN_RUN_MS,
) -> list[tuple[int, int]]:
    """Return (start_ms, end_ms) speech runs, merging short gaps and dropping short runs."""
    edges = np.diff(np.r_[0, (probabilities > threshold).astype(np.int8), 0])
    runs: list[list[int]] = []
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if runs and (start - runs[-1][1]) * FRAME_MS < min_gap_ms:
            runs[-1][1] = int(end)
        else:
            runs.append([int(start), int(end)])
    return [
        (round(start * FRAME_MS), round(end * FRAME_MS))
        for start, end in runs if (end - start) * FRAME_MS >= min_run_ms
    ]


def speech_ends_ms(audio: Path) -> list[int]:
    """Return the end of every speech run in ``audio``, in milliseconds."""
    return [end for _, end in speech_runs(speech_probabilities(decode_audio(audio)))]
