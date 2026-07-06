import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Label, Static

from jipandan.core import ffmpeg
from jipandan.core.audio_playback import AudioPlayback, default_audio_playback
from jipandan.core.ffmpeg import ExportOptions
from jipandan.core.models import ClipCandidate
from jipandan.tui.widgets.waveform import (
    GENERATING_PREVIEW_PLACEHOLDER,
    WaveformWidget,
    format_playback_remaining,
)

_PREVIEW_DIR = Path("tmp") / "preview"

DEFAULT_PRELOAD_EXPORT_OPTIONS = ExportOptions(mode="trim_edges")


@dataclass(frozen=True)
class ExportPreviewArtifacts:
    preview_path: Path
    preview_seconds: float
    as_is_seconds: float


@dataclass(frozen=True)
class ExportConfirm:
    title: str
    preview_path: Path | None
    wait_for_preview_path: Callable[[], Path | None] | None = None


def default_export_title(candidate: ClipCandidate) -> str:
    if candidate.last_export_title is not None:
        return candidate.last_export_title
    return candidate.title


def export_preview_key(
    candidate: ClipCandidate,
    options: ExportOptions,
    preview_title: str,
) -> tuple[object, ...]:
    return (
        candidate.clip_id,
        candidate.start,
        candidate.duration,
        options.mode,
        options.start_threshold_db,
        options.stop_threshold_db,
        preview_title,
    )


def build_export_preview_artifacts(
    audio: Path,
    candidate: ClipCandidate,
    options: ExportOptions,
    *,
    preview_dir: Path = _PREVIEW_DIR,
) -> ExportPreviewArtifacts:
    preview_title = default_export_title(candidate)
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = ffmpeg.export_clip(
        audio,
        candidate,
        preview_dir,
        export_title=preview_title,
        export_options=options,
    )
    preview_seconds = ffmpeg.probe_duration_seconds(preview_path)
    if options.mode == "as_is":
        as_is_seconds = preview_seconds
    else:
        as_is_seconds = float(candidate.duration)
    return ExportPreviewArtifacts(
        preview_path=preview_path,
        preview_seconds=preview_seconds,
        as_is_seconds=as_is_seconds,
    )


class ExportPreviewModal(ModalScreen[ExportConfirm | bool | None]):
    """Render export preview, collect the clip title, and start export on confirm.

    Dismissed value:
      * ``ExportConfirm`` – export with this title (and optional preview artifact)
      * ``False``         – back to the export mode picker (Esc while title is not focused)
      * ``None``          – abort export (Esc while editing the title)
    """

    BINDINGS = [
        Binding("escape", "cancel", "Back", show=False),
        Binding("enter", "focus_or_export", "Title / Export", show=True),
        Binding("space", "replay", "Replay", show=True),
        Binding("ctrl+c", "copy_title", "Copy", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ExportPreviewModal {
        align: center middle;
    }

    #export-preview-dialog {
        width: 90;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #export-preview-waveform {
        height: 12;
    }

    #export-title-input {
        margin-top: 1;
    }

    #export-preview-times {
        color: $text-muted;
    }

    #export-preview-info {
        height: 1;
        color: $text-muted;
    }

    #export-preview-status {
        height: 1;
        color: $text-muted;
    }

    #export-preview-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(
        self,
        audio: Path,
        candidate: ClipCandidate,
        options: ExportOptions,
        *,
        audio_playback: AudioPlayback | None = None,
        try_preloaded: Callable[[], ExportPreviewArtifacts | None] | None = None,
    ) -> None:
        super().__init__()
        self._audio = audio
        self._candidate = candidate
        self._options = options
        self._audio_playback = (
            audio_playback
            if audio_playback is not None
            else default_audio_playback
        )
        self._try_preloaded = try_preloaded
        self._preview_path: Path | None = None
        self._as_is_seconds: float | None = None
        self._preview_seconds: float | None = None
        self._playback_process: subprocess.Popen | None = None
        self._playback_end: float | None = None
        self._playback_duration: float | None = None
        self._playback_timer: Timer | None = None
        # Guard UI callbacks from worker threads after the modal is dismissed.
        self._is_active = False
        self._preview_generation = 0
        self._handoff_ready = threading.Event()
        self._handoff_artifacts: ExportPreviewArtifacts | None = None
        self._handoff_error: str | None = None

    @staticmethod
    def _format_times_line(candidate: ClipCandidate) -> str:
        return f"Start: {candidate.start}    End: {candidate.end}"

    @staticmethod
    def _format_seconds(seconds: float | None) -> str:
        if seconds is None:
            return "rendering…"
        return f"{seconds:.3f}s"

    @staticmethod
    def _format_delta(delta_seconds: float) -> str:
        sign = "+" if delta_seconds > 0 else ("-" if delta_seconds < 0 else "±")
        return f"Δ {sign}{abs(delta_seconds):.3f}s"

    def _format_info_line(
        self,
        as_is_seconds: float | None,
        preview_seconds: float | None,
    ) -> str:
        as_is = self._format_seconds(as_is_seconds)
        preview = self._format_seconds(preview_seconds)
        if as_is_seconds is None or preview_seconds is None:
            return f"As is: {as_is}    Preview: {preview}"
        delta = self._format_delta(preview_seconds - as_is_seconds)
        return f"As is: {as_is}    Preview: {preview}    {delta}"

    def compose(self) -> ComposeResult:
        default_title = default_export_title(self._candidate)
        with Vertical(id="export-preview-dialog"):
            yield Label(
                f"Preview export ({self._options.mode})  #{self._candidate.clip_id}",
                id="export-preview-header",
            )
            yield Static(
                self._format_times_line(self._candidate),
                id="export-preview-times",
                markup=False,
            )
            yield WaveformWidget(id="export-preview-waveform")
            yield Input(default_title, id="export-title-input")
            yield Static(
                self._format_info_line(None, None),
                id="export-preview-info",
                markup=False,
            )
            yield Static("", id="export-preview-status", markup=False)
            yield Label(
                "Enter = edit title / export  Space = replay  Esc = back  Ctrl+C = copy",
                id="export-preview-hint",
            )

    def _preview_still_valid(self, generation: int) -> bool:
        return self._is_active and generation == self._preview_generation

    def _deactivate(self, *, cancel_build: bool = False) -> None:
        self._is_active = False
        self._stop_playback()
        if cancel_build:
            self._preview_generation += 1

    def _wait_for_preview_path(self) -> Path | None:
        if self._preview_path is not None:
            return self._preview_path
        self._handoff_ready.wait()
        if self._handoff_error is not None:
            return None
        if self._handoff_artifacts is not None:
            return self._handoff_artifacts.preview_path
        return None

    def on_mount(self) -> None:
        self._is_active = True
        self._preview_generation = 1
        self._handoff_ready.clear()
        self._handoff_artifacts = None
        self._handoff_error = None
        widget = self.query_one("#export-preview-waveform", WaveformWidget)
        widget.focus()
        widget.show_placeholder(GENERATING_PREVIEW_PLACEHOLDER)
        self.query_one("#export-preview-status", Static).update(
            "Rendering export audio…"
        )
        self._build_preview()

    def on_unmount(self) -> None:
        self._is_active = False
        self._stop_playback()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "export-title-input":
            self._export()

    @work(thread=True, exclusive=True, group="export-preview")
    def _build_preview(self) -> None:
        generation = self._preview_generation
        try:
            artifacts: ExportPreviewArtifacts | None = None
            if self._try_preloaded is not None:
                artifacts = self._try_preloaded()
            if artifacts is None:
                artifacts = build_export_preview_artifacts(
                    self._audio,
                    self._candidate,
                    self._options,
                )
        except Exception as exc:
            if generation == self._preview_generation:
                self._handoff_error = str(exc)
                self._handoff_ready.set()
            if self._preview_still_valid(generation):
                self.app.call_from_thread(self._on_preview_failed, str(exc))
            return
        if generation != self._preview_generation:
            return
        self._handoff_artifacts = artifacts
        self._handoff_ready.set()
        self._preview_path = artifacts.preview_path
        self._as_is_seconds = artifacts.as_is_seconds
        self._preview_seconds = artifacts.preview_seconds
        if self._preview_still_valid(generation):
            self.app.call_from_thread(
                self._on_preview_ready,
                artifacts.preview_path,
                artifacts.as_is_seconds,
                artifacts.preview_seconds,
            )

    def _on_preview_ready(
        self,
        preview_path: Path,
        as_is_seconds: float,
        preview_seconds: float,
    ) -> None:
        if not self._is_active:
            return
        try:
            widget = self.query_one("#export-preview-waveform", WaveformWidget)
            preview_duration = f"{preview_seconds:.3f}"
            widget.display_waveform(
                preview_path,
                "00:00:00.000",
                preview_duration,
                media_duration=preview_seconds,
                source_audio=preview_path,
            )
            if not self._is_active:
                return
            self.query_one("#export-preview-info", Static).update(
                self._format_info_line(as_is_seconds, preview_seconds)
            )
            if not self._is_active:
                return
            self._start_playback()
        except NoMatches:
            return

    def _on_preview_failed(self, message: str) -> None:
        if not self._is_active:
            return
        try:
            widget = self.query_one("#export-preview-waveform", WaveformWidget)
            widget.show_placeholder(f"Preview failed: {message}")
            self.query_one("#export-preview-info", Static).update(
                "As is: unavailable    Preview: unavailable"
            )
            self.query_one("#export-preview-status", Static).update(
                "Preview unavailable. Enter to set title and export, Esc to go back."
            )
        except NoMatches:
            return

    def _title_input(self) -> Input:
        return self.query_one("#export-title-input", Input)

    def _waveform_widget(self) -> WaveformWidget:
        return self.query_one("#export-preview-waveform", WaveformWidget)

    def _start_playback(self) -> None:
        if self._preview_path is None:
            return
        self._stop_playback()
        try:
            self._playback_process = self._audio_playback.spawn_play_file(
                self._preview_path
            )
        except Exception as exc:
            self.notify(f"Playback failed: {exc}", severity="error")
            return
        # Use the probed preview duration when available; otherwise fall back
        # to ``candidate.duration`` as an upper bound. The watcher below clears
        # the status once playback exits, so an upper bound stays safe.
        countdown_seconds = (
            self._preview_seconds
            if self._preview_seconds is not None
            else float(self._candidate.duration)
        )
        self._playback_duration = countdown_seconds
        self._playback_end = time.monotonic() + countdown_seconds
        self._update_playback_status()
        self._playback_timer = self.set_interval(0.2, self._update_playback_status)

    def _stop_playback(self) -> None:
        process = self._playback_process
        self._playback_process = None
        if process is not None and process.poll() is None:
            process.terminate()
        if self._playback_timer is not None:
            self._playback_timer.stop()
            self._playback_timer = None
        self._playback_end = None
        self._playback_duration = None
        try:
            self._waveform_widget().clear_playhead()
            self.query_one("#export-preview-status", Static).update("")
        except Exception:
            # Widget may already be gone during unmount.
            pass

    def _update_playback_status(self) -> None:
        if not self._is_active:
            self._stop_playback()
            return
        process = self._playback_process
        if process is None:
            return
        if process.poll() is not None:
            self._stop_playback()
            return
        if self._playback_end is None:
            return
        remaining = self._playback_end - time.monotonic()
        try:
            status = self.query_one("#export-preview-status", Static)
            widget = self._waveform_widget()
        except NoMatches:
            self._stop_playback()
            return
        if remaining <= 0:
            # The player may still be flushing; let the next tick check process.poll().
            status.update(format_playback_remaining(0.0))
            return
        if self._playback_duration is not None:
            elapsed = self._playback_duration - remaining
            widget.set_playhead(elapsed)
        status.update(format_playback_remaining(remaining))

    def action_replay(self) -> None:
        if self._preview_path is None:
            return
        self._start_playback()

    def action_focus_or_export(self) -> None:
        title_input = self._title_input()
        if title_input.has_focus:
            # Enter is handled by ``on_input_submitted`` while the field is focused.
            return
        title_input.focus()
        title_input.cursor_position = len(title_input.value)

    def action_copy_title(self) -> None:
        title = self._title_input().value
        if not title:
            self.notify("Nothing to copy", severity="warning")
            return
        self.app.copy_to_clipboard(title)
        self.notify("Title copied to clipboard")

    def _export(self) -> None:
        value = self._title_input().value.strip()
        if not value:
            self.notify("Title cannot be empty", severity="warning")
            return
        wait_for_preview_path = None
        if self._preview_path is None:
            wait_for_preview_path = self._wait_for_preview_path
        self._deactivate()
        self.dismiss(
            ExportConfirm(
                title=value,
                preview_path=self._preview_path,
                wait_for_preview_path=wait_for_preview_path,
            )
        )

    def action_cancel(self) -> None:
        if self._title_input().has_focus:
            # While editing the title, Esc should just exit editing.
            self._waveform_widget().focus()
            return
        self._deactivate(cancel_build=True)
        self.dismiss(False)
