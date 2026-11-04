"""Candidate-generation variants that were tried on top of the audit's generator: extending a
clip's end into the next speech run, adding bursts of low-VAD energy, and suppressing
near-duplicate candidates.

Each variant is a diagnostic, not a proposed default. 0602 was the development recording;
the others are descriptive transfer checks. Timing references are the reviewer's approved
Exported/Ready clips (keep-only), and the start/end rates use acoustic proxies, so they are
not listening judgements. Variants are re-matched to the references by best overlap, so the
matched cohorts differ between variants: rates are descriptive, not paired improvements.

Input is the same private JSON config as ``audit_candidate_coverage.py`` (``name``, ``session``,
``words``, ``vad`` and the recording's cached ``<name>.levels.npy`` in --levels-dir). Output is
aggregate JSON only: counts, candidates per hour, recall and proxy rates. Needs the repository's
``src`` on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_candidate_coverage import distinct, recall, variants  # noqa: E402
from evaluate_candidates import exported_start, kept_clips  # noqa: E402
from jipandan.core import candidates as cand, vad  # noqa: E402

# End extension: move an end to the next speech run's end when that run starts within the gap
# of the end and the whole clip stays within the maximum length.
NEXT_RUN_GAPS_S = (.16, .32, .6)
NEXT_RUN_MAX_CLIP_S = 5.0

# Energy additions: loud 10 ms frames above a threshold are joined across short gaps, padded,
# and kept only when they last .6-5 s and the VAD hears almost no speech in them.
ENERGY_THRESHOLDS_DB = (-40, -35, -30, -25)
ENERGY_FRAMES_PER_S = 100            # 10 ms level frames
ENERGY_JOIN_GAP_FRAMES = 16          # 160 ms
ENERGY_PAD_BEFORE_S, ENERGY_PAD_AFTER_S = .2, .1
ENERGY_MIN_S, ENERGY_MAX_S = .6, 5.0
ENERGY_MAX_SPEECH_SHARE = .1         # share of VAD frames at or above the speech threshold
VAD_FRAME_S = .032

# Deduplication: drop a candidate whose overlap (IoU) with an already-kept one reaches the
# threshold. The preference decides which of two near-duplicates survives.
DEDUP_THRESHOLDS = (.7, .8, .9)
DEDUP_PREFERENCES = ("short", "long")

# A variant's candidate matches a reference when their overlap-over-union is at least this.
MATCH_IOU = .5
# Reference starts and ends are called late/early beyond these margins (seconds).
LATE_START_S, EXTRA_START_S, EARLY_END_S = .05, .25, .05


def extend_into_next_run(base: np.ndarray, runs_ms: list[tuple[int, int]], gap: float,
                         max_clip: float = NEXT_RUN_MAX_CLIP_S) -> np.ndarray:
    """Move each end to the end of the first speech run that starts after it, within ``gap``."""
    spans = base.copy()
    runs = np.array(runs_ms, float).reshape(-1, 2) / 1000
    if not len(runs) or not len(spans):
        return distinct(spans)
    index = np.searchsorted(runs[:, 0], spans[:, 1], side="right")
    valid = index < len(runs)
    nearest = np.clip(index, 0, len(runs) - 1)
    change = valid & (runs[nearest, 0] - spans[:, 1] <= gap) & (runs[nearest, 1] - spans[:, 0] <= max_clip)
    spans[change, 1] = runs[nearest[change], 1]
    return distinct(spans)


def energy_bursts(levels_db: np.ndarray, threshold: float, join_gap: int = ENERGY_JOIN_GAP_FRAMES) -> list[list[int]]:
    """Frame ranges ``[start, end)`` where the level reaches ``threshold``, joined across gaps of
    at most ``join_gap`` frames."""
    loud = levels_db >= threshold
    edges = np.diff(np.r_[False, loud, False].astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    joined: list[list[int]] = []
    for a, b in zip(starts, ends):
        if joined and a - joined[-1][1] <= join_gap:
            joined[-1][1] = int(b)
        else:
            joined.append([int(a), int(b)])
    return joined


def energy_additions(levels_db: np.ndarray, probs: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    """Burst-shaped candidates in which the VAD hears (almost) no speech."""
    added = []
    for a, b in energy_bursts(levels_db, threshold):
        start = max(0.0, a / ENERGY_FRAMES_PER_S - ENERGY_PAD_BEFORE_S)
        end = b / ENERGY_FRAMES_PER_S + ENERGY_PAD_AFTER_S
        if not ENERGY_MIN_S <= end - start <= ENERGY_MAX_S:
            continue
        inside = probs[int(start / VAD_FRAME_S):int(end / VAD_FRAME_S) + 1]
        if len(inside) and np.mean(inside >= cand.SPEECH_THRESHOLD) <= ENERGY_MAX_SPEECH_SHARE:
            added.append((start, end))
    return added


def suppress(spans: np.ndarray, threshold: float, prefer: str) -> np.ndarray:
    """Keep spans in ``prefer`` order (``short`` or ``long`` first), dropping any whose IoU with a
    kept span is at least ``threshold``."""
    if prefer not in DEDUP_PREFERENCES:
        raise ValueError("prefer must be 'short' or 'long'")
    duration = spans[:, 1] - spans[:, 0]
    order = np.argsort(duration if prefer == "short" else -duration, kind="stable")
    kept: list[int] = []
    for i in order:
        if kept:
            others = spans[kept]
            others = others[(others[:, 0] < spans[i, 1]) & (others[:, 1] > spans[i, 0])]
            if len(others):
                iou = ((np.minimum(others[:, 1], spans[i, 1]) - np.maximum(others[:, 0], spans[i, 0]))
                       / (np.maximum(others[:, 1], spans[i, 1]) - np.minimum(others[:, 0], spans[i, 0])))
                if (iou >= threshold).any():
                    continue
        kept.append(int(i))
    return spans[sorted(kept)]


def proxy_rates(kept: np.ndarray, spans: np.ndarray, levels_db: np.ndarray, hours: float) -> dict:
    """Candidate count, recall and the acoustic start/end proxies for one variant."""
    matched = late = early = extra = measured = 0
    shift: list[float] = []
    for a, b in kept:
        overlap = np.minimum(spans[:, 1], b) - np.maximum(spans[:, 0], a)
        union = np.maximum(spans[:, 1], b) - np.minimum(spans[:, 0], a)
        i = int(np.argmax(overlap / union))
        if overlap[i] / union[i] < MATCH_IOU:
            continue
        matched += 1
        diff = exported_start(levels_db, *spans[i]) - exported_start(levels_db, a, b)
        early += spans[i, 1] < b - EARLY_END_S
        if np.isfinite(diff):
            measured += 1
            shift.append(float(diff))
            late += diff > LATE_START_S
            extra += diff < -EXTRA_START_S
    return {"n": len(spans), "per_hour": len(spans) / hours, "recall": recall(kept, spans), "matched": matched,
            "start_measured": measured, "late_start": late / max(measured, 1),
            "extra_start_audio_proxy": extra / max(measured, 1), "early_end": early / max(matched, 1),
            "median_start_shift": float(np.median(shift))}


def run_recording(config: dict, levels_dir: Path) -> dict:
    segments = json.loads(Path(config["words"]).read_text())["segments"]
    probs = np.load(config["vad"]).astype(np.float32)
    runs = vad.speech_runs(probs, cand.SPEECH_THRESHOLD)
    levels = np.load(levels_dir / (config["name"] + ".levels.npy"))
    kept = kept_clips(Path(config["session"]))
    hours = len(probs) * VAD_FRAME_S / 3600
    sources = variants(segments, runs)
    base = sources["generator"]
    for gap in NEXT_RUN_GAPS_S:
        sources[f"end_next_run_gap_{gap}"] = extend_into_next_run(base, runs, gap)
    for threshold in ENERGY_THRESHOLDS_DB:
        sources[f"add_non_speech_energy_{threshold}dB"] = distinct([*base, *energy_additions(levels, probs, threshold)])
    followups = {name: proxy_rates(kept, spans, levels, hours) for name, spans in sources.items()
                 if name not in ("old_srt", "whisper_segments") and not name.startswith("extend_inside")}
    dedup = {}
    for threshold in DEDUP_THRESHOLDS:
        for prefer in DEDUP_PREFERENCES:
            spans = suppress(base, threshold, prefer)
            dedup[f"{threshold}_{prefer}"] = {"n": len(spans), "per_hour": len(spans) / hours,
                                               "recall": recall(kept, spans)}
    return {"followups": followups, "dedup": dedup}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--levels-dir", type=Path, required=True,
                        help="folder with <name>.levels.npy, cached by audit_candidate_coverage.py --audio")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError("output already exists; use a new path")
    result = {}
    for config in json.loads(args.config.read_text()):
        result[config["name"]] = run_recording(config, args.levels_dir)
        print(config["name"], "done", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
