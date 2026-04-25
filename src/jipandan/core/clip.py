import shlex
import subprocess
from pathlib import Path


def build_ffmpeg_clip_command(
    input_audio: Path,
    output_audio: Path,
    start: str,
    duration: str,
) -> str:
    return (
        f"ffmpeg -i {shlex.quote(str(input_audio))} "
        f"-ss {shlex.quote(start)} -t {shlex.quote(duration)} "
        f"-c copy {shlex.quote(str(output_audio))}"
    )


def run_ffmpeg_clip_command(
    input_audio: Path,
    output_audio: Path,
    start: str,
    duration: str,
) -> None:
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-i",
        str(input_audio),
        "-ss",
        start,
        "-t",
        duration,
        "-c",
        "copy",
        str(output_audio),
    ]
    subprocess.run(cmd, check=True)
