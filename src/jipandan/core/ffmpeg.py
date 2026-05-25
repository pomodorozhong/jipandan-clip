import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jipandan.core.models import ClipCandidate

ExportMode = Literal["as_is", "trim_edges", "trim_all"]

DEFAULT_START_THRESHOLD_DB = -40.0
DEFAULT_STOP_THRESHOLD_DB = -50.0
DEFAULT_TRIM_ALL_THRESHOLD_DB = -30.0


@dataclass(frozen=True)
class ExportOptions:
    mode: ExportMode
    start_threshold_db: float = DEFAULT_START_THRESHOLD_DB
    stop_threshold_db: float = DEFAULT_STOP_THRESHOLD_DB


def build_silence_filter(
    *,
    stop_periods: int,
    start_threshold_db: float,
    stop_threshold_db: float,
    stop_duration: str,
    trim_middle: bool,
) -> str:
    parts = [
        "start_periods=1",
        "start_duration=0.1",
        "start_silence=0.2",
        f"start_threshold={start_threshold_db:g}dB",
        f"stop_periods={stop_periods}",
        f"stop_duration={stop_duration}",
        f"stop_threshold={stop_threshold_db:g}dB",
    ]
    if trim_middle:
        parts.extend(["start_mode=any", "stop_mode=any"])
    return "silenceremove=" + ":".join(parts)


SILENCE_TRIM_EDGES_FILTER = build_silence_filter(
    stop_periods=1,
    start_threshold_db=DEFAULT_START_THRESHOLD_DB,
    stop_threshold_db=DEFAULT_STOP_THRESHOLD_DB,
    stop_duration="1",
    trim_middle=False,
)

SILENCE_TRIM_ALL_FILTER = build_silence_filter(
    stop_periods=-1,
    start_threshold_db=DEFAULT_TRIM_ALL_THRESHOLD_DB,
    stop_threshold_db=DEFAULT_TRIM_ALL_THRESHOLD_DB,
    stop_duration="0.2",
    trim_middle=True,
)

# Backwards-compatible alias used by notebooks.
SILENCE_REMOVE_FILTER = SILENCE_TRIM_EDGES_FILTER

# Play audio without opening an mpv window (e.g. album-art UI on macOS).
MPV_BASE = ["--no-terminal", "--no-video", "--force-window=no", "--audio-display=no"]


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def extract_preview(
    input_audio: Path,
    start: str,
    duration: str,
    out_mp3: Path,
) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(input_audio),
            "-ss",
            start,
            "-t",
            duration,
            "-c",
            "copy",
            str(out_mp3),
        ]
    )


WAVEFORM_PIXEL_SIZE = (800, 200)


def render_waveform(
    mp3: Path,
    out_png: Path,
    size: tuple[int, int] = WAVEFORM_PIXEL_SIZE,
) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(mp3),
            "-filter_complex",
            f"showwavespic=s={width}x{height}:colors=cyan",
            "-frames:v",
            "1",
            str(out_png),
        ]
    )


_INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|\n\r\t]+')


def _safe_filename(value: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", value).strip()
    return cleaned.strip(". ") or "untitled"


def export_basename(input_audio: Path, index: int, title: str) -> str:
    return f"{_safe_filename(input_audio.stem)}_{index:04d}_{_safe_filename(title)}"


def _audio_filter_for_options(options: ExportOptions) -> str | None:
    if options.mode == "as_is":
        return None
    if options.mode == "trim_all":
        return build_silence_filter(
            stop_periods=-1,
            start_threshold_db=options.start_threshold_db,
            stop_threshold_db=options.stop_threshold_db,
            stop_duration="0.2",
            trim_middle=True,
        )
    return build_silence_filter(
        stop_periods=1,
        start_threshold_db=options.start_threshold_db,
        stop_threshold_db=options.stop_threshold_db,
        stop_duration="1",
        trim_middle=False,
    )


def export_clip(
    input_audio: Path,
    candidate: ClipCandidate,
    clip_dir: Path,
    export_title: str | None = None,
    export_options: ExportOptions | None = None,
    tmp_dir: Path | None = None,
) -> Path:
    tmp_root = tmp_dir or Path("tmp")
    tmp_root.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    title = export_title if export_title is not None else candidate.title
    basename = export_basename(input_audio, candidate.index, title)
    tmp_clip = tmp_root / f"{basename}.mp3"
    final_clip = clip_dir / f"{basename}.mp3"

    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(input_audio),
            "-ss",
            candidate.start,
            "-t",
            candidate.duration,
            "-c",
            "copy",
            "-metadata",
            f"title={title}",
            "-metadata",
            f"TXXX:ORIGINAL_START_TIME={candidate.original_start}",
            str(tmp_clip),
        ]
    )
    options = export_options or ExportOptions(mode="trim_edges")
    audio_filter = _audio_filter_for_options(options)
    if audio_filter is None:
        shutil.copy2(tmp_clip, final_clip)
    else:
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "quiet",
                "-i",
                str(tmp_clip),
                "-af",
                audio_filter,
                str(final_clip),
            ]
        )
    return final_clip


def play_preview(input_audio: Path, start: str, duration: str) -> None:
    _run(
        [
            "mpv",
            *MPV_BASE,
            f"--start={start}",
            f"--length={duration}",
            str(input_audio),
        ]
    )


def play_file(path: Path) -> None:
    _run(["mpv", *MPV_BASE, str(path)])


def spawn_play_preview(
    input_audio: Path, start: str, duration: str
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "mpv",
            *MPV_BASE,
            f"--start={start}",
            f"--length={duration}",
            str(input_audio),
        ]
    )


def spawn_play_file(path: Path) -> subprocess.Popen:
    return subprocess.Popen(["mpv", *MPV_BASE, str(path)])
