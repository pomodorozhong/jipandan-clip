"""Round files: one standalone JSON file per finished review round, written beside the recording once.

A round file outlives the session database: it names the recording by a hash of its audio and
each clip by its time range, so a fresh project of the same recording, even one cut into
different clips, can read it back to skip the clips the round covered and keep its decisions for
the estimates. It holds only what the round produced: the time on each clip counts views logged
while the round was open. See doc/app-rebuild-plan.md, "Round files".
"""

from __future__ import annotations

import bisect
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from jipandan.core.review_rounds import KEPT, PROCESSED, RANDOM, TOP
from jipandan.core.stage_times import STAGES

FORMAT = "jipandan-round"
VERSION = 1
# A file clip matches a clip here when they overlap by at least half of the shorter one.
MIN_OVERLAP = 0.5
MAX_FILE_CLIPS = 20_000


def audio_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as audio:
        for block in iter(lambda: audio.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def round_file_path(audio: Path, number: int) -> Path:
    """Where a round's file goes: beside the recording, with a counter if the name is taken."""
    base = audio.with_name(f"{audio.stem}.round-{number:02d}.json")
    path, copy = base, 1
    while path.exists():
        copy += 1
        path = base.with_name(f"{audio.stem}.round-{number:02d}-{copy}.json")
    return path


def outcome(status: str) -> str:
    return "kept" if status in KEPT else "rejected" if status in PROCESSED else "unfinished"


def build_round_file(
    item: dict, recording: dict, clips: Sequence[tuple[str, int, int, int, str, float | None]],
    times: dict[str, dict[str, int]],
) -> dict:
    """The file for round ``item``; ``clips`` are its clips as (clip_id, index, start_ms, end_ms, status, score)."""
    roles = item["roles"]
    completed = item["completed"] or {}
    return {
        "format": FORMAT, "version": VERSION,
        "recording": recording,
        "round": {
            "number": item["number"], "size": item["size"], "pool": item.get("pool"), "total": item.get("total"),
            "random_share": item["random_share"], "seed": item["seed"], "score_version": item.get("score_version"),
            "sampling": item.get("sampling", 1), "random_chance": item.get("random_chance"),
            "started": item.get("started"), "ended": completed.get("t"), "unprocessed": completed.get("unprocessed"),
        },
        "clips": [
            {"start_ms": start, "end_ms": end, "role": roles[str(index)],
             "score": None if score is None else round(score, 1), "outcome": outcome(status),
             "time_ms": times.get(clip_id, dict.fromkeys(STAGES, 0))}
            for clip_id, index, start, end, status, score in clips if str(index) in roles
        ],
    }


def write_round_file(path: Path, data: dict) -> None:
    """Write ``data`` to a new file; an existing file is never replaced."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


def parse_round_file(data: object) -> dict:
    """Check that ``data`` is a round file and return it; raises ValueError naming what is wrong."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Jipandan round file")
    if data.get("version") != VERSION:
        raise ValueError(f"round file version {data.get('version')} is not supported")
    recording, info, clips = data.get("recording"), data.get("round"), data.get("clips")
    if not isinstance(recording, dict) or not isinstance(recording.get("sha256"), str):
        raise ValueError("the file does not name its recording")
    if not isinstance(info, dict) or not isinstance(info.get("seed"), str) or not isinstance(info.get("number"), int):
        raise ValueError("the file's round is incomplete")
    if not isinstance(clips, list) or len(clips) > MAX_FILE_CLIPS:
        raise ValueError("the file's clips are missing")
    for clip in clips:
        if not (isinstance(clip, dict) and isinstance(clip.get("start_ms"), int) and isinstance(clip.get("end_ms"), int)
                and clip["end_ms"] > clip["start_ms"] and clip.get("role") in (TOP, RANDOM)
                and clip.get("outcome") in ("kept", "rejected", "unfinished")):
            raise ValueError("a clip in the file is malformed")
    return data


def match_clips(file_clips: Sequence[dict], clips: Sequence[tuple[int, int, int]]) -> dict[int, tuple[float, dict]]:
    """Map SRT indexes here, from ``clips`` as (index, start_ms, end_ms), to the file clip each overlaps most.

    Clips are matched by time, not index, so a project cut into different clips still finds them.
    Each match comes with its overlap as a share of the shorter clip; several clips here can match
    one file clip when this project cut it into parts.
    """
    ordered = sorted(file_clips, key=lambda clip: clip["start_ms"])
    starts = [clip["start_ms"] for clip in ordered]
    matches: dict[int, tuple[float, dict]] = {}
    for index, start, end in clips:
        position = max(0, bisect.bisect_left(starts, start) - 1)
        while position < len(ordered) and ordered[position]["start_ms"] < end:
            clip = ordered[position]
            overlap = min(end, clip["end_ms"]) - max(start, clip["start_ms"])
            shorter = min(end - start, clip["end_ms"] - clip["start_ms"])
            share = overlap / shorter if shorter > 0 else 0.0
            if share >= MIN_OVERLAP and share > matches.get(index, (0.0, {}))[0]:
                matches[index] = (share, clip)
            position += 1
    return matches


def imported_round(data: dict, matches: dict[int, tuple[float, dict]], number: int, file_name: str) -> dict:
    """A finished round here built from a round file's clips matched by ``match_clips``.

    Each file clip was one decision, so it counts once: its outcome goes to the clip here that
    overlaps it most, other clips here cut from it are only ``covered`` (left out of later rounds
    if it was decided, without counting as keepers or labels), and the round's counts and random
    labels come from the file's clips with the file's scores, not from the clips here.
    """
    info = data["round"]
    stage_ms = dict.fromkeys(STAGES, 0)
    for clip in data["clips"]:
        for stage in STAGES:
            value = (clip.get("time_ms") or {}).get(stage)
            stage_ms[stage] += value if isinstance(value, int) and value > 0 else 0
    matched_clips = {id(clip) for _, clip in matches.values()}
    best: dict[int, tuple[float, int]] = {}
    for index, (share, clip) in sorted(matches.items()):
        if share > best.get(id(clip), (0.0, 0))[0]:
            best[id(clip)] = (share, index)
    primary = {index for _, index in best.values()}
    return {
        "number": number, "size": len(data["clips"]), "pool": info.get("pool"), "total": info.get("total"),
        "random_share": info.get("random_share", 0), "seed": info["seed"], "score_version": info.get("score_version"),
        "sampling": info.get("sampling", 1), "random_chance": info.get("random_chance"),
        "top": [], "random": [],
        "roles": {str(index): clip["role"] for index, (_, clip) in matches.items()},
        "outcomes": {str(index): clip["outcome"] for index, (_, clip) in matches.items() if index in primary},
        "covered": sorted(index for index, (_, clip) in matches.items()
                          if index not in primary and clip["outcome"] != "unfinished"),
        "file_clips": [{"role": clip["role"], "score": clip.get("score"), "outcome": clip["outcome"]}
                       for clip in data["clips"]],
        "started": info.get("started"),
        "completed": {"t": info.get("ended") or info.get("started"), "unprocessed": info.get("unprocessed") or 0},
        "stage_ms": stage_ms,
        "imported": {"file": file_name, "number": info["number"], "clips": len(data["clips"]),
                     "unmatched": sum(1 for clip in data["clips"] if id(clip) not in matched_clips)},
    }
