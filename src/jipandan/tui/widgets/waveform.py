from collections.abc import Callable
from functools import partial
from pathlib import Path

import numpy as np
from textual import events, on, work
from textual.app import ComposeResult
from textual.containers import Center, Container, Vertical
from textual.timer import Timer
from textual.widgets import LoadingIndicator, Static
from textual_plot import PlotWidget

from jipandan.core import ffmpeg
from jipandan.core.srt import srt_time_to_seconds
from jipandan.core.waveform_envelope import (
    decode_mp3_mono_f32,
    downsample_envelope,
    envelope_for_time_range,
)
from jipandan.tui.widgets.waveform_nudge_bar import (
    MARKER_EPSILON_SECONDS,
    NudgeEdge,
    WaveformNudgeBar,
)
from jipandan.tui.widgets.waveform_plot import (
    absolute_time_to_nudge_x,
    envelope_buckets_for_width,
    nudge_x_to_absolute_time,
    render_waveform_plot,
)

GENERATING_WAVEFORM_PLACEHOLDER = "Generating waveform…"
GENERATING_PREVIEW_PLACEHOLDER = "Generating preview…"
_LOADING_PLACEHOLDERS = frozenset(
    {GENERATING_WAVEFORM_PLACEHOLDER, GENERATING_PREVIEW_PLACEHOLDER}
)
_SCALE_REGEN_DEBOUNCE_SECONDS = 0.15
_SCALE_REGEN_MIN_RELATIVE_DELTA = 0.03


def format_playback_remaining(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"Playing audio ({minutes}:{secs:02d} remaining)"


def _timestamp_seconds(value: str) -> float:
    return srt_time_to_seconds(value.replace(".", ","))


class WaveformWidget(Vertical, can_focus=True):
    ALLOW_SELECT = False

    DEFAULT_CSS = """
    WaveformWidget {
        height: 1fr;
        min-height: 6;
        padding: 1 0 0 0;
        border: tall transparent;
    }

    WaveformWidget:focus {
        border: tall $primary;
    }

    #waveform-content {
        height: 1fr;
        width: 100%;
    }

    #waveform-plot {
        width: 100%;
        height: 1fr;
        display: none;
    }

    #waveform-placeholder-panel {
        height: 1fr;
        width: 100%;
        align: center middle;
    }

    #waveform-nudge-bar {
        height: 1;
        width: 100%;
        display: none;
        background: $surface;
    }

    #waveform-loading-row {
        height: auto;
        width: 100%;
        margin-bottom: 1;
    }

    #waveform-placeholder-row {
        height: auto;
        width: 100%;
    }

    #waveform-loading {
        height: auto;
        width: auto;
    }

    #waveform-placeholder {
        height: auto;
        width: auto;
        content-align: center middle;
    }

    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._audio_path: Path | None = None
        self._viewport_start: float | None = None
        self._viewport_duration: float | None = None
        self._media_duration: float | None = None
        self._marker_start: float | None = None
        self._marker_end: float | None = None
        self._preview_marker_start: float | None = None
        self._preview_marker_end: float | None = None
        self._nudge_handler: Callable[[NudgeEdge, float], None] | None = None
        self._pending_placeholder: str | None = None
        self._pending_plot_apply = False
        self._plot_update_in_progress = False
        self._plot_update_token = 0
        self._nudge_bar: WaveformNudgeBar | None = None
        self._envelope_times: np.ndarray | None = None
        self._envelope_mins: np.ndarray | None = None
        self._envelope_maxs: np.ndarray | None = None
        self._pcm_samples: np.ndarray | None = None
        self._pcm_duration: float | None = None
        self._scale_regen_enabled = False
        self._last_regen_x_range: tuple[float, float] | None = None
        self._scale_regen_timer: Timer | None = None
        self._pending_scale_x_range: tuple[float, float] | None = None

    def compose(self) -> ComposeResult:
        with Container(id="waveform-content"):
            with Vertical(id="waveform-placeholder-panel"):
                with Center(id="waveform-loading-row"):
                    yield LoadingIndicator(id="waveform-loading")
                with Center(id="waveform-placeholder-row"):
                    yield Static(
                        GENERATING_WAVEFORM_PLACEHOLDER,
                        id="waveform-placeholder",
                        markup=False,
                    )
            plot = PlotWidget(id="waveform-plot")
            plot.can_focus = False
            plot.display = False
            yield plot
        yield WaveformNudgeBar(id="waveform-nudge-bar")

    def on_mount(self) -> None:
        self._nudge_bar = self.query_one("#waveform-nudge-bar", WaveformNudgeBar)
        self._nudge_bar.bind_waveform(self)
        if self._nudge_handler is not None:
            self._nudge_bar.set_nudge_handler(self._nudge_handler)
        self._flush_pending_display()

    def set_nudge_handler(
        self, handler: Callable[[NudgeEdge, float], None] | None
    ) -> None:
        self._nudge_handler = handler
        if self._nudge_bar is not None:
            self._nudge_bar.set_nudge_handler(handler)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.screen.clear_selection()

    def set_marker_preview(self, marker_start: float, marker_end: float) -> None:
        self._preview_marker_start = marker_start
        self._preview_marker_end = marker_end
        if not self._nodes_ready() or self._audio_path is None:
            return
        self._apply_marker_overlay()

    def clear_marker_preview(self) -> None:
        if (
            self._preview_marker_start is None
            and self._preview_marker_end is None
        ):
            return
        self._preview_marker_start = None
        self._preview_marker_end = None
        if self._audio_path is None or not self._nodes_ready():
            return
        self._apply_marker_overlay()

    def is_image_update_in_progress(self) -> bool:
        return self._plot_update_in_progress

    def _nodes_ready(self) -> bool:
        return (
            len(self.query("#waveform-placeholder-panel")) > 0
            and len(self.query("#waveform-placeholder")) > 0
            and len(self.query("#waveform-plot")) > 0
        )

    def _begin_plot_update(self) -> int:
        self._plot_update_token += 1
        self._plot_update_in_progress = True
        return self._plot_update_token

    def _cancel_plot_update(self, token: int | None = None) -> None:
        if token is not None and token != self._plot_update_token:
            return
        self._plot_update_in_progress = False

    @staticmethod
    def _shows_loading_indicator(message: str) -> bool:
        return message in _LOADING_PLACEHOLDERS

    def _flush_pending_display(self) -> None:
        if not self._nodes_ready():
            return
        if self._pending_placeholder is not None:
            message = self._pending_placeholder
            self._pending_placeholder = None
            self.show_placeholder(message)
            return
        if self._pending_plot_apply and self._audio_path is not None:
            self._pending_plot_apply = False
            self._start_envelope_load(self._audio_path)

    def show_placeholder(self, message: str) -> None:
        self._cancel_plot_update()
        self._plot_update_token += 1
        self._audio_path = None
        self._viewport_start = None
        self._viewport_duration = None
        self._media_duration = None
        self._marker_start = None
        self._marker_end = None
        self._preview_marker_start = None
        self._preview_marker_end = None
        self._pending_plot_apply = False
        self._envelope_times = None
        self._envelope_mins = None
        self._envelope_maxs = None
        self._pcm_samples = None
        self._pcm_duration = None
        self._scale_regen_enabled = False
        self._last_regen_x_range = None
        self._cancel_scale_regen_timer()
        if not self._nodes_ready():
            self._pending_placeholder = message
            return
        self._pending_placeholder = None
        if self._nudge_bar is not None:
            self._nudge_bar.clear()
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        loading = self.query_one("#waveform-loading", LoadingIndicator)
        placeholder = self.query_one("#waveform-placeholder", Static)
        plot = self.query_one("#waveform-plot", PlotWidget)
        placeholder.update(message)
        loading.display = self._shows_loading_indicator(message)
        panel.display = True
        plot.display = False

    def display_waveform(
        self,
        path: Path,
        viewport_start: str,
        viewport_duration: str,
        *,
        media_duration: float | None = None,
    ) -> None:
        if not path.exists():
            self.show_placeholder(f"Waveform not found: {path}")
            return
        self._audio_path = path
        self._viewport_start = _timestamp_seconds(viewport_start)
        self._viewport_duration = float(viewport_duration)
        self._media_duration = (
            media_duration
            if media_duration is not None
            else self._viewport_duration
        )
        viewport_end = self._viewport_start + self._viewport_duration
        self._marker_start = self._viewport_start
        self._marker_end = viewport_end
        if not self._nodes_ready():
            self._pending_plot_apply = True
            self._pending_placeholder = None
            self.call_after_refresh(self._flush_pending_display)
            return
        self._pending_plot_apply = False
        self._start_envelope_load(path)
        self._sync_nudge_bar()

    def overlay_trim_bounds(self, clip_start: str, clip_end: str) -> None:
        if self._audio_path is None or self._viewport_start is None:
            return
        if self._viewport_duration is None:
            return
        marker_start = _timestamp_seconds(clip_start)
        marker_end = _timestamp_seconds(clip_end)
        if (
            self._marker_start is not None
            and self._marker_end is not None
            and abs(self._marker_start - marker_start) < MARKER_EPSILON_SECONDS
            and abs(self._marker_end - marker_end) < MARKER_EPSILON_SECONDS
        ):
            return
        self._marker_start = marker_start
        self._marker_end = marker_end
        if not self._nodes_ready():
            self._pending_plot_apply = True
            self._pending_placeholder = None
            self.call_after_refresh(self._flush_pending_display)
            return
        self._apply_marker_overlay()
        self._sync_nudge_bar()
        self.call_after_refresh(self._refresh_nudge_bar_handles)

    def _sync_nudge_bar(self) -> None:
        if self._nudge_bar is None:
            return
        if self._nudge_handler is None:
            self._nudge_bar.clear()
            return
        if self._audio_path is None or self._marker_start is None:
            self._nudge_bar.clear()
            return
        if self._marker_end is None:
            self._nudge_bar.clear()
            return
        image_start, image_duration, _image_end = self._image_time_range()
        self._nudge_bar.set_time_range(image_start, image_duration)
        self._nudge_bar.sync_markers(self._marker_start, self._marker_end)
        self._nudge_bar.show()

    def _image_time_range(self) -> tuple[float, float, float]:
        image_start = self._viewport_start
        assert image_start is not None
        image_duration = self._media_duration or self._viewport_duration
        assert image_duration is not None
        return image_start, image_duration, image_start + image_duration

    def _marker_positions_relative(self) -> tuple[float, float] | None:
        if (
            self._viewport_start is None
            or self._marker_start is None
            or self._marker_end is None
        ):
            return None
        marker_start = (
            self._preview_marker_start
            if self._preview_marker_start is not None
            else self._marker_start
        )
        marker_end = (
            self._preview_marker_end
            if self._preview_marker_end is not None
            else self._marker_end
        )
        base = self._viewport_start
        image_start, _image_duration, image_end = self._image_time_range()
        rel_start = max(0.0, min(marker_start - base, image_end - base))
        rel_end = max(rel_start, min(marker_end - base, image_end - base))
        return rel_start, rel_end

    def map_time_to_nudge_x(self, time_seconds: float) -> int | None:
        if self._viewport_start is None or not self._nodes_ready():
            return None
        plot = self.query_one("#waveform-plot", PlotWidget)
        if not plot.display:
            return None
        try:
            return absolute_time_to_nudge_x(
                plot,
                viewport_start=self._viewport_start,
                time_seconds=time_seconds,
            )
        except (ValueError, ZeroDivisionError):
            return None

    def map_nudge_x_to_time(self, nudge_x: float) -> float | None:
        if self._viewport_start is None or not self._nodes_ready():
            return None
        plot = self.query_one("#waveform-plot", PlotWidget)
        if not plot.display:
            return None
        try:
            return nudge_x_to_absolute_time(
                plot,
                viewport_start=self._viewport_start,
                nudge_x=nudge_x,
            )
        except (ValueError, ZeroDivisionError):
            return None

    def _refresh_nudge_bar_handles(self) -> None:
        if self._nudge_bar is not None and self._nudge_bar.display:
            self._nudge_bar.refresh()

    def _cancel_scale_regen_timer(self) -> None:
        if self._scale_regen_timer is not None:
            self._scale_regen_timer.stop()
            self._scale_regen_timer = None
        self._pending_scale_x_range = None

    def _scale_range_needs_regen(self, x_min: float, x_max: float) -> bool:
        if self._last_regen_x_range is None:
            return True
        last_min, last_max = self._last_regen_x_range
        span = max(last_max - last_min, 1e-6)
        if abs(x_min - last_min) / span < _SCALE_REGEN_MIN_RELATIVE_DELTA:
            if abs(x_max - last_max) / span < _SCALE_REGEN_MIN_RELATIVE_DELTA:
                return False
        return True

    def _schedule_scale_regen(self, x_min: float, x_max: float) -> None:
        if not self._scale_regen_enabled:
            return
        if self._pcm_samples is None or self._pcm_duration is None:
            return
        self._pending_scale_x_range = (x_min, x_max)
        if self._scale_regen_timer is not None:
            self._scale_regen_timer.stop()
        self._scale_regen_timer = self.set_timer(
            _SCALE_REGEN_DEBOUNCE_SECONDS,
            self._run_scale_regen,
            name="waveform-scale-regen",
        )

    def _run_scale_regen(self) -> None:
        self._scale_regen_timer = None
        pending = self._pending_scale_x_range
        self._pending_scale_x_range = None
        if pending is None or not self._nodes_ready():
            return
        x_min, x_max = pending
        if not self._scale_range_needs_regen(x_min, x_max):
            return
        plot = self.query_one("#waveform-plot", PlotWidget)
        if not plot.display:
            return
        self._regen_envelope_for_range(plot, x_min, x_max)

    @on(PlotWidget.ScaleChanged)
    def _on_plot_scale_changed(self, event: PlotWidget.ScaleChanged) -> None:
        if not self._nodes_ready():
            return
        plot = self.query_one("#waveform-plot", PlotWidget)
        if event.plot is not plot:
            return
        self._schedule_scale_regen(event.x_min, event.x_max)

    def _regen_envelope_for_range(
        self, plot: PlotWidget, x_min: float, x_max: float
    ) -> None:
        if self._pcm_samples is None or self._pcm_duration is None:
            return
        duration = self._pcm_duration
        visible_min = max(0.0, min(x_min, duration))
        visible_max = max(visible_min, min(x_max, duration))
        if visible_max <= visible_min:
            return
        self._scale_regen_enabled = False
        try:
            width = max(plot.size.width, 1)
            buckets = envelope_buckets_for_width(width)
            times, mins, maxs = envelope_for_time_range(
                self._pcm_samples,
                duration,
                visible_min,
                visible_max,
                buckets,
            )
            self._envelope_times = times
            self._envelope_mins = mins
            self._envelope_maxs = maxs
            self._last_regen_x_range = (x_min, x_max)
            self._render_plot(plot, x_limits=(x_min, x_max))
            plot.refresh()
            self.call_after_refresh(self._refresh_nudge_bar_handles)
        finally:
            self._scale_regen_enabled = True

    def _render_plot(
        self,
        plot: PlotWidget,
        *,
        x_limits: tuple[float, float] | None = None,
    ) -> None:
        if (
            self._envelope_times is None
            or self._envelope_mins is None
            or self._envelope_maxs is None
        ):
            return
        markers = self._marker_positions_relative()
        render_waveform_plot(
            plot,
            times=self._envelope_times,
            mins=self._envelope_mins,
            maxs=self._envelope_maxs,
            marker_start=markers[0] if markers is not None else None,
            marker_end=markers[1] if markers is not None else None,
            x_limits=x_limits,
        )

    def _start_envelope_load(self, mp3_path: Path) -> None:
        token = self._begin_plot_update()
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        plot = self.query_one("#waveform-plot", PlotWidget)
        panel.display = True
        plot.display = False
        self._load_envelope(mp3_path, token)

    @work(thread=True, exclusive=True, group="waveform-envelope")
    def _load_envelope(self, mp3_path: Path, token: int) -> None:
        try:
            width = max(self.size.width, self.app.size.width)
            buckets = envelope_buckets_for_width(width)
            duration = ffmpeg.probe_duration_seconds(mp3_path)
            samples = decode_mp3_mono_f32(mp3_path)
            times, mins, maxs = downsample_envelope(samples, duration, buckets)
        except Exception as exc:
            if token == self._plot_update_token:
                self.app.call_from_thread(self._on_envelope_failed, token, str(exc))
            return
        if token != self._plot_update_token:
            return
        self.app.call_from_thread(
            self._on_envelope_ready,
            token,
            samples,
            duration,
            times,
            mins,
            maxs,
        )

    def _on_envelope_failed(self, token: int, message: str) -> None:
        if token != self._plot_update_token:
            return
        self._cancel_plot_update(token)
        self.show_placeholder(f"Waveform failed: {message}")

    def _on_envelope_ready(
        self,
        token: int,
        samples: np.ndarray,
        duration: float,
        times: np.ndarray,
        mins: np.ndarray,
        maxs: np.ndarray,
    ) -> None:
        if token != self._plot_update_token:
            return
        self._pcm_samples = samples
        self._pcm_duration = duration
        self._envelope_times = times
        self._envelope_mins = mins
        self._envelope_maxs = maxs
        self._scale_regen_enabled = False
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        plot = self.query_one("#waveform-plot", PlotWidget)
        self._render_plot(plot)
        panel.display = False
        plot.display = True
        plot.refresh()
        self.call_after_refresh(partial(self._finish_plot_update, token))

    def _apply_marker_overlay(self) -> None:
        if self._plot_update_in_progress:
            return
        plot = self.query_one("#waveform-plot", PlotWidget)
        if not plot.display:
            return
        self._render_plot(plot, x_limits=(plot._x_min, plot._x_max))
        plot.refresh()
        self.call_after_refresh(self._refresh_nudge_bar_handles)

    def _finish_plot_update(self, token: int) -> None:
        if token != self._plot_update_token:
            return
        self._plot_update_in_progress = False
        plot = self.query_one("#waveform-plot", PlotWidget)
        plot.refresh()
        self._last_regen_x_range = (plot._x_min, plot._x_max)
        self._scale_regen_enabled = True
        self._sync_nudge_bar()
        self._refresh_nudge_bar_handles()
