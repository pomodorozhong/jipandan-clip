"""Audio playback backends for previewing clips."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

# Play audio without opening a player window (e.g. album-art UI on macOS).
MPV_BASE = ["--no-terminal", "--no-video", "--force-window=no", "--audio-display=no"]


class AudioPlayback(ABC):
    """Play audio files or segments without coupling callers to a specific player."""

    @abstractmethod
    def play_preview(
        self, input_audio: Path, start: str, duration: str
    ) -> None:
        """Block until a segment of ``input_audio`` has finished playing."""

    @abstractmethod
    def play_file(self, path: Path) -> None:
        """Block until ``path`` has finished playing."""

    @abstractmethod
    def spawn_play_preview(
        self, input_audio: Path, start: str, duration: str
    ) -> subprocess.Popen[bytes]:
        """Start playing a segment; caller owns the returned process."""

    @abstractmethod
    def spawn_play_file(self, path: Path) -> subprocess.Popen[bytes]:
        """Start playing a file; caller owns the returned process."""

    @abstractmethod
    def cli_base_args(self) -> list[str]:
        """Base CLI arguments for notebook shell commands (e.g. ``!mpv ...``)."""


class MpvAudioPlayback(AudioPlayback):
    def __init__(self, base_args: list[str] | None = None) -> None:
        self._base = list(base_args if base_args is not None else MPV_BASE)

    def cli_base_args(self) -> list[str]:
        return list(self._base)

    def _mpv_cmd(self, *extra: str) -> list[str]:
        return ["mpv", *self._base, *extra]

    def play_preview(
        self, input_audio: Path, start: str, duration: str
    ) -> None:
        subprocess.run(
            self._mpv_cmd(
                f"--start={start}",
                f"--length={duration}",
                str(input_audio),
            ),
            check=True,
        )

    def play_file(self, path: Path) -> None:
        subprocess.run(self._mpv_cmd(str(path)), check=True)

    def spawn_play_preview(
        self, input_audio: Path, start: str, duration: str
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            self._mpv_cmd(
                f"--start={start}",
                f"--length={duration}",
                str(input_audio),
            )
        )

    def spawn_play_file(self, path: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen(self._mpv_cmd(str(path)))


default_audio_playback: AudioPlayback = MpvAudioPlayback()
