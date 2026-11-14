"""Measure the application's current clip features for every recording in a config file.

The config is a JSON list of {name, session, audio, words}: the reviewed session JSON (legacy
recordings), the full recording, and the Whisper word JSON whose segments carry
``no_speech_prob``. The generated 0903 recording is read from its frozen database snapshot
instead. Needs ffmpeg on PATH and the repository's ``src`` on PYTHONPATH.

Each ``<name>.pipeline-features.json`` gets a ``<name>.pipeline-features.source.json`` beside it
holding the SHA-256 of the inputs it was measured from and, for a measured recording, the ffmpeg
build that decoded it. An existing feature file is reused only when that fingerprint matches the
current inputs. Otherwise the command stops before measuring anything; pass --regenerate to
measure those recordings again. A feature file from before fingerprints existed has none:
--adopt records the current inputs as its fingerprint without measuring, for files known to have
been measured from them.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import sqlite3
import subprocess
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from jipandan.core.clip_features import CLIP_FEATURES_VERSION, compute_clip_features
from jipandan.core.srt import srt_time_to_seconds

SNAPSHOT_FIELDS = ("peak_db", "mid_share_db", "bass_share_db", "no_speech_prob")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_clips(snapshot: Path) -> list[tuple[str, str]]:
    # Read-only, through SQLite: a snapshot copied with its write-ahead log reads the same rows.
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as con:
        return list(con.execute("select clip_id,data from clip"))


@functools.cache
def ffmpeg_version() -> str:
    """First line of ``ffmpeg -version``: builds decode to slightly different samples."""
    return subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]


def fingerprint(name: str, cfg: dict, snapshot: Path) -> dict:
    """What a recording's features were measured from; equal fingerprints mean equal inputs."""
    if name == "0903":
        rows = json.dumps(sorted(snapshot_clips(snapshot)), ensure_ascii=False).encode()
        return {"recording": name, "clip_features_version": CLIP_FEATURES_VERSION,
                "sha256": {"snapshot_clips": hashlib.sha256(rows).hexdigest()}}
    sources = {key: file_sha256(Path(cfg[key])) for key in ("session", "audio", "words")}
    return {"recording": name, "clip_features_version": CLIP_FEATURES_VERSION, "ffmpeg": ffmpeg_version(),
            "sha256": sources}


def differences(recorded: dict, current: dict) -> str:
    """Which parts of two fingerprints differ, in words for the person running the command."""
    names = {"clip_features_version": "the clip-feature version", "ffmpeg": "the ffmpeg build",
             "recording": "the recording name", "snapshot_clips": "the snapshot's clips"}
    old, new = ({**f, **f.get("sha256", {})} for f in (recorded, current))
    changed = [key for key in sorted(old.keys() | new.keys()) if key != "sha256" and old.get(key) != new.get(key)]
    return ", ".join(names.get(key, f"the {key} file") for key in changed)


def source_path(dest: Path) -> Path:
    return dest.with_name(dest.name.removesuffix(".json") + ".source.json")


def seconds(value: str) -> float:
    return srt_time_to_seconds(value.replace(".", ","))


def snapshot_features(snapshot: Path) -> list[dict]:
    clips = [json.loads(data) for _, data in snapshot_clips(snapshot)]
    return [{"id": f"0903:{c['index']}" + (f".{c['suffix']}" if c["suffix"] else ""),
             **{k: c.get(k) for k in SNAPSHOT_FIELDS}} for c in clips]


def session_features(name: str, cfg: dict) -> list[dict]:
    clips = [c for c in json.loads(Path(cfg["session"]).read_text())["candidates"] if not c.get("suffix")]
    spans = [(seconds(c["original_start"]), seconds(c["original_end"])) for c in clips]
    segments = json.loads(Path(cfg["words"]).read_text())["segments"]
    started = time.perf_counter()
    features = compute_clip_features(Path(cfg["audio"]), spans)
    print(name, "seconds", time.perf_counter() - started, flush=True)
    out = []
    for clip, (start, end), feature in zip(clips, spans, features):
        # The Whisper segment that overlaps this clip most (ties: closest start).
        best = max(segments, key=lambda s: (min(end, s["end"]) - max(start, s["start"]),
                                            -abs(start - s["start"])))
        out.append({"id": f"{name}:{clip['index']}", **(asdict(feature) if feature else {}),
                    "no_speech_prob": best.get("no_speech_prob")})
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True, help="frozen 0903 .jipandan.db copy")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--regenerate", action="store_true",
                        help="measure again every recording whose existing feature file does not match "
                             "its current inputs, instead of stopping")
    parser.add_argument("--adopt", action="store_true",
                        help="record the current inputs as the fingerprint of every existing feature file "
                             "that has none, without measuring; only for files known to come from them. "
                             "Run it with the ffmpeg build that measured them, which it records. "
                             "With --regenerate too, such a file is adopted, not measured again")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Decide for every recording before measuring any, so a long run cannot stop halfway.
    plan, stale = [], []
    for cfg in json.loads(args.config.read_text()):
        name = cfg["name"]
        dest = args.out_dir / f"{name}.pipeline-features.json"
        current = fingerprint(name, cfg, args.snapshot)
        recorded = json.loads(source_path(dest).read_text()) if source_path(dest).exists() else None
        if dest.exists() and recorded == current:
            action = "reused"
        elif not dest.exists():
            action = "generated"
        elif recorded is None and args.adopt:
            action = "adopted"
        else:
            action = "regenerated"
            stale.append(f"{dest.name}: " + ("no recorded input fingerprint" if recorded is None else
                                             "measured from different inputs: " + differences(recorded, current)))
        plan.append((name, cfg, dest, current, action))
    if stale and not args.regenerate:
        parser.exit(1, "Existing feature files cannot be reused:\n  " + "\n  ".join(stale)
                    + "\nPass --regenerate to measure them again, or use a new --out-dir. For a file with no "
                    "recorded fingerprint that you know was measured from the current inputs, --adopt records "
                    "them without measuring.\n")

    for name, cfg, dest, current, action in plan:
        if action == "reused":
            print(name, "reused", dest.name, flush=True)
            continue
        if action == "adopted":
            source_path(dest).write_text(json.dumps(current, indent=2) + "\n")
            print(name, "adopted", dest.name, flush=True)
            continue
        # Without its fingerprint a feature file is never reused, so drop the old one first.
        source_path(dest).unlink(missing_ok=True)
        out = snapshot_features(args.snapshot) if name == "0903" else session_features(name, cfg)
        # Under its final name only once complete: an interrupted run must not leave a truncated
        # feature file without a fingerprint, which --adopt would then accept.
        partial = dest.with_name(dest.name + ".part")
        try:
            partial.write_text(json.dumps(out, indent=2))
            partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)
        source_path(dest).write_text(json.dumps(current, indent=2) + "\n")
        print(name, action, len(out), flush=True)


if __name__ == "__main__":
    main()
