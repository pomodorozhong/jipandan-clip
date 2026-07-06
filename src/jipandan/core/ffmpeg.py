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


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def probe_duration_seconds(audio: Path) -> float:
    """Return the duration of ``audio`` in seconds as reported by ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _extract_audio_slice(
    input_audio: Path,
    start: str,
    duration: str,
    out_mp3: Path,
    *,
    metadata: tuple[tuple[str, str], ...] = (),
) -> None:
    """Extract an MP3 slice with sample-accurate seek (re-encoded)."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
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
        "-q:a",
        "2",
    ]
    for key, value in metadata:
        cmd.extend(["-metadata", f"{key}={value}"])
    cmd.append(str(out_mp3))
    _run(cmd)


def _extract_audio_slice_fast(
    input_audio: Path,
    start: str,
    duration: str,
    out_mp3: Path,
) -> None:
    """Extract an MP3 slice with fast input-side seek (re-encoded).

    Places ``-ss`` before ``-i`` so ffmpeg can jump into long files quickly.
    Boundaries may be slightly less accurate than :func:`_extract_audio_slice`.
    """
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-ss",
            start,
            "-i",
            str(input_audio),
            "-t",
            duration,
            "-q:a",
            "2",
            str(out_mp3),
        ]
    )


def extract_preview(
    input_audio: Path,
    start: str,
    duration: str,
    out_mp3: Path,
) -> None:
    """Extract a preview MP3 slice with sample-accurate seek (re-encoded)."""
    _extract_audio_slice(input_audio, start, duration, out_mp3)


def extract_preview_fast(
    input_audio: Path,
    start: str,
    duration: str,
    out_mp3: Path,
) -> None:
    """Extract a preview MP3 slice optimized for waveform rendering."""
    _extract_audio_slice_fast(input_audio, start, duration, out_mp3)

_INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|\n\r\t]+')


def _safe_filename(value: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", value).strip()
    return cleaned.strip(". ") or "untitled"


def export_basename(input_audio: Path, clip_token: str, title: str) -> str:
    return f"{_safe_filename(input_audio.stem)}_{clip_token}_{_safe_filename(title)}"


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


def publish_prebuilt_clip(
    source: Path,
    input_audio: Path,
    candidate: ClipCandidate,
    clip_dir: Path,
    export_title: str,
) -> Path:
    """Copy a preview-rendered clip into ``clip_dir`` with final metadata."""
    clip_dir.mkdir(parents=True, exist_ok=True)
    basename = export_basename(input_audio, candidate.filename_token, export_title)
    final_clip = clip_dir / f"{basename}.mp3"
    if source.resolve() == final_clip.resolve():
        return final_clip
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(source),
            "-c",
            "copy",
            "-metadata",
            f"title={export_title}",
            "-metadata",
            f"TXXX:ORIGINAL_START_TIME={candidate.original_start}",
            str(final_clip),
        ]
    )
    return final_clip


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
    basename = export_basename(input_audio, candidate.filename_token, title)
    tmp_clip = tmp_root / f"{basename}.mp3"
    final_clip = clip_dir / f"{basename}.mp3"

    _extract_audio_slice(
        input_audio,
        candidate.start,
        candidate.duration,
        tmp_clip,
        metadata=(
            ("title", title),
            ("TXXX:ORIGINAL_START_TIME", candidate.original_start),
        ),
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
