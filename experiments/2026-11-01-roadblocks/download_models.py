"""Download the pinned model checkpoints and verify them against model-revisions.json.

Each model is fetched at its exact Hugging Face commit and then checked: the SHA-256 of
``model.safetensors`` and of every custom ``*.py`` file must match the values recorded when the
scores were produced. Review the custom code before running it: the scorers load it with
``trust_remote_code``. Needs the ``inference`` dependency group.

    uv run --group inference python download_models.py --dest <models-dir> d1-2B d1-Omni-2B LFM3-1.7B
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

PATTERNS = ["*.py", "*.json", "*.jinja", "LICENSE", "README.md", "*.safetensors"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(folder: Path, pin: dict) -> list[str]:
    problems = []
    if digest(folder / "model.safetensors") != pin["checkpoint_sha256"]:
        problems.append("model.safetensors differs")
    code = {p.name: digest(p) for p in sorted(folder.glob("*.py"))}
    if code != pin["custom_code_sha256"]:
        problems.append("custom code differs: " + ", ".join(sorted(set(code) ^ set(pin["custom_code_sha256"])
                        | {k for k in code if code[k] != pin["custom_code_sha256"].get(k)})))
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("models", nargs="+")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--pins", type=Path, default=Path(__file__).with_name("model-revisions.json"))
    args = parser.parse_args()
    pins = json.loads(args.pins.read_text())["models"]
    failed = False
    for name in args.models:
        pin = pins[name]
        folder = args.dest / name
        snapshot_download(pin["repo"], revision=pin["revision"], local_dir=folder, allow_patterns=PATTERNS)
        problems = verify(folder, pin)
        print(name, pin["revision"], "OK" if not problems else "; ".join(problems), flush=True)
        failed |= bool(problems)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
