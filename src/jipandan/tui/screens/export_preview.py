import subprocess
import time
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Label, Static

from jipandan.core import ffmpeg
from jipandan.core.ffmpeg import ExportOptions
from jipandan.core.models import ClipCandidate
from jipandan.tui.widgets.waveform import (
    WaveformWidget,
    format_playback_remaining,
)

_PREVIEW_DIR = Path("tmp") / "preview"
# Titles baked into the preview files; only ever read by the user from the tmp dir.
_PREVIEW_TITLE = "preview"
_AS_IS_TITLE = "preview-asis"


class ExportPreviewModal(ModalScreen[bool]):
    """Render the export-shaped audio, show its waveform, and play it back.

    Dismissed value:
      * ``True``  – user confirmed; the caller should continue to the title modal.
      * ``False`` – user cancelled; the caller should abort the export.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Back", show=False),
        Binding("enter", "confirm", "Confirm", show=True),
        Binding("space", "replay", "Replay", show=True),
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
    ) -> None:
        super().__init__()
        self._audio = audio
        self._candidate = candidate
        self._options = options
        self._preview_path: Path | None = None
        self._as_is_seconds: float | None = None
        self._preview_seconds: float | None = None
        self._playback_process: subprocess.Popen | None = None
        self._playback_end: float | None = None
        self._playback_timer: Timer | None = None

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
        with Vertical(id="export-preview-dialog"):
            yield Label(
                f"Preview export ({self._options.mode})  #{self._candidate.clip_id}",
                id="export-preview-title",
            )
            yield WaveformWidget(id="export-preview-waveform")
            yield Static(
                self._format_info_line(None, None),
                id="export-preview-info",
                markup=False,
            )
            yield Static("", id="export-preview-status", markup=False)
            yield Label(
                "Enter = confirm  Space = replay  Esc = back",
                id="export-preview-hint",
            )

    def on_mount(self) -> None:
        widget = self.query_one("#export-preview-waveform", WaveformWidget)
        widget.show_placeholder("Generating preview…")
        self.query_one("#export-preview-status", Static).update(
            "Rendering export audio…"
        )
        self._build_preview()

    def on_unmount(self) -> None:
        self._stop_playback()

    @work(thread=True, exclusive=True, group="export-preview")
    def _build_preview(self) -> None:
        try:
            _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            # Always render an "as is" baseline so both sides of the duration
            # comparison come from real ffmpeg output; this cancels out mp3
            # frame-alignment noise that would otherwise leak into the delta.
            as_is_path = ffmpeg.export_clip(
                self._audio,
                self._candidate,
                _PREVIEW_DIR,
                export_title=_AS_IS_TITLE,
                export_options=ExportOptions(mode="as_is"),
            )
            as_is_seconds = ffmpeg.probe_duration_seconds(as_is_path)
            if self._options.mode == "as_is":
                preview_path = as_is_path
                preview_seconds = as_is_seconds
            else:
                preview_path = ffmpeg.export_clip(
                    self._audio,
                    self._candidate,
                    _PREVIEW_DIR,
                    export_title=_PREVIEW_TITLE,
                    export_options=self._options,
                )
                preview_seconds = ffmpeg.probe_duration_seconds(preview_path)
            waveform_path = preview_path.with_suffix(".png")
            ffmpeg.render_waveform(preview_path, waveform_path)
        except Exception as exc:
            self.app.call_from_thread(self._on_preview_failed, str(exc))
            return
        self._preview_path = preview_path
        self._as_is_seconds = as_is_seconds
        self._preview_seconds = preview_seconds
        self.app.call_from_thread(
            self._on_preview_ready,
            waveform_path,
            as_is_seconds,
            preview_seconds,
        )

    def _on_preview_ready(
        self,
        waveform_path: Path,
        as_is_seconds: float,
        preview_seconds: float,
    ) -> None:
        widget = self.query_one("#export-preview-waveform", WaveformWidget)
        widget.display_waveform(
            waveform_path,
            "00:00:00.000",
            self._candidate.duration,
        )
        self.query_one("#export-preview-info", Static).update(
            self._format_info_line(as_is_seconds, preview_seconds)
        )
        self._start_playback()

    def _on_preview_failed(self, message: str) -> None:
        widget = self.query_one("#export-preview-waveform", WaveformWidget)
        widget.show_placeholder(f"Preview failed: {message}")
        self.query_one("#export-preview-info", Static).update(
            "As is: unavailable    Preview: unavailable"
        )
        self.query_one("#export-preview-status", Static).update(
            "Preview unavailable. Enter to export anyway, Esc to go back."
        )

    def _start_playback(self) -> None:
        if self._preview_path is None:
            return
        self._stop_playback()
        try:
            self._playback_process = ffmpeg.spawn_play_file(self._preview_path)
        except Exception as exc:
            self.notify(f"mpv failed: {exc}", severity="error")
            return
        # Use the probed preview duration when available; otherwise fall back
        # to ``candidate.duration`` as an upper bound. The watcher below clears
        # the status once mpv exits, so an upper bound stays safe.
        countdown_seconds = (
            self._preview_seconds
            if self._preview_seconds is not None
            else float(self._candidate.duration)
        )
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
        try:
            self.query_one("#export-preview-status", Static).update("")
        except Exception:
            # Widget may already be gone during unmount.
            pass

    def _update_playback_status(self) -> None:
        process = self._playback_process
        if process is None:
            return
        if process.poll() is not None:
            self._stop_playback()
            return
        if self._playback_end is None:
            return
        remaining = self._playback_end - time.monotonic()
        if remaining <= 0:
            # mpv may still be flushing; let the next tick check process.poll().
            self.query_one("#export-preview-status", Static).update(
                format_playback_remaining(0.0)
            )
            return
        self.query_one("#export-preview-status", Static).update(
            format_playback_remaining(remaining)
        )

    def action_replay(self) -> None:
        if self._preview_path is None:
            return
        self._start_playback()

    def action_confirm(self) -> None:
        self._stop_playback()
        self.dismiss(True)

    def action_cancel(self) -> None:
        self._stop_playback()
        self.dismiss(False)
