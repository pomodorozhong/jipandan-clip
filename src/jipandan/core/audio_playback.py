"""Audio playback backends for previewing clips."""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import threading
import time
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


class MpvPlaybackMonitor:
    """Track mpv playback position via JSON IPC (``time-pos``)."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        socket_path: Path,
        temp_dir: Path,
    ) -> None:
        self._process = process
        self._socket_path = socket_path
        self._temp_dir = temp_dir
        self._stop = threading.Event()
        self._time_pos: float | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="mpv-playback-monitor",
            daemon=True,
        )
        self._thread.start()

    def time_pos(self) -> float | None:
        with self._lock:
            return self._time_pos

    def close(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=0.2)
        except RuntimeError:
            pass
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
        except OSError:
            pass
        try:
            if self._temp_dir.exists():
                self._temp_dir.rmdir()
        except OSError:
            pass

    def _run(self) -> None:
        sock: socket.socket | None = None
        try:
            deadline = time.monotonic() + 3.0
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._process.poll() is not None:
                    return
                if self._socket_path.exists():
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(0.2)
                        sock.connect(str(self._socket_path))
                        break
                    except OSError:
                        if sock is not None:
                            sock.close()
                            sock = None
                time.sleep(0.05)
            if sock is None:
                return
            sock.sendall(
                b'{"command":["observe_property",1,"time-pos"]}\n'
            )
            while not self._stop.is_set():
                if self._process.poll() is not None:
                    return
                try:
                    payload = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not payload:
                    return
                for line in payload.splitlines():
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if (
                        message.get("event") == "property-change"
                        and message.get("name") == "time-pos"
                    ):
                        data = message.get("data")
                        if isinstance(data, (int, float)):
                            with self._lock:
                                self._time_pos = float(data)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


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

    def spawn_play_preview_monitored(
        self, input_audio: Path, start: str, duration: str
    ) -> tuple[subprocess.Popen[bytes], MpvPlaybackMonitor]:
        temp_dir = Path(tempfile.mkdtemp(prefix="jipandan-mpv-"))
        socket_path = temp_dir / "ipc.sock"
        process = subprocess.Popen(
            self._mpv_cmd(
                f"--input-ipc-server={socket_path}",
                f"--start={start}",
                f"--length={duration}",
                str(input_audio),
            )
        )
        monitor = MpvPlaybackMonitor(process, socket_path, temp_dir)
        return process, monitor

    def spawn_play_file(self, path: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen(self._mpv_cmd(str(path)))


default_audio_playback: AudioPlayback = MpvAudioPlayback()
