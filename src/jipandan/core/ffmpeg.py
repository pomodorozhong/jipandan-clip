import re
import os
import shutil
import subprocess
import tempfile
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jipandan.core.models import ClipCandidate
from jipandan.core.srt import srt_time_to_seconds

ExportMode = Literal["as_is", "trim_edges", "trim_all"]

DEFAULT_START_THRESHOLD_DB = -40.0
DEFAULT_STOP_THRESHOLD_DB = -50.0


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


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


# Seeking: placing -ss after -i decodes from the start of the file, which is exact
# but takes ~17 s for a clip 6 hours into a stream. Placing it before -i jumps
# straight there; with a short pre-roll that is then trimmed, the result is
# sample-identical on files whose demuxer seeks exactly (such as CBR MP3). Each
# file is checked once, and files that fail fall back to the slow exact seek.
_SEEK_PREROLL_SECONDS = 0.5
_SEEK_CHECK_AT_SECONDS = 600.0
_fast_seek_checks: dict[tuple[str, int, int], bool] = {}


def _decode_probe(audio: Path, before: list[str], after: list[str]) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", *before, "-i", str(audio), *after, "-t", "1", "-ac", "1",
         "-ar", "16000", "-f", "f32le", "pipe:1"],
        check=True, capture_output=True,
    ).stdout


def fast_seek_is_exact(audio: Path, duration_seconds: float | None = None) -> bool:
    """Whether jumping into ``audio`` lands on exactly the same samples as decoding up to it."""
    stat = audio.stat()
    key = (str(audio.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _fast_seek_checks:
        duration = duration_seconds if duration_seconds is not None else probe_duration_seconds(audio)
        at = min(_SEEK_CHECK_AT_SECONDS, max(0.0, duration / 2 - 1))
        if at <= _SEEK_PREROLL_SECONDS:
            _fast_seek_checks[key] = True
        else:
            try:
                exact = _decode_probe(audio, [], ["-ss", f"{at:.6f}"])
                fast = _decode_probe(
                    audio, ["-ss", f"{at - _SEEK_PREROLL_SECONDS:.6f}"], ["-ss", f"{_SEEK_PREROLL_SECONDS:.6f}"],
                )
            except subprocess.CalledProcessError:
                _fast_seek_checks[key] = False
            else:
                _fast_seek_checks[key] = len(exact) == len(fast) and _max_abs_difference(exact, fast) < 1e-4
    return _fast_seek_checks[key]


def _max_abs_difference(first: bytes, second: bytes) -> float:
    import numpy as np

    a = np.frombuffer(first[: len(first) // 4 * 4], np.float32)
    b = np.frombuffer(second[: len(second) // 4 * 4], np.float32)
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def seek_arguments(audio: Path, start_seconds: float) -> tuple[list[str], list[str]]:
    """FFmpeg arguments placed before and after ``-i`` to start exactly at ``start_seconds``."""
    if start_seconds <= 0:
        return [], []
    if fast_seek_is_exact(audio):
        preroll = min(start_seconds, _SEEK_PREROLL_SECONDS)
        return ["-ss", f"{start_seconds - preroll:.6f}"], ["-ss", f"{preroll:.6f}"]
    return [], ["-ss", f"{start_seconds:.6f}"]


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
    before, after = seek_arguments(input_audio, srt_time_to_seconds(start.replace(".", ",")))
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "quiet",
        *before,
        "-i",
        str(input_audio),
        *after,
        "-t",
        duration,
        "-q:a",
        "2",
    ]
    for key, value in metadata:
        cmd.extend(["-metadata", f"{key}={value}"])
    cmd.append(str(out_mp3))
    _run(cmd)


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
    *,
    replace_existing: bool = False,
) -> Path:
    """Copy a preview-rendered clip into ``clip_dir`` with final metadata."""
    clip_dir.mkdir(parents=True, exist_ok=True)
    basename = export_basename(input_audio, candidate.filename_token, export_title)
    final_clip = clip_dir / f"{basename}.mp3"
    if source.resolve() == final_clip.resolve():
        return final_clip
    temporary_clip = clip_dir / f".{basename}.{uuid4().hex}.mp3"
    try:
        _run([
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
            str(temporary_clip),
        ])
        final_clip = _publish_clip(temporary_clip, final_clip, replace_existing=replace_existing)
    finally:
        temporary_clip.unlink(missing_ok=True)
    return final_clip


def _publish_clip(source: Path, final_clip: Path, *, replace_existing: bool) -> Path:
    """Publish a complete MP3, choosing a new filename on collision."""
    if replace_existing:
        os.replace(source, final_clip)
        return final_clip
    candidate = final_clip
    number = 2
    while True:
        try:
            os.link(source, candidate)
            return candidate
        except FileExistsError:
            candidate = final_clip.with_name(f"{final_clip.stem} ({number}){final_clip.suffix}")
            number += 1


def render_export_preview(
    input_audio: Path,
    candidate: ClipCandidate,
    options: ExportOptions,
    output: Path,
) -> None:
    """Render one immutable export preview without publishing a clip."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jipandan-preview-") as directory:
        source = Path(directory) / "source.mp3"
        _extract_audio_slice(input_audio, candidate.start, candidate.duration, source)
        audio_filter = _audio_filter_for_options(options)
        if audio_filter is None:
            shutil.copy2(source, output)
            return
        rendered = Path(directory) / "rendered.mp3"
        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
             "-af", audio_filter, str(rendered)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[-500:] or "FFmpeg could not render the preview")
        os.replace(rendered, output)
