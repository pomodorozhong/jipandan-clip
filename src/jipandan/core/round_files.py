"""Round files: one standalone JSON file per finished review round, written beside the recording once.

A round file outlives the session database: it names the recording by a hash of its audio and
holds the round's part of the review history, so a fresh project of the same recording, even one
cut into different clips, can read it back, and datasets can be built from it later. It records
facts, not conclusions: every round clip as it was when the round started, each change to them
with the clips as they were right after it, and the views of them. What the round found (its
outcomes, time, corrections) is worked out when the file is read, by ``RoundHistory``.

Changes to a round's clips after it ended go into update files beside it, each holding the
changes and views since the last file, so no file is ever rewritten.

A reader ignores fields it doesn't know and reads missing ones as None, so adding a field keeps
the version. The version goes up only when the file's own structure changes, with one function
in ``UPGRADES`` turning a file of the previous version into the current one, so the rest of the
app only ever sees the current version. See doc/app-rebuild-plan.md, "Round files".
"""

from __future__ import annotations

import bisect
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from jipandan.core.models import clip_candidate_from_dict
from jipandan.core.review_rounds import KEPT, OUTCOME_STATUS, PROCESSED, RANDOM, TOP, clip_times
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.core.stage_times import STAGES

FORMAT = "jipandan-round"
UPDATE_FORMAT = "jipandan-round-update"
VERSION = 2
# A file clip matches a clip here when they overlap by at least half of the shorter one.
MIN_OVERLAP = 0.5
MAX_FILE_CLIPS = 20_000
MAX_FILE_ENTRIES = 500_000


def audio_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as audio:
        for block in iter(lambda: audio.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _free_path(base: Path) -> Path:
    """``base``, or the same name with a counter when it is taken."""
    path, copy = base, 1
    while path.exists():
        copy += 1
        path = base.with_name(f"{base.stem}-{copy}{base.suffix}")
    return path


def round_file_path(audio: Path, number: int) -> Path:
    """Where a round's file goes: beside the recording, with a counter if the name is taken."""
    return _free_path(audio.with_name(f"{audio.stem}.round-{number:02d}.json"))


def update_file_path(audio: Path, number: int, update: int) -> Path:
    return _free_path(audio.with_name(f"{audio.stem}.round-{number:02d}.update-{update:02d}.json"))


def outcome(status: str) -> str:
    return "kept" if status in KEPT else "rejected" if status in PROCESSED else "unfinished"


def time_ms(value: str) -> int:
    return round(srt_time_to_seconds(value.replace(".", ",")) * 1000)


def clip_index(clip_id: str) -> int:
    return int(clip_id.split("-")[0])


def in_round(roles: dict[str, str], clip_id: str | None) -> bool:
    """Whether ``clip_id`` belongs to a round; membership is by SRT index, so split clips belong too."""
    return clip_id is not None and clip_id.split("-")[0] in roles


def _portable_clip(clip: dict | None) -> dict | None:
    """A stored clip with its export path cut to the file name, so a copied file holds no folder layout."""
    if clip is None or not clip.get("last_export_path"):
        return clip
    return {**clip, "last_export_path": Path(clip["last_export_path"]).name}


def _portable_event(event: dict) -> dict:
    return {**event, "path": Path(event["path"]).name} if isinstance(event.get("path"), str) else event


def round_slice(roles: dict[str, str], changes: Sequence[dict], events: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """The changes and events of ``RecordingStore.history`` that touch a round's clips, made portable."""
    kept_changes = []
    for change in changes:
        after = {clip_id: _portable_clip(clip) for clip_id, clip in change["after"].items() if in_round(roles, clip_id)}
        if after:
            kept_changes.append({**change, "after": after, "events": [_portable_event(e) for e in change["events"]]})
    return kept_changes, [_portable_event(e) for e in events if in_round(roles, e.get("clip"))]


def build_round_file(
    item: dict, recording: dict, source: dict, clips_at_start: dict[str, dict], scores: dict[str, float | None],
    changes: Sequence[dict], events: Sequence[dict], start_seq: int, end_seq: int,
) -> dict:
    """The file for finished round ``item``.

    ``source`` names where the clips came from (``clip_source``, ``srt_sha256``, ``features_version``);
    ``clips_at_start`` holds each round clip as stored when the round started, by clip ID, and
    ``scores`` its Likely keep score; ``changes`` and ``events`` are the store's history between
    ``start_seq`` and ``end_seq``.
    """
    completed = item["completed"] or {}
    roles = item["roles"]
    changes, events = round_slice(roles, changes, events)
    return {
        "format": FORMAT, "version": VERSION,
        "recording": recording,
        "round": {
            "number": item["number"], "size": item["size"], "pool": item.get("pool"), "total": item.get("total"),
            "random_share": item["random_share"], "seed": item["seed"], "score_version": item.get("score_version"),
            "sampling": item.get("sampling", 1), "random_chance": item.get("random_chance"),
            "started": item.get("started"), "ended": completed.get("t"), "unprocessed": completed.get("unprocessed"),
            **source, "roles": roles, "start_seq": start_seq, "end_seq": end_seq,
        },
        "clips_at_start": {
            clip_id: {**_portable_clip(clip), "score": None if scores.get(clip_id) is None else round(scores[clip_id], 1)}
            for clip_id, clip in sorted(clips_at_start.items(), key=lambda pair: _clip_order(pair[0]))
            if in_round(roles, clip_id)
        },
        "changes": changes,
        "events": events,
    }


def build_update_file(
    item: dict, sha256: str, update: int, from_seq: int, to_seq: int, changes: Sequence[dict], events: Sequence[dict],
) -> dict:
    """Update file ``update`` of finished round ``item``: its clips' changes and views after ``from_seq``."""
    changes, events = round_slice(item["roles"], changes, events)
    return {
        "format": UPDATE_FORMAT, "version": VERSION,
        "recording": {"sha256": sha256},
        "round": {"number": item["number"], "seed": item["seed"]},
        "update": update, "from_seq": from_seq, "to_seq": to_seq,
        "changes": changes, "events": events,
    }


def write_round_file(path: Path, data: dict) -> None:
    """Write ``data`` to a new file; an existing file is never replaced."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


def _clip_order(clip_id: str) -> tuple[int, int]:
    index, _, suffix = clip_id.partition("-")
    return int(index), int(suffix or 0)


# Reading ------------------------------------------------------------------


def file_kind(data: object) -> str | None:
    """"round" or "update" for a Jipandan round or update file, otherwise None."""
    if isinstance(data, dict):
        return {FORMAT: "round", UPDATE_FORMAT: "update"}.get(data.get("format"))
    return None


def _check_v1(data: dict) -> None:
    clips = data.get("clips")
    if not isinstance(clips, list) or len(clips) > MAX_FILE_CLIPS:
        raise ValueError("the file's clips are missing")
    for clip in clips:
        if not (isinstance(clip, dict) and isinstance(clip.get("start_ms"), int) and isinstance(clip.get("end_ms"), int)
                and clip["end_ms"] > clip["start_ms"] and clip.get("role") in (TOP, RANDOM)
                and clip.get("outcome") in ("kept", "rejected", "unfinished")):
            raise ValueError("a clip in the file is malformed")


def _synthetic_clip(index: int, start_ms: int, end_ms: int, status: str) -> dict:
    start = seconds_to_ffmpeg_timestamp(start_ms / 1000)
    return {"index": index, "suffix": 0, "title": "", "original_start": start,
            "original_end": seconds_to_ffmpeg_timestamp(end_ms / 1000), "start": start,
            "duration": f"{(end_ms - start_ms) / 1000:.3f}", "status": status}


def v1_to_v2(data: dict) -> dict:
    """A version 1 file, which held each clip's outcome and time, as the history that would produce them.

    Version 1 named clips only by time, so they get stand-in IDs 1, 2, ... in time order. Each starts
    Unsorted, one synthetic change at the round's end gives it its outcome (kept reads as exported,
    as import always read it), and one synthetic view per stage holds its time. Everything else
    version 2 records is unknown and read as None.
    """
    _check_v1(data)
    info = data["round"]
    ended = info.get("ended") or info.get("started")
    roles, start, after, events = {}, {}, {}, []
    for number, clip in enumerate(sorted(data["clips"], key=lambda c: (c["start_ms"], c["end_ms"])), 1):
        clip_id = str(number)
        roles[clip_id] = clip["role"]
        start[clip_id] = {**_synthetic_clip(number, clip["start_ms"], clip["end_ms"], "pending"), "score": clip.get("score")}
        after[clip_id] = _synthetic_clip(number, clip["start_ms"], clip["end_ms"], OUTCOME_STATUS[clip["outcome"]])
        for stage in STAGES:
            ms = (clip.get("time_ms") or {}).get(stage)
            if isinstance(ms, int) and ms > 0:
                events.append({"seq": 1, "t": ended, "type": "view", "clip": clip_id, "stage": stage, "dwell_ms": ms,
                               "synthetic": True})
    return {
        **data, "version": 2,
        "round": {**info, "sampling": info.get("sampling", 1), "random_chance": info.get("random_chance"),
                  "roles": roles, "start_seq": 0, "end_seq": 1, "upgraded_from": 1},
        "clips_at_start": start,
        "changes": [{"seq": 1, "t": ended, "type": "outcome", "label": None, "undoes": None, "events": [],
                     "after": after, "synthetic": True}],
        "events": events,
    }


# One entry per breaking change: the version it reads and the function that turns it into the next.
UPGRADES: dict[int, Callable[[dict], dict]] = {1: v1_to_v2}


def _valid_clip_id(clip_id: object) -> bool:
    try:
        _clip_order(clip_id)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _valid_clip(clip: object) -> bool:
    """Whether ``clip`` is a clip snapshot with every field the readers of round files use."""
    if not isinstance(clip, dict):
        return False
    try:
        clip_candidate_from_dict(clip)
        for key in ("original_start", "original_end", "start"):
            time_ms(clip[key])
        float(clip["duration"])
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return False
    return isinstance(clip["title"], str) and isinstance(clip.get("status"), str)


def _check_history(changes: object, events: object) -> None:
    if not isinstance(changes, list) or not isinstance(events, list) or len(changes) + len(events) > MAX_FILE_ENTRIES:
        raise ValueError("the file's history is missing")
    for change in changes:
        if not (isinstance(change, dict) and isinstance(change.get("seq"), int) and isinstance(change.get("after"), dict)
                and all(_valid_clip_id(clip_id) and (clip is None or _valid_clip(clip))
                        for clip_id, clip in change["after"].items())):
            raise ValueError("a change in the file is malformed")
    for event in events:
        if not (isinstance(event, dict) and isinstance(event.get("seq"), int) and _valid_clip_id(event.get("clip"))
                and isinstance(event.get("type"), str)
                and (event["type"] != "view" or isinstance(event.get("dwell_ms"), int))):
            raise ValueError("an event in the file is malformed")


def check_in_round(roles: dict[str, str], changes: list[dict], events: list[dict]) -> None:
    """Raise ValueError if ``changes`` or ``events`` name a clip outside the round with ``roles``."""
    if not all(in_round(roles, clip_id) for change in changes for clip_id in change["after"]) \
            or not all(in_round(roles, event["clip"]) for event in events):
        raise ValueError("the file's history names a clip outside its round")


def _check_v2(data: dict) -> None:
    info, start = data["round"], data.get("clips_at_start")
    roles = info.get("roles")
    if not (isinstance(roles, dict) and all(role in (TOP, RANDOM) for role in roles.values())
            and isinstance(info.get("start_seq"), int) and isinstance(info.get("end_seq"), int)):
        raise ValueError("the file's round is incomplete")
    if not isinstance(start, dict) or len(start) > MAX_FILE_CLIPS:
        raise ValueError("the file's clips are missing")
    if not all(_valid_clip_id(clip_id) and in_round(roles, clip_id) and _valid_clip(clip)
               for clip_id, clip in start.items()):
        raise ValueError("a clip in the file is malformed")
    _check_history(data.get("changes"), data.get("events"))
    check_in_round(roles, data["changes"], data["events"])


def parse_round_file(data: object) -> dict:
    """Check that ``data`` is a round file and return it in the current version; raises ValueError naming what is wrong."""
    if file_kind(data) != "round":
        raise ValueError("not a Jipandan round file")
    version = data.get("version")
    if version not in (*UPGRADES, VERSION):
        raise ValueError(f"round file version {version} is not supported")
    recording, info = data.get("recording"), data.get("round")
    if not isinstance(recording, dict) or not isinstance(recording.get("sha256"), str):
        raise ValueError("the file does not name its recording")
    if not isinstance(info, dict) or not isinstance(info.get("seed"), str) or not isinstance(info.get("number"), int):
        raise ValueError("the file's round is incomplete")
    while data["version"] in UPGRADES:
        data = UPGRADES[data["version"]](data)
    _check_v2(data)
    return data


def parse_update_file(data: object) -> dict:
    """Check that ``data`` is an update file and return it; raises ValueError naming what is wrong."""
    if file_kind(data) != "update":
        raise ValueError("not a Jipandan round update file")
    if data.get("version") != VERSION:
        raise ValueError(f"update file version {data.get('version')} is not supported")
    recording, info = data.get("recording"), data.get("round")
    if not isinstance(recording, dict) or not isinstance(recording.get("sha256"), str):
        raise ValueError("the file does not name its recording")
    if not isinstance(info, dict) or not isinstance(info.get("seed"), str) or not isinstance(info.get("number"), int):
        raise ValueError("the file does not name its round")
    if not all(isinstance(data.get(key), int) for key in ("update", "from_seq", "to_seq")):
        raise ValueError("the file's update is incomplete")
    _check_history(data.get("changes"), data.get("events"))
    return data


class RoundHistory:
    """A round read back from its file and any update files: its clips at any point, and what it found."""

    def __init__(self, data: dict, updates: Sequence[dict] = ()) -> None:
        self.recording = data["recording"]
        self.info = data["round"]
        self.roles: dict[str, str] = self.info["roles"]
        self.start: dict[str, dict] = data["clips_at_start"]
        self.changes = sorted(data["changes"], key=lambda change: change["seq"])
        self.events = sorted(data["events"], key=lambda event: event["seq"])
        self.synthetic = self.info.get("upgraded_from") is not None
        self.end_seq: int = self.info["end_seq"]
        self.last_seq = self.end_seq
        # Updates applied, and gaps where an update file between two others is missing.
        self.updates = self.gaps = 0
        self._file_clips: list[dict] | None = None
        for update in sorted(updates, key=lambda u: (u["from_seq"], u["to_seq"])):
            if update["round"]["seed"] != self.info["seed"] or update["recording"]["sha256"] != self.recording["sha256"]:
                raise ValueError("the update file is for another round")
            if update["to_seq"] <= self.last_seq:
                continue
            check_in_round(self.roles, update["changes"], update["events"])
            self.gaps += update["from_seq"] > self.last_seq
            self.changes += [change for change in update["changes"] if change["seq"] > self.last_seq]
            # A round file also holds views delivered after the round that were made while it was open.
            seen = {event["seq"] for event in self.events}
            self.events += [event for event in update["events"] if event["seq"] > self.last_seq and event["seq"] not in seen]
            self.last_seq = update["to_seq"]
            self.updates += 1

    def clips_at(self, seq: int | None = None) -> dict[str, dict]:
        """Each round clip as it was after event ``seq`` (by default, after every change known)."""
        clips = {clip_id: {k: v for k, v in clip.items() if k != "score"} for clip_id, clip in self.start.items()}
        for change in self.changes:
            if seq is not None and change["seq"] > seq:
                break
            for clip_id, clip in change["after"].items():
                if clip is None:
                    clips.pop(clip_id, None)
                else:
                    clips[clip_id] = clip
        return dict(sorted(clips.items(), key=lambda pair: _clip_order(pair[0])))

    def score(self, clip_id: str) -> float | None:
        """A clip's Likely keep score when the file was written; a clip split off later takes its SRT line's."""
        clip = self.start.get(clip_id) or self.start.get(clip_id.split("-")[0]) or {}
        return clip.get("score")

    def undone(self, until: int | None = None) -> set[int]:
        """The changes undone by changes up to event ``until`` (by default, by every change known)."""
        return {seq for change in self.changes if until is None or change["seq"] <= until
                for seq in change.get("undoes") or []}

    def file_clips(self) -> list[dict]:
        """Each round clip as the round ended: its original range, role, score, and outcome.

        The same list every time, so matches found in it can be told apart by identity.
        """
        if self._file_clips is not None:
            return self._file_clips
        clips = []
        for clip_id, clip in self.clips_at(self.end_seq).items():
            index = clip_index(clip_id)
            clips.append({"clip_id": clip_id, "index": index, "start_ms": time_ms(clip["original_start"]),
                          "end_ms": time_ms(clip["original_end"]), "role": self.roles[str(index)],
                          "score": self.score(clip_id), "outcome": outcome(clip["status"])})
        self._file_clips = clips
        return clips

    def times(self) -> dict[str, dict[str, int]]:
        """Milliseconds per stage on each round clip while the round was open."""
        item = {"started": self.info.get("started"), "completed": {"t": self.info.get("ended")}, "roles": self.roles}
        # Views count by when they were made, not when they were stored, as in the round's summary.
        events = self.events
        index = {event["clip"]: clip_index(event["clip"]) for event in events}
        times = clip_times(item, index, [event for event in events if not event.get("synthetic")])
        for event in events:
            # A version 1 file's time was already cut to the round; its synthetic views count whole.
            if event.get("synthetic") and event["type"] == "view" and event.get("stage") in STAGES:
                clip = times.setdefault(event["clip"], dict.fromkeys(STAGES, 0))
                clip[event["stage"]] += event["dwell_ms"]
        return times

    def review_marks(self) -> dict[str, dict]:
        """Per round clip, while the round was open: whether its decision flipped between kept and
        rejected (``corrected``), and how many of its changes were undone (``undone``)."""
        undone = self.undone(self.end_seq)
        statuses: dict[str, list[str]] = {clip_id: [clip["status"]] for clip_id, clip in self.start.items()}
        marks: dict[str, dict] = {}
        for change in self.changes:
            if change["seq"] > self.end_seq:
                break
            for clip_id, clip in change["after"].items():
                mark = marks.setdefault(clip_id, {"corrected": False, "undone": 0})
                if change["seq"] in undone:
                    mark["undone"] += 1
                elif clip is not None and not change.get("synthetic"):
                    statuses.setdefault(clip_id, []).append(clip["status"])
        for clip_id, seen in statuses.items():
            decided = {outcome(status) for status in seen if status != "pending"}
            marks.setdefault(clip_id, {"corrected": False, "undone": 0})["corrected"] = {"kept", "rejected"} <= decided
        return marks


Fit = tuple[float, float]


def match_clips(file_clips: Sequence[dict], clips: Sequence[tuple[int, int, int]]) -> dict[int, tuple[Fit, dict]]:
    """Map SRT indexes here, from ``clips`` as (index, start_ms, end_ms), to the file clip each overlaps most.

    Clips are matched by time, not index, so a project cut into different clips still finds them.
    Each match comes with its fit: the overlap as a share of the shorter clip, then as a share of
    both clips together, which breaks ties between nested clips in favor of the same range. Several
    clips here can match one file clip when this project cut it into parts.
    """
    ordered = sorted(file_clips, key=lambda clip: clip["start_ms"])
    starts = [clip["start_ms"] for clip in ordered]
    matches: dict[int, tuple[Fit, dict]] = {}
    for index, start, end in clips:
        position = max(0, bisect.bisect_left(starts, start) - 1)
        while position < len(ordered) and ordered[position]["start_ms"] < end:
            clip = ordered[position]
            overlap = min(end, clip["end_ms"]) - max(start, clip["start_ms"])
            shorter = min(end - start, clip["end_ms"] - clip["start_ms"])
            union = max(end, clip["end_ms"]) - min(start, clip["start_ms"])
            fit = (overlap / shorter if shorter > 0 else 0.0, overlap / union if union > 0 else 0.0)
            if fit[0] >= MIN_OVERLAP and fit > matches.get(index, ((0.0, 0.0), {}))[0]:
                matches[index] = (fit, clip)
            position += 1
    return matches


def imported_round(history: RoundHistory, matches: dict[int, tuple[Fit, dict]], number: int, file_name: str) -> dict:
    """A finished round here built from a round file's clips matched by ``match_clips``.

    Each file clip was one decision, so it counts once: its outcome goes to the clip here that
    overlaps it most, other clips here cut from it are only ``covered`` (left out of later rounds
    if it was decided, without counting as keepers or labels), and the round's counts and random
    labels come from the file's clips with the file's scores, not from the clips here.
    """
    info = history.info
    file_clips = history.file_clips()
    stage_ms = dict.fromkeys(STAGES, 0)
    for clip in history.times().values():
        for stage in STAGES:
            stage_ms[stage] += clip[stage]
    matched_clips = {id(clip) for _, clip in matches.values()}
    best: dict[int, tuple[Fit, int]] = {}
    for index, (fit, clip) in sorted(matches.items()):
        if fit > best.get(id(clip), ((0.0, 0.0), 0))[0]:
            best[id(clip)] = (fit, index)
    primary = {index for _, index in best.values()}
    return {
        "number": number, "size": len(file_clips), "pool": info.get("pool"), "total": info.get("total"),
        "random_share": info.get("random_share", 0), "seed": info["seed"], "score_version": info.get("score_version"),
        "sampling": info.get("sampling", 1), "random_chance": info.get("random_chance"),
        "top": [], "random": [],
        "roles": {str(index): clip["role"] for index, (_, clip) in matches.items()},
        "outcomes": {str(index): clip["outcome"] for index, (_, clip) in matches.items() if index in primary},
        "covered": sorted(index for index, (_, clip) in matches.items()
                          if index not in primary and clip["outcome"] != "unfinished"),
        "file_clips": [{"role": clip["role"], "score": clip["score"], "outcome": clip["outcome"]} for clip in file_clips],
        "started": info.get("started"),
        "completed": {"t": info.get("ended") or info.get("started"), "unprocessed": info.get("unprocessed") or 0},
        "stage_ms": stage_ms,
        "imported": {"file": file_name, "number": info["number"], "clips": len(file_clips),
                     "unmatched": sum(1 for clip in file_clips if id(clip) not in matched_clips)},
    }
