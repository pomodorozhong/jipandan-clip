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
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jipandan.core import candidates as cand
from jipandan.core import vad
from jipandan.core.srt import parse_srt, srt_time_to_seconds

KEPT = ("exported", "group1", "group2")
MIN_COVER = 0.8
TOLERANCES_S = (0.25, 0.5, 0.75, 1.0, 1.5)


@dataclass
class Recording:
    name: str
    hours: float
    kept: np.ndarray  # (n, 2) final start and end, in seconds
    sources: dict[str, np.ndarray]  # source name -> (m, 2) candidate start and end


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
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--recording", nargs=5, action="append", required=True,
        metavar=("NAME", "SESSION", "SRT", "WORDS_JSON", "VAD_NPY"),
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
    print(report(recordings))


if __name__ == "__main__":
    main()
