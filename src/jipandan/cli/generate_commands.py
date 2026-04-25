import argparse
import json
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SubtitleEntry:
    index: int
    start: str
    end: str
    text: str


def _srt_time_to_seconds(value: str) -> float:
    hhmmss, millis = value.split(",")
    hours, minutes, seconds = hhmmss.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def _srt_time_to_ffmpeg(value: str) -> str:
    return value.replace(",", ".")


def _escape_for_double_quotes(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _parse_srt(srt_path: Path) -> list[SubtitleEntry]:
    raw_text = srt_path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in raw_text.split("\n\n") if block.strip()]
    entries: list[SubtitleEntry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        if " --> " not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split(" --> ", maxsplit=1)]
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        entries.append(SubtitleEntry(index=index, start=start, end=end, text=text))
    return entries


def _code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [f"{source}\n"],
    }


def _markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [f"{source}\n"],
    }


def _build_notebook(entries: list[SubtitleEntry], input_audio: Path, clip_dir: Path) -> dict:
    cells: list[dict] = []
    for entry in entries:
        start_seconds = _srt_time_to_seconds(entry.start)
        end_seconds = _srt_time_to_seconds(entry.end)
        duration_seconds = max(0.0, end_seconds - start_seconds)

        start_mpv = _srt_time_to_ffmpeg(entry.start)
        start_ffmpeg = start_mpv
        duration_str = f"{duration_seconds:.3f}"

        output_prefix = str(clip_dir / f"clip_{entry.index:04d}_")

        safe_input = shlex.quote(str(input_audio))
        safe_title = shlex.quote(entry.text)
        safe_output = f'"{_escape_for_double_quotes(output_prefix)}${{title}}.mp3"'

        preview_cmd = (
            f"!mpv --start={shlex.quote(start_mpv)} "
            f"--length={shlex.quote(duration_str)} {safe_input}"
        )
        clip_cmd = (
            f"!title={safe_title}; ffmpeg -y -i {safe_input} -ss {shlex.quote(start_ffmpeg)} "
            f"-t {shlex.quote(duration_str)} -c copy "
            f'-metadata title="$title" {safe_output}'
        )

        cells.append(
            _markdown_cell(
                f"## Clip {entry.index}: {entry.text}\n\n"
                f"- Start: `{entry.start}`\n"
                f"- End: `{entry.end}`\n"
                f"- Duration: `{duration_str}s`\n\n"
            )
        )
        cells.append(_code_cell(preview_cmd))
        cells.append(_code_cell(clip_cmd))

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Jupyter notebook that previews and clips each SRT segment."
    )
    parser.add_argument("input", type=Path, help="Input subtitle (.srt) file path.")
    parser.add_argument(
        "--audio",
        required=True,
        type=Path,
        help="Source audio file used by mpv/ffmpeg commands.",
    )
    parser.add_argument(
        "--clip-dir",
        type=Path,
        default=Path("clip"),
        help="Directory used by generated ffmpeg output paths.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(f"clip_commands_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ipynb"),
        help="Output notebook file path.",
    )
    args = parser.parse_args()

    entries = _parse_srt(args.input)
    if not entries:
        raise ValueError(f"No valid subtitle entries found in {args.input}")

    notebook = _build_notebook(entries, input_audio=args.audio, clip_dir=args.clip_dir)
    args.output.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
    print(f"Wrote notebook to: {args.output}")
    print(f"Generated commands for {len(entries)} subtitle segments.")


if __name__ == "__main__":
    main()
