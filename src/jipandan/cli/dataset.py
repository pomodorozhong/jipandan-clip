import argparse
import json
import sys
from pathlib import Path

from jipandan.core.datasets import build_dataset, write_dataset
from jipandan.core.round_files import file_kind


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _inputs(paths: list[Path]) -> list[tuple[str, object]]:
    """Each file named, and each round or update file directly in a folder named, as (file name, parsed JSON).

    A folder beside a recording also holds its other JSON files, such as snap points, so only round
    and update files are taken from folders; a file named directly is always reported.
    """
    files: list[tuple[str, object]] = []
    for path in paths:
        if path.is_dir():
            files += [(item.name, data) for item in sorted(path.glob("*.json"))
                      if file_kind(data := _read(item)) is not None]
        else:
            files.append((path.name, _read(path)))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build ranking, timing, and title datasets from round files and their update files.")
    parser.add_argument("inputs", type=Path, nargs="+", help="Round and update files, or folders holding them.")
    parser.add_argument("--out", type=Path, required=True, help="An empty or new folder for the dataset.")
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        sys.exit(f"{args.out} is not empty; choose an empty or new folder.")
    dataset = build_dataset(_inputs(args.inputs))
    write_dataset(args.out, dataset)
    manifest = dataset["manifest"]
    for entry in manifest["inputs"]:
        if not entry.get("used"):
            print(f"Skipped {entry['file']}: {entry.get('reason', 'not a round or update file')}")
    for task in ("ranking", "timing", "titles"):
        tally = manifest["counts"][task]
        left_out = ", ".join(f"{count} {reason}" for reason, count in tally.get("excluded", {}).items())
        print(f"{task}: {tally.get('examples', 0)} examples" + (f" ({left_out} left out)" if left_out else ""))
    labels = manifest["labels"]
    print(f"Random labels: {labels['random_draws']} from {labels['recordings']} recordings "
          f"(planning target {labels['target']})")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
