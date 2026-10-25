"""Training datasets built from round files: ranking, timing, and title examples, with counts.

Round files hold facts (each round's clips, changes, and views); this module holds the rules that
turn them into examples, so changing a rule means building the dataset again, never rewriting a
round file. The same files always give the same bytes. See doc/datasets.md.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from jipandan.core.models import clip_candidate_from_dict
from jipandan.core.review_rounds import LABELS_TARGET, RANDOM, pick_chance
from jipandan.core.round_files import (
    VERSION as ROUND_FILE_VERSION, RoundHistory, clip_index, file_kind, outcome, parse_round_file, parse_update_file,
    time_ms,
)

FORMAT = "jipandan-dataset"
VERSION = 1
# Bump when a rule below changes what goes into a dataset, so each dataset names the rules that built it.
RULES = 1
# Clips whose range and title the owner approved: exported, or Ready to export.
APPROVED = ("exported", "group2")
FEATURES = ("peak_db", "mid_share_db", "bass_share_db", "no_speech_prob", "avg_logprob")


def _canonical(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(history: RoundHistory, clip_id: str) -> dict:
    index, _, suffix = clip_id.partition("-")
    sha = history.recording["sha256"]
    return {"recording": sha, "partition": sha, "round": history.info["number"], "seed": history.info["seed"],
            "clip_id": clip_id, "index": int(index), "suffix": int(suffix or 0), "parent": index if suffix else None}


def _export(clip: dict) -> dict | None:
    if not clip.get("last_export_path"):
        return None
    return {"mode": clip.get("last_export_mode"), "start_threshold_db": clip.get("last_export_start_threshold_db"),
            "stop_threshold_db": clip.get("last_export_stop_threshold_db"), "title": clip.get("last_export_title"),
            "file": clip.get("last_export_path"), "state": clip_candidate_from_dict(clip).export_state}


def build_dataset(files: Sequence[tuple[str, object]]) -> dict:
    """Build the dataset from round and update files, given as (file name or path, parsed JSON).

    Returns ``manifest`` and the ``ranking``, ``timing``, and ``titles`` example lists.
    """
    inputs: list[dict] = []
    bases: dict[tuple[str, str], list[tuple[int, str, dict, dict]]] = {}
    updates: dict[tuple[str, str], dict[str, tuple[str, dict, dict]]] = {}
    hashed = [(name, raw, hashlib.sha256(_canonical(raw).encode("utf-8")).hexdigest()) for name, raw in files]
    # Names only label inputs for people: which copy is used depends on content alone, and inputs
    # sharing a name are listed in the same order however they were given.
    for name, raw, sha in sorted(hashed, key=lambda item: (item[0], item[2])):
        entry = {"file": name, "kind": file_kind(raw), "content_sha256": sha}
        inputs.append(entry)
        try:
            data = parse_update_file(raw) if entry["kind"] == "update" else parse_round_file(raw)
        except ValueError as exc:
            entry.update(used=False, reason=str(exc))
            continue
        key = (data["recording"]["sha256"], data["round"]["seed"])
        entry.update(recording=key[0], round=data["round"]["number"], seed=key[1], version=raw.get("version"))
        if entry["kind"] == "update":
            # A copy of an update already read adds nothing.
            updates.setdefault(key, {}).setdefault(entry["content_sha256"], (name, data, entry))
        else:
            bases.setdefault(key, []).append((raw.get("version"), name, data, entry))

    ranking, timing, titles = [], [], []
    counts = {"ranking": Counter(), "timing": Counter(), "titles": Counter()}
    excluded = {"timing": Counter(), "titles": Counter()}
    recordings: dict[str, dict] = {}
    draws: set[tuple[str, str, int]] = set()
    gaps = 0
    for key in sorted(bases):
        # The copy in the newest format, written from the most history, stands for the round.
        candidates = sorted(bases[key], key=lambda item: (-item[0], item[3]["content_sha256"]))
        version, name, data, entry = candidates[0]
        for _, _, _, other_entry in candidates[1:]:
            other_entry.update(used=False, reason=f"another copy of this round, {name}, is used")
        round_updates = sorted(updates.get(key, {}).values(), key=lambda item: (item[0], item[2]["content_sha256"]))
        try:
            history = RoundHistory(data, [update for _, update, _ in round_updates])
        except ValueError as exc:
            entry.update(used=False, reason=str(exc))
            continue
        entry["used"] = True
        for _, _, update_entry in round_updates:
            update_entry["used"] = True
        gaps += history.gaps
        sources = [name, *(update_name for update_name, _, _ in round_updates)]
        recording = recordings.setdefault(key[0], {"name": history.recording.get("name"), "rounds": 0,
                                                    "ranking": 0, "timing": 0, "titles": 0})
        recording["rounds"] += 1
        info = history.info
        marks = history.review_marks()
        times = history.times()
        ended = history.clips_at(history.end_seq)
        final = history.clips_at()

        for clip_id, clip in ended.items():
            index = clip_index(clip_id)
            start = history.start.get(clip_id) or history.start.get(str(index)) or {}
            features = {name: start.get(name) for name in FEATURES}
            chance = pick_chance(info, index)
            result = outcome(clip["status"])
            mark = marks.get(clip_id, {"corrected": False, "undone": 0})
            ranking.append({
                **_identity(history, clip_id), "role": info["roles"][str(index)], "pick_chance": chance,
                "pool": info.get("pool"), "sampling": info.get("sampling"), "score_version": info.get("score_version"),
                "score": history.score(clip_id), "features": features, "features_version": info.get("features_version"),
                "status": clip["status"], "outcome": result, **mark, "time_ms": times.get(clip_id),
                "synthetic": history.synthetic, "sources": sources,
            })
            recording["ranking"] += 1
            tally = counts["ranking"]
            tally["examples"] += 1
            tally[result] += 1
            tally["corrected"] += mark["corrected"]
            tally["synthetic"] += history.synthetic
            tally["missing_pick_chance"] += chance is None
            tally["missing_features"] += all(value is None for value in features.values())
            if info["roles"][str(index)] == RANDOM and result != "unfinished":
                draws.add((key[0], key[1], index))

        for clip_id, clip in final.items():
            status = clip["status"]
            if status == "group1":
                excluded["timing"]["needs work"] += 1
                excluded["titles"]["needs work"] += 1
                continue
            if status not in APPROVED:
                continue
            if history.synthetic:
                excluded["timing"]["older format without final state"] += 1
                excluded["titles"]["older format without final state"] += 1
                continue
            changed = ended.get(clip_id) != clip
            common = {**_identity(history, clip_id), "status": status, "changed_after_round": changed, "sources": sources}
            start_ms, end_ms = time_ms(clip["start"]), time_ms(clip["start"]) + round(float(clip["duration"]) * 1000)
            original = (time_ms(clip["original_start"]), time_ms(clip["original_end"]))
            timing.append({**common, "original_start_ms": original[0], "original_end_ms": original[1],
                           "start_ms": start_ms, "end_ms": end_ms, "retimed": (start_ms, end_ms) != original,
                           "export": _export(clip)})
            recording["timing"] += 1
            counts["timing"]["examples"] += 1
            counts["timing"]["retimed"] += (start_ms, end_ms) != original
            counts["timing"]["changed_after_round"] += changed
            source = clip.get("source_text")
            if not source:
                excluded["titles"]["no source text"] += 1
                continue
            title = (clip.get("last_export_title") if status == "exported" else None) or clip["title"]
            titles.append({**common, "source_text": source, "title": title, "edited": title != source})
            recording["titles"] += 1
            counts["titles"]["examples"] += 1
            counts["titles"]["edited"] += title != source
            counts["titles"]["changed_after_round"] += changed

    for entry in inputs:
        if entry.get("kind") == "update" and "reason" not in entry:
            entry.setdefault("used", False)
            if not entry["used"]:
                entry["reason"] = ("a copy of another update file" if entry.get("seed") and
                                   (entry["recording"], entry["seed"]) in bases else "its round file is not among the inputs")
    order = lambda row: (row["recording"], row["round"], row["seed"], row["index"], row["suffix"])
    manifest = {
        "format": FORMAT, "version": VERSION, "rules": RULES, "round_file_version": ROUND_FILE_VERSION,
        "inputs": inputs,
        "recordings": dict(sorted(recordings.items())),
        "counts": {
            "ranking": dict(sorted(counts["ranking"].items())),
            "timing": {**dict(sorted(counts["timing"].items())), "excluded": dict(sorted(excluded["timing"].items()))},
            "titles": {**dict(sorted(counts["titles"].items())), "excluded": dict(sorted(excluded["titles"].items()))},
        },
        "labels": {"random_draws": len(draws), "recordings": len({sha for sha, _, _ in draws}), "target": LABELS_TARGET},
        "update_gaps": gaps,
    }
    return {"manifest": manifest, "ranking": sorted(ranking, key=order), "timing": sorted(timing, key=order),
            "titles": sorted(titles, key=order)}


def write_dataset(folder: Path, dataset: dict) -> list[Path]:
    """Write ``dataset`` into ``folder`` as manifest.json and one JSON Lines file per task."""
    folder.mkdir(parents=True, exist_ok=True)
    written = [folder / "manifest.json"]
    written[0].write_text(json.dumps(dataset["manifest"], ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                          encoding="utf-8")
    for task in ("ranking", "timing", "titles"):
        path = folder / f"{task}.jsonl"
        path.write_text("".join(_canonical(row) + "\n" for row in dataset[task]), encoding="utf-8")
        written.append(path)
    return written
