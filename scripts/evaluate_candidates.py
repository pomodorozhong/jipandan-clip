"""Score generated clip candidates and SRT lines against a reviewed recording's kept clips.

Uses the method agreed in #49: a candidate finds a kept clip when it covers at least 80% of
the kept clip's final bounds and both edges fall within an edge tolerance. Results are
reported at several tolerances: the share of kept clips found (recall), candidates per hour
of recording (review cost), and the median edge error a found clip still needs fixed.

Each ``--recording`` takes a name, the reviewed session (``.jipandan.db`` or a legacy
``.jipandan.json``), the SRT the session was made from, a Whisper transcription with word
timestamps as JSON (``{"segments": [{"start", "end", "words": [...]}]}``), and Silero speech
probabilities per 32 ms frame as a ``.npy`` file (see ``jipandan.core.vad``).

    uv run python scripts/evaluate_candidates.py \\
        --recording 0511 0511.jipandan.json 0511.srt 0511.words.json 0511.silero.npy

With ``--audio NAME AUDIO`` for a recording, it also reports start and end timing the way they
are judged (#47): a start fails when the export would begin later than it does for the kept clip,
cutting into the voice, while an early start only adds silence the export trims; an end fails only
when it is early.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jipandan.core import candidates as cand
from jipandan.core import ffmpeg, vad
from jipandan.core.srt import parse_srt, srt_time_to_seconds

KEPT = ("exported", "group1", "group2")
MIN_COVER = 0.8
TOLERANCES_S = (0.25, 0.5, 0.75, 1.0, 1.5)
# Timing report: how much later (start) or earlier (end) than the kept clip counts as cutting the voice.
CUT_S = 0.05
MIN_OVERLAP = 0.5
# The export's leading trim (``ffmpeg.build_silence_filter``): sound must stay above the threshold
# for start_duration, and start_silence of quiet is kept before it.
TRIM_DURATION_S = 0.1
TRIM_KEEP_S = 0.2
LEVEL_RATE = 100


@dataclass
class Recording:
    name: str
    hours: float
    kept: np.ndarray  # (n, 2) final start and end, in seconds
    sources: dict[str, np.ndarray]  # source name -> (m, 2) candidate start and end
    levels: np.ndarray | None = None  # 10 ms RMS levels in dBFS, for the timing report


def _seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def kept_clips(session: Path) -> np.ndarray:
    """Return the final (start, end) of every kept clip in a reviewed session."""
    if session.suffix == ".db":
        with sqlite3.connect(f"file:{session}?mode=ro", uri=True) as db:
            clips = [json.loads(data) for (data,) in db.execute("SELECT data FROM clip")]
    else:
        clips = json.loads(session.read_text(encoding="utf-8"))["candidates"]
    bounds = [
        (_seconds(clip["start"]), _seconds(clip["start"]) + float(clip["duration"]))
        for clip in clips if clip["status"] in KEPT
    ]
    return np.array(sorted(bounds), float).reshape(-1, 2)


def load_recording(
    name: str, session: Path, srt: Path, words_json: Path, probabilities: Path, **generator_options,
) -> Recording:
    segments = json.loads(words_json.read_text(encoding="utf-8"))["segments"]
    probs = np.load(probabilities).astype(np.float32)
    generated = cand.generate_candidates(
        segments, vad.speech_runs(probs, threshold=cand.SPEECH_THRESHOLD), **generator_options,
    )
    srt_lines = [(srt_time_to_seconds(e.start), srt_time_to_seconds(e.end)) for e in parse_srt(srt)]
    return Recording(
        name=name,
        hours=len(probs) * vad.FRAME_MS / 3_600_000,
        kept=kept_clips(session),
        sources={
            "SRT lines": np.array(srt_lines, float).reshape(-1, 2),
            "Whisper segments": np.array(
                [(float(s["start"]), float(s["end"])) for s in segments], float).reshape(-1, 2),
            "Generator": np.array(
                [(c.start_ms / 1000, c.end_ms / 1000) for c in generated], float).reshape(-1, 2),
        },
    )


def levels_db(audio: Path, chunk_frames: int = 60_000) -> np.ndarray:
    """Return 10 ms RMS levels of ``audio`` in dBFS, decoding in chunks to keep memory small."""
    frame = 8000 // LEVEL_RATE
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
        stdout=subprocess.PIPE,
    )
    parts = []
    while chunk := process.stdout.read(chunk_frames * frame * 4):
        samples = np.frombuffer(chunk, np.float32)
        samples = samples[: len(samples) // frame * frame].reshape(-1, frame)
        parts.append(20 * np.log10(np.maximum(np.sqrt((samples ** 2).mean(1)), 1e-6)))
    if process.wait():
        raise RuntimeError(f"ffmpeg could not decode {audio}")
    return np.concatenate(parts) if parts else np.zeros(0)


def exported_start(levels: np.ndarray, start: float) -> float:
    """Where the export's edge trim (default start threshold) begins a clip that starts at ``start``."""
    start = max(start, 0.0)
    index = round(start * LEVEL_RATE)
    loud = levels[index:index + 30 * LEVEL_RATE] > ffmpeg.DEFAULT_START_THRESHOLD_DB
    need = round(TRIM_DURATION_S * LEVEL_RATE)
    if len(loud) < need:
        return start
    runs = np.flatnonzero(np.convolve(loud, np.ones(need, int), "valid") >= need)
    return start if not len(runs) else max(start, (index + runs[0]) / LEVEL_RATE - TRIM_KEEP_S)


def timing(recording: Recording, source: str) -> dict:
    """Late exported starts and early ends of each kept clip's best-overlapping candidate."""
    candidates = recording.sources[source]
    late = early = matched = 0
    for start, end in recording.kept:
        overlap = np.minimum(candidates[:, 1], end) - np.maximum(candidates[:, 0], start)
        union = np.maximum(candidates[:, 1], end) - np.minimum(candidates[:, 0], start)
        best = int(np.argmax(overlap / union))
        if overlap[best] / union[best] < MIN_OVERLAP:
            continue
        matched += 1
        shift = exported_start(recording.levels, candidates[best, 0]) - exported_start(recording.levels, start)
        late += shift > CUT_S
        early += candidates[best, 1] < end - CUT_S
    return {"matched": matched / len(recording.kept), "late": late / max(matched, 1), "early": early / max(matched, 1)}


def match(kept: np.ndarray, candidates: np.ndarray, tolerance: float) -> np.ndarray:
    """Return each kept clip's best (start error, end error) among matching candidates, NaN if none."""
    best = np.full((len(kept), 2), np.nan)
    if not len(candidates):
        return best
    order = np.argsort(candidates[:, 0])
    candidates = candidates[order]
    for row, (start, end) in enumerate(kept):
        lo = np.searchsorted(candidates[:, 0], start - tolerance, "left")
        hi = np.searchsorted(candidates[:, 0], start + tolerance, "right")
        near = candidates[lo:hi]
        errors = np.abs(near - (start, end))
        cover = (np.minimum(near[:, 1], end) - np.maximum(near[:, 0], start)) / max(end - start, 1e-9)
        ok = (errors <= tolerance).all(1) & (cover >= MIN_COVER)
        if ok.any():
            best[row] = errors[ok][np.argmin(errors[ok].sum(1))]
    return best


def summarize(recordings: list[Recording], source: str, tolerance: float) -> dict:
    errors = np.concatenate([match(r.kept, r.sources[source], tolerance) for r in recordings])
    found = ~np.isnan(errors[:, 0])
    return {
        "recall": found.mean(),
        "per_hour": sum(len(r.sources[source]) for r in recordings) / sum(r.hours for r in recordings),
        "start_error": np.median(errors[found, 0]) if found.any() else np.nan,
        "end_error": np.median(errors[found, 1]) if found.any() else np.nan,
    }


def report(recordings: list[Recording]) -> str:
    sources = list(recordings[0].sources)
    lines = [
        "Kept clips: " + ", ".join(f"{r.name} {len(r.kept)} ({r.hours:.1f} h)" for r in recordings),
        "",
        "Recall, candidates per hour, and median start / end error of found clips (ms).",
        "",
        "| tolerance | " + " | ".join(sources) + " |",
        "|---" * (len(sources) + 1) + "|",
    ]
    for tolerance in TOLERANCES_S:
        cells = []
        for source in sources:
            s = summarize(recordings, source, tolerance)
            cells.append(
                f"{s['recall']:.0%}, {s['per_hour']:.0f}/h, "
                f"{s['start_error'] * 1000:.0f} / {s['end_error'] * 1000:.0f}"
            )
        lines.append(f"| {tolerance * 1000:.0f} ms | " + " | ".join(cells) + " |")
    if len(recordings) > 1:
        lines += ["", "Recall per recording:", ""]
        lines.append("| tolerance | source | " + " | ".join(r.name for r in recordings) + " |")
        lines.append("|---" * (len(recordings) + 2) + "|")
        for tolerance in TOLERANCES_S:
            for source in sources:
                lines.append(
                    f"| {tolerance * 1000:.0f} ms | {source} | "
                    + " | ".join(f"{summarize([r], source, tolerance)['recall']:.0%}" for r in recordings)
                    + " |"
                )
    timed = [r for r in recordings if r.levels is not None]
    if timed:
        lines += [
            "",
            "Timing of each kept clip's best-overlapping candidate (overlap ≥ 50% of the union): "
            "matched / exported start later than the kept clip's by more than 50 ms (cuts the voice) / "
            "end more than 50 ms early.",
            "",
            "| recording | " + " | ".join(sources) + " |",
            "|---" * (len(sources) + 1) + "|",
        ]
        for r in timed:
            cells = [timing(r, source) for source in sources]
            lines.append(f"| {r.name} | " + " | ".join(
                f"{c['matched']:.0%} / {c['late']:.0%} / {c['early']:.0%}" for c in cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--recording", nargs=5, action="append", required=True,
        metavar=("NAME", "SESSION", "SRT", "WORDS_JSON", "VAD_NPY"),
    )
    parser.add_argument(
        "--audio", nargs=2, action="append", default=[], metavar=("NAME", "AUDIO"),
        help="recording audio, to add the start and end timing report",
    )
    parser.add_argument("--min-length-ms", type=int, default=cand.MIN_LENGTH_MS)
    parser.add_argument("--max-length-ms", type=int, default=cand.MAX_LENGTH_MS)
    args = parser.parse_args()
    recordings = [
        load_recording(
            name, *map(Path, paths),
            min_length_ms=args.min_length_ms, max_length_ms=args.max_length_ms,
        )
        for name, *paths in args.recording
    ]
    audio = dict(args.audio)
    for recording in recordings:
        if recording.name in audio:
            recording.levels = levels_db(Path(audio[recording.name]))
    print(report(recordings))


if __name__ == "__main__":
    main()
