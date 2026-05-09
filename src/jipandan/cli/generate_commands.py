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
        safe_final_output = f'"{_escape_for_double_quotes(output_prefix)}${{title}}.mp3"'
        safe_tmp_output = f'"tmp/clip_{entry.index:04d}_${{title}}.mp3"'

        tmp_clip = f"tmp/clip_{entry.index:04d}.mp3"
        tmp_wave = f"tmp/clip_{entry.index:04d}.png"

        mpv_preview_cmd = (
            f"!mpv --no-terminal --start={shlex.quote(start_mpv)} "
            f"--length={shlex.quote(duration_str)} {safe_input}\n"
        )

        soundwave_cmd = (
            f'!ffmpeg -y -loglevel quiet -i {safe_input} -ss {shlex.quote(start_ffmpeg)} '
            f'-t {shlex.quote(duration_str)} -c copy "{tmp_clip}"\n'
            f'!ffmpeg -y -loglevel quiet -i "{tmp_clip}" -filter_complex '
            f'"showwavespic=s=800x200:colors=cyan" -frames:v 1 "{tmp_wave}"\n\n'
            "from IPython.display import Image, display\n"
            f'display(Image(filename="{tmp_wave}"))'
        )
        clip_cmd = (
            f"!title={safe_title}; ffmpeg -y -loglevel quiet -i {safe_input} -ss {shlex.quote(start_ffmpeg)} "
            f"-t {shlex.quote(duration_str)} -c copy "
            f'-metadata title="$title" {safe_tmp_output}\n'
            f"!title={safe_title}; ffmpeg -y -loglevel quiet -i {safe_tmp_output} "
            '-af silenceremove=start_periods=1:start_duration=0.02:start_silence=0.1:start_threshold=-40dB:'
            'stop_periods=1:stop_duration=0.2:stop_threshold=-50dB '
            f"{safe_final_output}\n"
            f'!title={safe_title}; ffmpeg -y -loglevel quiet -i {safe_final_output} '
            '-filter_complex "showwavespic=s=800x200:colors=cyan" -frames:v 1 '
            f'"tmp/clip_{entry.index:04d}.png"\n'
            f"!title={safe_title}; mpv --no-terminal {safe_final_output}\n"
            "\nfrom IPython.display import Image, display\n"
            f'display(Image(filename="tmp/clip_{entry.index:04d}.png"))'
        )

        cells.append(
            _markdown_cell(
                f"## {entry.index}: Preview - {entry.text}\n\n"
            )
        )
        cells.append(_code_cell(mpv_preview_cmd))

        cells.append(
            _markdown_cell(
                f"## {entry.index}: Clipping\n\n"
                f"- Start: `{entry.start}`\n"
                f"- End: `{entry.end}`\n"
                f"- Duration: `{duration_str}s`\n\n"
            )
        )
        cells.append(_code_cell(soundwave_cmd))
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
