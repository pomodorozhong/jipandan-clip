"""Round backups: an additional copy of round and update files in the app's own data folder.

The files beside a recording go when its project folder goes, so each one is also copied to
``<root>/<audio sha256>/<round seed>/`` under its own name. The hash and seed come from the file, so
equal recording names, round numbers reused after Start over, and moved projects never collide.
Nothing here replaces, removes, or purges a file: a different file under a taken name is stored
beside it. ``manifest.jsonl`` in each folder says which file holds which name and where it came from.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from jipandan.core.round_files import file_kind, parse_round_file, parse_update_file

MANIFEST = "manifest.jsonl"
_SAFE_PART = re.compile(r"[0-9A-Za-z_-]+")


def _folder_part(value: str) -> str:
    """``value`` as one folder name; a file read from elsewhere must not choose a path."""
    if not _SAFE_PART.fullmatch(value):
        raise ValueError("the file's recording or round identity can't name a backup folder")
    return value


def round_backup_folder(root: Path, sha256: str, seed: str) -> Path:
    return root / _folder_part(sha256) / _folder_part(seed)


def _manifest(folder: Path) -> list[dict]:
    """The manifest's entries; a line cut short by an interrupted write is left out."""
    try:
        lines = (folder / MANIFEST).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("file"), str):
            entries.append(entry)
    return entries


def _sync_folder(folder: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(target: Path, content: bytes) -> None:
    """Write ``content`` to the new file ``target`` whole: a failure leaves no file under its name."""
    temporary = target.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.read_bytes() != content:
            raise OSError(f"The backup of {target.name} did not read back the same")
        # Unlike a rename, a link fails rather than replacing a file that appeared meanwhile.
        os.link(temporary, target)
        _sync_folder(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _append_manifest(folder: Path, entry: dict) -> None:
    path = folder / MANIFEST
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("ab") as handle:
        # An interrupted write can leave a last line without its end, which must not swallow this one.
        if handle.tell() and path.read_bytes()[-1:] != b"\n":
            line = "\n" + line
        handle.write(line.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def _stored_name(folder: Path, name: str, content: bytes, digest: str) -> tuple[str, bool]:
    """The file in ``folder`` for this content, and whether it still has to be written."""
    target = folder / name
    if not target.exists():
        return name, True
    if target.read_bytes() == content:
        return name, False
    other = target.with_name(f"{target.stem}.{digest[:12]}{target.suffix}")
    return other.name, not (other.exists() and other.read_bytes() == content)


def backup_file(root: Path, name: str, content: bytes, source: str | None = None) -> Path:
    """Keep a verified copy of the round or update file ``content``; returns where it is.

    Backing up the same content again changes nothing. Raises ValueError for content that isn't a
    valid round or update file, and OSError if it could not be written; earlier backups stay as they were.
    """
    try:
        raw = json.loads(content)
    except ValueError as exc:
        raise ValueError(f"{name} is not a JSON file") from exc
    data = parse_update_file(raw) if file_kind(raw) == "update" else parse_round_file(raw)
    folder = round_backup_folder(root, data["recording"]["sha256"], data["round"]["seed"])
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(name).name
    digest = hashlib.sha256(content).hexdigest()
    stored, write = _stored_name(folder, name, content, digest)
    if write:
        _publish(folder / stored, content)
    if not any(entry["name"] == name and entry["file"] == stored and entry.get("sha256") == digest
               for entry in _manifest(folder)):
        _append_manifest(folder, {
            "name": name, "file": stored, "kind": file_kind(raw), "sha256": digest, "size": len(content),
            "recording": data["recording"].get("name"), "round": data["round"]["number"],
            "source": source, "backed_up": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    return folder / stored


def backup_data(root: Path, name: str, data: object, source: str | None = None) -> Path:
    """``backup_file`` for parsed JSON, written the way ``write_round_file`` writes it."""
    return backup_file(root, name, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"), source)


def missing_backups(root: Path, sha256: str | None, seed: str, names: Sequence[str]) -> list[str]:
    """Which of a round's file ``names`` have no backup at their recorded size."""
    if sha256 is None:
        return list(names)
    try:
        folder = round_backup_folder(root, sha256, seed)
        entries = _manifest(folder)
    except (OSError, ValueError):
        return list(names)

    def backed_up(name: str) -> bool:
        for entry in entries:
            if entry["name"] != name:
                continue
            try:
                if (folder / entry["file"]).stat().st_size == entry.get("size"):
                    return True
            except OSError:
                continue
        return False

    return [name for name in names if not backed_up(name)]
