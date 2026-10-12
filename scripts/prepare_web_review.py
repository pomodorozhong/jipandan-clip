"""Make a disposable copy of the 0526 recording for a fresh review session."""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
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
    parser.add_argument(
        "--name", default="web-review-0526",
        help="Test folder name under the system temporary directory",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", args.name):
        parser.error("--name must be a simple lowercase folder name")
    root = Path(__file__).resolve().parents[1]
    source = root / "raw"
    target = Path(tempfile.gettempdir()) / "jipandan" / args.name
    target.mkdir(parents=True, exist_ok=True)
    paths = [source / f"0526{suffix}" for suffix in (".mp3", ".srt")]
    database = target / "0526.jipandan.db"
    if not args.reset and (database.exists() or any((target / path.name).exists() for path in paths)):
        parser.error(f"{target} already contains a review copy; use --reset to replace it")
    # The GUI creates a fresh session database from the SRT when the copy is opened.
    for leftover in target.glob("0526.jipandan.db*"):
        leftover.unlink()
    for path in paths:
        copy_file(path, target / path.name)
    print(target / "0526.mp3")


if __name__ == "__main__":
    main()
