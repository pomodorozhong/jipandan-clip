from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static
from textual_plot import DurationFormatter, HiResMode, PlotWidget

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate
from jipandan.core.waveform_envelope import load_waveform_envelope

if TYPE_CHECKING:
    from jipandan.tui.waveform_service import WaveformService

_START_MARKER_STYLE = "rgb(255,200,0)"
_END_MARKER_STYLE = "rgb(255,80,200)"


@dataclass(frozen=True)
class PlotWaveformData:
    times: np.ndarray
    mins: np.ndarray
    maxs: np.ndarray
    marker_start: float
    marker_end: float


class PlotWaveformPreviewModal(ModalScreen[None]):
    """Read-only textual-plot preview of the current clip's basic waveform."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
    ]

    DEFAULT_CSS = """
    PlotWaveformPreviewModal {
        layout: vertical;
    }

    #plot-waveform-dialog {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    #plot-waveform-header,
    #plot-waveform-times,
    #plot-waveform-title,
    #plot-waveform-status,
    #plot-waveform-hint {
        height: auto;
        width: 100%;
    }

    #plot-waveform-plot {
        height: 1fr;
        width: 100%;
        min-height: 10;
    }

    #plot-waveform-status {
        color: $text-muted;
    }

    #plot-waveform-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(
        self,
        candidate: ClipCandidate,
        waveform_service: WaveformService,
    ) -> None:
        super().__init__()
        self._candidate = candidate
        self._waveform_service = waveform_service
        self._is_active = False
        self._load_generation = 0
        self._envelope_buckets = 800

    @staticmethod
    def _format_times_line(candidate: ClipCandidate) -> str:
        return f"Start: {candidate.start}    End: {candidate.end}"

    def compose(self) -> ComposeResult:
        candidate = self._candidate
        with Vertical(id="plot-waveform-dialog"):
            yield Label(
                f"Plot preview (textual-plot)  #{candidate.clip_id}",
                id="plot-waveform-header",
            )
            yield Static(
                self._format_times_line(candidate),
                id="plot-waveform-times",
                markup=False,
            )
            yield Static(candidate.title, id="plot-waveform-title", markup=False)
            plot = PlotWidget(id="plot-waveform-plot")
            plot.can_focus = False
            yield plot
            yield Static("Loading waveform…", id="plot-waveform-status", markup=False)
            yield Label("Esc = close", id="plot-waveform-hint")

    def on_mount(self) -> None:
        self._is_active = True
        self._load_generation = 1
        # Braille mode is 2 cells wide; use extra buckets for fullscreen width.
        self._envelope_buckets = max(800, self.app.size.width * 4)
        self._load_waveform()

    def on_unmount(self) -> None:
        self._is_active = False

    def _load_still_valid(self, generation: int) -> bool:
        return self._is_active and generation == self._load_generation

    @work(thread=True, exclusive=True, group="plot-waveform-preview")
    def _load_waveform(self) -> None:
        generation = self._load_generation
        try:
            mp3 = self._waveform_service.ensure_basic_mp3(self._candidate)
            times, mins, maxs = load_waveform_envelope(
                mp3, buckets=self._envelope_buckets
            )
            ffmpeg.probe_duration_seconds(mp3)
            extract_start = self._waveform_service.basic_padded_start_seconds(
                self._candidate
            )
            clip_start = self._waveform_service.clip_start_seconds(self._candidate)
            clip_end = self._waveform_service.clip_end_seconds(self._candidate)
            data = PlotWaveformData(
                times=times,
                mins=mins,
                maxs=maxs,
                marker_start=clip_start - extract_start,
                marker_end=clip_end - extract_start,
            )
        except Exception as exc:
            if self._load_still_valid(generation):
                self.app.call_from_thread(self._on_load_failed, str(exc))
            return
        if not self._load_still_valid(generation):
            return
        self.app.call_from_thread(self._on_load_ready, data)

    def _on_load_failed(self, message: str) -> None:
        self.query_one("#plot-waveform-status", Static).update(
            f"Waveform failed: {message}"
        )

    def _on_load_ready(self, data: PlotWaveformData) -> None:
        plot = self.query_one("#plot-waveform-plot", PlotWidget)
        plot.clear()
        plot.set_x_formatter(DurationFormatter())
        plot.plot(
            data.times,
            data.maxs,
            line_style="cyan",
            hires_mode=HiResMode.BRAILLE,
        )
        plot.plot(
            data.times,
            data.mins,
            line_style="cyan",
            hires_mode=HiResMode.BRAILLE,
        )
        plot.add_v_line(
            data.marker_start,
            line_style=_START_MARKER_STYLE,
            label="Start",
        )
        plot.add_v_line(
            data.marker_end,
            line_style=_END_MARKER_STYLE,
            label="End",
        )
        plot.set_xlabel("Time")
        plot.set_ylabel("Amplitude")
        self.query_one("#plot-waveform-status", Static).update("")

    def action_cancel(self) -> None:
        self._is_active = False
        self._load_generation += 1
        self.dismiss(None)
