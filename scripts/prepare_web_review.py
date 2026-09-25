"""Make a disposable 0526 review session without changing the original files."""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def copy_file(source: Path, destination: Path) -> None:
    if sys.platform == "darwin":
        try:
            subprocess.run(["cp", "-c", str(source), str(destination)], check=True)
            return
        except subprocess.CalledProcessError:
            pass
    shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Replace an existing disposable test copy")
    parser.add_argument("--name", default="web-review-0526", help="Test folder name under tmp/")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", args.name):
        parser.error("--name must be a simple lowercase folder name")
    root = Path(__file__).resolve().parents[1]
    source = root / "raw"
    target = root / "tmp" / args.name
    target.mkdir(parents=True, exist_ok=True)
    paths = [source / f"0526{suffix}" for suffix in (".mp3", ".srt", ".jipandan.json")]
    if not args.reset and any((target / path.name).exists() for path in paths):
        parser.error(f"{target} already contains a review copy; use --reset to replace it")
    for path in paths:
        copy_file(path, target / path.name)
    session_path = target / "0526.jipandan.json"
    data = json.loads(session_path.read_text(encoding="utf-8"))
    data["audio"] = str((target / "0526.mp3").resolve())
    data["srt"] = str((target / "0526.srt").resolve())
    data["clip_dir"] = str((target / "exports").resolve())
    data["revision"] = 0
    for candidate in data["candidates"]:
        if candidate["index"] <= 20:
            candidate["status"] = "pending"
    session_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(target / "0526.mp3")


if __name__ == "__main__":
    main()
