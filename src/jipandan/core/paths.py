"""Application-owned filesystem locations and storage policy."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs


APP_NAME = "Jipandan"


@dataclass(frozen=True)
class AppPaths:
    """Platform-appropriate roots for persistent data, caches, and logs."""

    data_dir: Path
    cache_dir: Path
    log_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        directories = PlatformDirs(APP_NAME, appauthor=False)
        return cls(
            data_dir=Path(directories.user_data_dir),
            cache_dir=Path(directories.user_cache_dir),
            log_dir=Path(directories.user_log_dir),
        )

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def transcription_dir(self) -> Path:
        return self.data_dir / "transcriptions"

    @property
    def transcription_log_dir(self) -> Path:
        return self.log_dir / "transcriptions"

    @property
    def preview_dir(self) -> Path:
        return self.cache_dir / "web-previews"

    @property
    def waveform_dir(self) -> Path:
        return self.cache_dir / "waveforms"

    @property
    def fallback_export_dir(self) -> Path:
        return self.data_dir / "exports"


def get_app_paths() -> AppPaths:
    """Return the current user's application directories without creating them."""

    return AppPaths.default()


def _audio_key(audio: Path) -> str:
    return hashlib.sha256(str(audio.expanduser().resolve()).encode("utf-8")).hexdigest()[:16]


def default_export_dir(audio: Path, *, paths: AppPaths | None = None) -> Path:
    """Choose the export directory for a new session.

    New sessions keep exports beside the selected recording. If that location is
    unavailable, use an application-data fallback so read-only source folders do
    not prevent review and export. An explicit ``--clip-dir`` remains the caller's
    responsibility and is handled before this function is called.
    """

    source_dir = audio.expanduser().resolve().parent
    beside_audio = source_dir / "exports"
    try:
        beside_audio.mkdir(parents=True, exist_ok=True)
        if os.access(beside_audio, os.W_OK):
            return beside_audio.resolve()
    except OSError:
        pass

    selected_paths = paths or get_app_paths()
    fallback = selected_paths.fallback_export_dir / _audio_key(audio)
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(
            "The recording folder is not writable and the application export "
            "folder could not be created; choose a writable --clip-dir"
        ) from exc
    return fallback.resolve()


def resolve_export_dir(path: str | Path) -> Path:
    """Resolve and validate a user-selected export directory."""

    selected = Path(path).expanduser().resolve()
    try:
        selected.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Could not create export directory: {selected}") from exc
    if not selected.is_dir():
        raise OSError(f"Export path is not a directory: {selected}")
    if not os.access(selected, os.W_OK):
        raise OSError(f"Export directory is not writable: {selected}")
    return selected


def waveform_cache_dir(audio: Path, *, paths: AppPaths | None = None) -> Path:
    """Return a stable, collision-resistant cache directory for one recording."""

    selected_paths = paths or get_app_paths()
    return selected_paths.waveform_dir / _audio_key(audio)
