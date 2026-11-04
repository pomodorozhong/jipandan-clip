"""Measure the application's current clip features for every recording in a config file.

The config is a JSON list of {name, session, audio, words}: the reviewed session JSON (legacy
recordings), the full recording, and the Whisper word JSON whose segments carry
``no_speech_prob``. The generated 0903 recording is read from its frozen database snapshot
instead. Needs ffmpeg on PATH and the repository's ``src`` on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from jipandan.core.clip_features import compute_clip_features
from jipandan.core.srt import srt_time_to_seconds

SNAPSHOT_FIELDS = ("peak_db", "mid_share_db", "bass_share_db", "no_speech_prob")


def seconds(value: str) -> float:
    return srt_time_to_seconds(value.replace(".", ","))


def snapshot_features(snapshot: Path) -> list[dict]:
    with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as con:
        clips = [json.loads(data) for (data,) in con.execute("select data from clip")]
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
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for cfg in json.loads(args.config.read_text()):
        name = cfg["name"]
        dest = args.out_dir / f"{name}.pipeline-features.json"
        if dest.exists():
            continue
        out = snapshot_features(args.snapshot) if name == "0903" else session_features(name, cfg)
        dest.write_text(json.dumps(out, indent=2))
        print(name, "done", len(out), flush=True)


if __name__ == "__main__":
    main()
