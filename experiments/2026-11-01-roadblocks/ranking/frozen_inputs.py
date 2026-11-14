"""Check the private frozen inputs against their recorded SHA-256 before computing from them.

``input-hashes.json`` lists every frozen input under ``frozen_inputs``. The legacy extraction
environment was never locked, so these exact files are the only definition of the inputs: a
different copy must stop the run, not quietly change the baseline.

A SQLite file is hashed as the one file it is. Rows still waiting in a write-ahead log beside it
(``<name>-wal``) would be read but not hashed, so a snapshot with a non-empty log is refused.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PINNED = Path(__file__).resolve().parents[1] / "input-hashes.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(inputs: dict[str, Path], pinned: Path = PINNED) -> dict[str, str]:
    """Return the hash of each named input, or raise when one is unpinned or differs."""
    recorded = json.loads(pinned.read_text()).get("frozen_inputs")
    if not isinstance(recorded, dict):
        raise ValueError(f"{pinned} has no frozen_inputs section, so it is not a recorded-hash file like this "
                         "experiment's input-hashes.json")
    hashes = {}
    for name, path in inputs.items():
        if name not in recorded:
            raise ValueError(f"{pinned.name} records no hash for the frozen input {name}")
        log = path.with_name(path.name + "-wal")
        if log.is_file() and log.stat().st_size:
            raise ValueError(f"{log.name} holds changes that the hash of {path.name} does not cover; "
                             "use a copy of the snapshot without its write-ahead log")
        hashes[name] = sha256(path)
        if hashes[name] != recorded[name]:
            raise ValueError(f"{path.name} is not the frozen input {name} recorded in {pinned.name}")
    return hashes
