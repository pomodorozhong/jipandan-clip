import subprocess
from pathlib import Path

from jipandan.core.models import ClipCandidate

SILENCE_REMOVE_FILTER = (
    "silenceremove=start_periods=1:start_duration=0.1:start_silence=0.2:start_threshold=-40dB:"
    "stop_periods=1:stop_duration=1:stop_threshold=-50dB"
)

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


def render_waveform(
    mp3: Path,
    out_png: Path,
    size: tuple[int, int] = (800, 200),
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


def _safe_filename(title: str) -> str:
    return title.replace("/", "_").replace("\\", "_")


def export_clip(
    input_audio: Path,
    candidate: ClipCandidate,
    clip_dir: Path,
    tmp_dir: Path | None = None,
) -> Path:
    tmp_root = tmp_dir or Path("tmp")
    tmp_root.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    safe_title = _safe_filename(candidate.title)
    tmp_clip = tmp_root / f"clip_{candidate.index:04d}_{safe_title}.mp3"
    final_clip = clip_dir / f"clip_{candidate.index:04d}_{safe_title}.mp3"

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
            f"title={candidate.title}",
            "-metadata",
            f"TXXX:ORIGINAL_START_TIME={candidate.original_start}",
            str(tmp_clip),
        ]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "quiet",
            "-i",
            str(tmp_clip),
            "-af",
            SILENCE_REMOVE_FILTER,
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
