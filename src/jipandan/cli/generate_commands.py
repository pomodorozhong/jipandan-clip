import argparse
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from jipandan.core.srt import (
    SubtitleEntry,
    compute_duration,
    parse_srt,
    srt_time_to_ffmpeg,
)


CELLS_PER_CLIP = 5
NOTEBOOK_CONTROL_CELLS = 1
DEFAULT_MAX_CELLS_PER_NOTEBOOK = 2000


def _escape_for_double_quotes(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


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


def _control_cell() -> dict:
    return _code_cell("RUN_MPV_PREVIEW = False\nRUN_CLIP = False\n")


def _cells_for_entry(
    entry: SubtitleEntry, input_audio: Path, clip_dir: Path
) -> list[dict]:
    start_ffmpeg = srt_time_to_ffmpeg(entry.start)
    duration_str = compute_duration(entry.start, entry.end)

    output_prefix = str(clip_dir / f"clip_{entry.index:04d}_")

    safe_input = shlex.quote(str(input_audio))
    title_literal = json.dumps(entry.text, ensure_ascii=False)

    tmp_clip = f"tmp/clip_{entry.index:04d}.mp3"
    tmp_wave = f"tmp/clip_{entry.index:04d}.png"

    soundwave_cmd = (
        f"title{entry.index} = {title_literal}\n"
        f"timestamp{entry.index} = {json.dumps(start_ffmpeg)}\n"
        f"duration{entry.index} = {json.dumps(duration_str)}\n"
        f'!ffmpeg -y -loglevel quiet -i {safe_input} -ss $timestamp{entry.index} '
        f'-t $duration{entry.index} -c copy "{tmp_clip}"\n'
        f'!ffmpeg -y -loglevel quiet -i "{tmp_clip}" -filter_complex '
        f'"showwavespic=s=800x200:colors=cyan" -frames:v 1 "{tmp_wave}"\n\n'
        "from IPython.display import Image, display\n"
        f'display(Image(filename="{tmp_wave}"))'
    )

    mpv_preview_cmd = (
        "if RUN_MPV_PREVIEW:\n"
        f"    !mpv --no-terminal --start=$timestamp{entry.index} "
        f"--length=$duration{entry.index} {safe_input}\n"
    )

    clip_cmd = (
        "if RUN_CLIP:\n"
        f'    !ffmpeg -y -loglevel quiet -i {safe_input} -ss $timestamp{entry.index} -t $duration{entry.index} '
        f'-c copy -metadata title="$title{entry.index}" -metadata TXXX:ORIGINAL_START_TIME="{start_ffmpeg}" '
        f'"tmp/clip_{entry.index:04d}_{{title{entry.index}}}.mp3"\n'
        f'    !ffmpeg -y -loglevel quiet -i "tmp/clip_{entry.index:04d}_{{title{entry.index}}}.mp3" '
        '-af silenceremove=start_periods=1:start_duration=0.1:start_silence=0.2:start_threshold=-40dB:'
        'stop_periods=1:stop_duration=1:stop_threshold=-50dB '
        f'"{_escape_for_double_quotes(output_prefix)}{{title{entry.index}}}.mp3"\n'
        f'    !ffmpeg -y -loglevel quiet -i "{_escape_for_double_quotes(output_prefix)}{{title{entry.index}}}.mp3" '
        '-filter_complex "showwavespic=s=800x200:colors=cyan" -frames:v 1 '
        f'"tmp/clip_{entry.index:04d}.png"\n'
        f'    !mpv --no-terminal "{_escape_for_double_quotes(output_prefix)}{{title{entry.index}}}.mp3"\n'
        "\n    from IPython.display import Image, display\n"
        f'    display(Image(filename="tmp/clip_{entry.index:04d}.png"))'
    )

    return [
        _markdown_cell(f"## {entry.index}: Preview - {entry.text}\n\n"),
        _code_cell(soundwave_cmd),
        _code_cell(mpv_preview_cmd),
        _markdown_cell(f"## {entry.index}: Clipping"),
        _code_cell(clip_cmd),
    ]


def _notebook_metadata() -> dict:
    return {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python"},
    }


def _build_notebook(entries: list[SubtitleEntry], input_audio: Path, clip_dir: Path) -> dict:
    cells: list[dict] = [_control_cell()]
    for entry in entries:
        cells.extend(_cells_for_entry(entry, input_audio, clip_dir))
    return {
        "cells": cells,
        "metadata": _notebook_metadata(),
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _chunk_entries(
    entries: list[SubtitleEntry], max_cells_per_notebook: int
) -> list[list[SubtitleEntry]]:
    chunks: list[list[SubtitleEntry]] = []
    current: list[SubtitleEntry] = []
    cell_count = NOTEBOOK_CONTROL_CELLS
    for entry in entries:
        if cell_count + CELLS_PER_CLIP > max_cells_per_notebook and current:
            chunks.append(current)
            current = []
            cell_count = 0
        current.append(entry)
        cell_count += CELLS_PER_CLIP
    if current:
        chunks.append(current)
    return chunks


def _split_output_path(base_output: Path, part: int, timestamp: str) -> Path:
    raw_filename = base_output.stem
    return base_output.with_name(f"{raw_filename}_p{part}_{timestamp}.ipynb")


def _unsplit_output_path(base_output: Path, timestamp: str) -> Path:
    raw_filename = base_output.stem
    return base_output.with_name(f"{raw_filename}_{timestamp}.ipynb")


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
        default=None,
        help="Output notebook base path (default: {audio_stem}.ipynb).",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=DEFAULT_MAX_CELLS_PER_NOTEBOOK,
        metavar="N",
        help=(
            f"Maximum cells per notebook before splitting (default: {DEFAULT_MAX_CELLS_PER_NOTEBOOK}). "
            "Splits only at clip boundaries."
        ),
    )
    args = parser.parse_args()

    if args.max_cells < CELLS_PER_CLIP:
        parser.error(f"--max-cells must be at least {CELLS_PER_CLIP} (cells per clip).")

    base_output = args.output if args.output is not None else Path(f"{args.audio.stem}.ipynb")
    if base_output.suffix.lower() != ".ipynb":
        base_output = base_output.with_suffix(".ipynb")

    entries = parse_srt(args.input)
    if not entries:
        raise ValueError(f"No valid subtitle entries found in {args.input}")

    iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    entry_chunks = _chunk_entries(entries, max_cells_per_notebook=args.max_cells)
    max_clips_per_notebook = args.max_cells // CELLS_PER_CLIP
    written_paths: list[Path] = []

    for part, chunk in enumerate(entry_chunks, start=1):
        if len(entry_chunks) == 1:
            output_path = _unsplit_output_path(base_output, iso_ts)
        else:
            output_path = _split_output_path(base_output, part, iso_ts)
        notebook = _build_notebook(chunk, input_audio=args.audio, clip_dir=args.clip_dir)
        output_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        written_paths.append(output_path)

    for path in written_paths:
        print(f"Wrote notebook to: {path}")
    print(f"Generated commands for {len(entries)} subtitle segments.")
    if len(written_paths) > 1:
        print(
            f"Split into {len(written_paths)} notebooks "
            f"(max {args.max_cells} cells, {max_clips_per_notebook} clips each)."
        )


if __name__ == "__main__":
    main()
