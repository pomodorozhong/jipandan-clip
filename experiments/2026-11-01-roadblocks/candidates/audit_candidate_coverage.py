"""Explore candidate recall/cost limits using existing transcripts, VAD arrays and reviewed clips.

Input is a JSON list of {name, session, srt, words, vad, audio} paths. Output is aggregate
JSON only. 0602 is the development recording; other recordings must not select parameters.
Variants are diagnostics, not new app defaults. Unedited keeps favor their source segmentation.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

# `evaluate_candidates` is the application's evaluation tool, kept in the repository's scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from jipandan.core import candidates as cand, vad
from jipandan.core.srt import parse_srt, srt_time_to_seconds
from evaluate_candidates import KEPT, kept_clips, levels_db, match


def seconds(value: str) -> float:
    return srt_time_to_seconds(value.replace(".", ","))


def clips(path: Path) -> list[dict]:
    if path.suffix == ".db":
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
            return [json.loads(d) for (d,) in db.execute("SELECT data FROM clip")]
    return json.loads(path.read_text())["candidates"]


def bounds(items: list[cand.Candidate]) -> np.ndarray:
    return np.array([(x.start_ms / 1000, x.end_ms / 1000) for x in items], float).reshape(-1, 2)


def distinct(spans) -> np.ndarray:
    return np.array(sorted({(round(a, 3), round(b, 3)) for a, b in spans if b > a}), float).reshape(-1, 2)


def variants(segments: list[dict], runs: list[tuple[int, int]]) -> dict[str, np.ndarray]:
    base = bounds(cand.generate_candidates(segments, runs))
    out = {"generator": base}
    for ms in (1200, 2000):
        out[f"backoff_{ms}ms"] = bounds(cand.generate_candidates(segments, runs, onset_backoff_ms=ms))
    for length in (8000, 12000):
        out[f"max_{length}ms"] = bounds(cand.generate_candidates(segments, runs, max_length_ms=length))
    all_runs = [(max(0, a - 200) / 1000, b / 1000) for a, b in runs if 600 <= b - max(0, a - 200) <= 5000]
    out["add_wordless_vad"] = distinct([*base, *all_runs])
    ends = np.array([b / 1000 for a, b in runs])
    starts = np.array([a / 1000 for a, b in runs])
    if len(runs):
        # Extend only ends inside a speech run, and only to a nearby forward speech end.
        idx = np.clip(np.searchsorted(starts, base[:, 1], side="right") - 1, 0, len(runs) - 1)
        for limit in (.5, 1.):
            change = (starts[idx] < base[:, 1]) & (ends[idx] > base[:, 1]) & (ends[idx] - base[:, 1] <= limit)
            y = base.copy()
            y[change, 1] = ends[idx[change]] + .05
            out[f"extend_inside_end_{limit}s"] = distinct(y)
    words = cand.words_from_segments(segments)
    for gap_ms in (160, 320):
        starts_ms = [w.start_ms for i, w in enumerate(words) if i == 0 or w.start_ms - words[i - 1].end_ms >= gap_ms or re.search(r"[。！？!?]", words[i - 1].text)]
        ends_ms = [w.end_ms for i, w in enumerate(words) if i == len(words) - 1 or words[i + 1].start_ms - w.end_ms >= gap_ms or re.search(r"[。！？!?]", w.text)]
        extra = []
        for start in starts_ms:
            first = bisect.bisect_left(ends_ms, start + 400)
            for end in ends_ms[first:first + 3]:
                a, b = max(0, start - 100) / 1000, end / 1000
                if len(ends):
                    j = min(np.searchsorted(ends, b), len(ends) - 1)
                    if 0 <= ends[j] - b <= .5:
                        b = ends[j]
                if .6 <= b - a <= 5:
                    extra.append((a, b))
        out[f"add_word_phrases_gap_{gap_ms}ms"] = distinct([*base, *extra])
    return out


def recall(kept: np.ndarray, source: np.ndarray) -> dict:
    result = {}
    for tol in (.25, .5, 1., 1.5):
        errors = match(kept, source, tol)
        found = np.isfinite(errors[:, 0])
        result[str(tol)] = {
            "found": int(found.sum()), "total": len(kept),
            "recall": float(found.mean()) if len(kept) else None,
            "median_errors_ms": (1000 * np.median(errors[found], axis=0)).tolist() if found.any() else None,
        }
    return result


def approximate_cut_rate(source: np.ndarray, levels: np.ndarray, probs: np.ndarray) -> dict:
    # Same acoustic diagnostic as the earlier experiment: a proxy, not human cut-in labels.
    bad_start = bad_end = 0
    for a, b in source:
        i, j = round(a * 100), round(b * 100)
        around = levels[max(0, i - 300):min(len(levels), j + 301)]
        inside = levels[max(0, i):min(len(levels), max(i + 5, j))]
        if not len(around) or not len(inside):
            continue
        floor, speech = np.percentile(around, 10), np.percentile(inside, 90)
        threshold = floor + .35 * (speech - floor)
        for edge, start in ((a, True), (b, False)):
            at = round(edge * 100)
            window = levels[max(0, at - 6):at] if start else levels[at:at + 6]
            p0 = max(0, int((edge - .1 if start else edge) / .032))
            p1 = min(len(probs), int((edge if start else edge + .1) / .032) + 1)
            if len(window) and p1 > p0 and window.mean() >= threshold and probs[p0:p1].max() >= .5:
                if start:
                    bad_start += 1
                else:
                    bad_end += 1
    return {"start_proxy": bad_start / max(len(source), 1), "end_proxy": bad_end / max(len(source), 1)}


ONSET_BACKOFF = .05  # seconds; the generator starts a clip this much before the word start


def oracle_found(retimed: np.ndarray, word_starts: np.ndarray, vad_ends: np.ndarray, tol: float,
                 backoff: float = ONSET_BACKOFF) -> int:
    """Count references some (word start, VAD end) pair can match within ``tol`` seconds.

    Every word start is moved earlier by ``backoff`` first, exactly as the generator does, and
    only then kept or dropped by its distance to the reference start. Filtering the unshifted
    starts and shifting afterwards (the earlier version) moved the window by ``backoff``.
    """
    starts_all = word_starts - backoff
    found = 0
    for a, b in retimed:
        starts = starts_all[abs(starts_all - a) <= tol]
        ends = vad_ends[abs(vad_ends - b) <= tol]
        choices = np.array([(s, e) for s in starts for e in ends if e > s]).reshape(-1, 2)
        found += bool(np.isfinite(match(np.array([[a, b]]), choices, tol)).all()) if len(choices) else False
    return found


def run_recording(config: dict, cache: Path, with_audio: bool) -> dict:
    segments = json.loads(Path(config["words"]).read_text())["segments"]
    probs = np.load(config["vad"]).astype(np.float32)
    runs = vad.speech_runs(probs, cand.SPEECH_THRESHOLD)
    session = clips(Path(config["session"]))
    kept = kept_clips(Path(config["session"]))
    retimed = []
    for c in session:
        if c["status"] not in KEPT:
            continue
        a, b = seconds(c["start"]), seconds(c["start"]) + float(c["duration"])
        if abs(a - seconds(c["original_start"])) > .05 or abs(b - seconds(c["original_end"])) > .05:
            retimed.append((a, b))
    retimed = np.array(retimed).reshape(-1, 2)
    sources = variants(segments, runs)
    sources["old_srt"] = np.array([(srt_time_to_seconds(e.start), srt_time_to_seconds(e.end)) for e in parse_srt(Path(config["srt"]))]).reshape(-1, 2)
    sources["whisper_segments"] = np.array([(s["start"], s["end"]) for s in segments]).reshape(-1, 2)
    hours = len(probs) * .032 / 3600
    if hours <= 0:
        raise ValueError("empty VAD probability array")
    result = {"hours": hours, "kept": len(kept), "retimed": len(retimed), "variants": {}}
    levels = None
    if with_audio:
        level_path = cache / (config["name"] + ".levels.npy")
        if level_path.exists():
            levels = np.load(level_path)
        else:
            levels = levels_db(Path(config["audio"]))
            np.save(level_path, levels)
    for name, source in sources.items():
        # Invalid zero-duration Whisper segments are not reviewable clips. Keep duplicate
        # valid ranges so the count still reflects actual review work.
        source = source[np.isfinite(source).all(1) & (source[:, 1] > source[:, 0])]
        source = source[np.argsort(source[:, 0], kind="stable")]
        near_duplicates = 0
        for i, (a, b) in enumerate(source):
            nearby = source[max(0, i - 20):i]
            if len(nearby):
                iou = (np.minimum(b, nearby[:, 1]) - np.maximum(a, nearby[:, 0])) / (np.maximum(b, nearby[:, 1]) - np.minimum(a, nearby[:, 0]))
                near_duplicates += bool((iou >= .8).any())
        result["variants"][name] = {
            "candidates": len(source), "per_hour": len(source) / hours,
            "median_duration": float(np.median(source[:, 1] - source[:, 0])) if len(source) else None,
            "near_duplicate_fraction_previous_20": near_duplicates / max(len(source), 1),
            "all": recall(kept, source), "retimed": recall(retimed, source),
        }
        if levels is not None and name in ("generator", "backoff_1200ms", "backoff_2000ms", "extend_inside_end_0.5s", "extend_inside_end_1.0s"):
            result["variants"][name]["acoustic_proxy"] = approximate_cut_rate(source, levels, probs)
    words = cand.words_from_segments(segments)
    ws = np.array([w.start_ms / 1000 for w in words])
    ve = np.array([b / 1000 for a, b in runs])
    # Oracle chooses freely from every Whisper word start and every VAD end; it is an upper
    # bound for this point vocabulary, not a candidate generator or achievable prediction.
    oracle = {}
    for tol in (.25, .5, 1.):
        oracle[str(tol)] = {"found": oracle_found(retimed, ws, ve, tol), "total": len(retimed)}
    no_vad = no_words = 0
    for a, b in kept:
        pr = probs[max(0, int(a / .032)):max(0, int(b / .032) + 1)]
        no_vad += not len(pr) or pr.max() < .3
        no_words += not any(w.start_ms < b * 1000 and w.end_ms > a * 1000 for w in words)
    result["ceilings"] = {"kept_without_vad": int(no_vad), "kept_without_words": int(no_words), "oracle_retimed_word_start_vad_end": oracle}
    result["input_hashes"] = {key: hashlib.sha256(Path(config[key]).read_bytes()).hexdigest() for key in ("session", "srt", "words", "vad")}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--audio", action="store_true")
    args = p.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {}
    for config in json.loads(args.config.read_text()):
        result[config["name"]] = run_recording(config, args.out.parent, args.audio)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(config["name"], "done", flush=True)


if __name__ == "__main__":
    main()
