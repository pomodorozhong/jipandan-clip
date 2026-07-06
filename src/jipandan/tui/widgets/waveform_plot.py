"""Shared textual-plot rendering helpers for waveform widgets."""

from __future__ import annotations

import numpy as np
from textual import on
from textual.events import MouseMove, MouseScrollDown, MouseScrollUp
from textual.reactive import reactive
from textual_plot import DurationFormatter, HiResMode, PlotWidget
from textual_plot.plot_widget import map_pixel_to_coordinate

START_MARKER_STYLE = "rgb(255,200,0)"
END_MARKER_STYLE = "rgb(255,80,200)"
PLAYHEAD_STYLE = "rgb(255,255,255)"
DEFAULT_ENVELOPE_BUCKETS = 800


class WaveformPlotWidget(PlotWidget):
    """PlotWidget locked to horizontal zoom/pan for waveform review."""

    # textual-plot defaults reserve rows for axis titles we do not show.
    margin_top = reactive(0)
    margin_bottom = reactive(1)

    def _render_y_label(self) -> None:
        return

    def _render_x_label(self) -> None:
        return

    @on(MouseScrollDown)
    def zoom_in(self, event: MouseScrollDown) -> None:
        self._zoom_with_mouse(event, self.MOUSE_ZOOM_FACTOR)

    @on(MouseScrollUp)
    def zoom_out(self, event: MouseScrollUp) -> None:
        self._zoom_with_mouse(event, -self.MOUSE_ZOOM_FACTOR)

    def _zoom_with_mouse(
        self, event: MouseScrollDown | MouseScrollUp, factor: float
    ) -> None:
        if not self._allow_pan_and_zoom:
            return
        if self.invert_mouse_wheel:
            factor *= -1
        if (offset := event.get_content_offset(self)) is None:
            return
        widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
        canvas = self.query_one("#plot")
        if widget.id == "margin-bottom":
            offset = event.screen_offset - self.screen.get_offset(canvas)
        x, y = self.get_coordinate_from_pixel(offset.x, offset.y)
        zoom_x = widget.id in ("plot", "margin-bottom")
        self._zoom(x, y, factor, zoom_x, zoom_y=False)

    def _pan_plot_with_mouse(self, event: MouseMove) -> None:
        assert event.widget is not None
        factor_x = event.delta_x if event.widget.id in ("plot", "margin-bottom") else 0
        self._pan(factor_x, 0)

    def action_zoom_in(self) -> None:
        self._zoom_with_keyboard(self.KEYBOARD_ZOOM_FACTOR, zoom_x=True, zoom_y=False)

    def action_zoom_out(self) -> None:
        self._zoom_with_keyboard(
            -self.KEYBOARD_ZOOM_FACTOR, zoom_x=True, zoom_y=False
        )

    def action_zoom_y_in(self) -> None:
        return

    def action_zoom_y_out(self) -> None:
        return

    def action_pan_up(self) -> None:
        return

    def action_pan_down(self) -> None:
        return


def envelope_buckets_for_width(width: int) -> int:
    """Scale envelope resolution with plot width (braille is 2 cells wide)."""
    return max(DEFAULT_ENVELOPE_BUCKETS, max(width, 1) * 4)


def absolute_time_to_nudge_x(
    plot: PlotWidget,
    *,
    viewport_start: float,
    time_seconds: float,
) -> int:
    """Map an absolute timestamp to nudge-bar x aligned with plot v-lines."""
    rel_time = time_seconds - viewport_start
    canvas_x, _ = plot.get_pixel_from_coordinate(rel_time, 0.0)
    return int(plot.margin_left) + canvas_x


def nudge_x_to_absolute_time(
    plot: PlotWidget,
    *,
    viewport_start: float,
    nudge_x: float,
) -> float:
    """Map nudge-bar x back to an absolute timestamp."""
    canvas_x = int(round(nudge_x - plot.margin_left))
    rel_time, _ = map_pixel_to_coordinate(
        canvas_x,
        0,
        plot._x_min,
        plot._x_max,
        plot._y_min,
        plot._y_max,
        plot._scale_rectangle,
    )
    return viewport_start + rel_time


def render_waveform_plot(
    plot: PlotWidget,
    *,
    times: np.ndarray,
    mins: np.ndarray,
    maxs: np.ndarray,
    marker_start: float | None = None,
    marker_end: float | None = None,
    playhead: float | None = None,
    use_duration_axis: bool = True,
    x_limits: tuple[float, float] | None = None,
) -> None:
    plot.clear()
    if use_duration_axis:
        plot.set_x_formatter(DurationFormatter())
    if x_limits is not None:
        plot.set_xlimits(x_limits[0], x_limits[1])
        plot.set_ylimits(None, None)
    else:
        # clear() keeps prior zoom/pan limits; reset so a new clip autoscales.
        plot.set_xlimits(None, None)
        plot.set_ylimits(None, None)
    plot.plot(times, maxs, line_style="cyan", hires_mode=HiResMode.BRAILLE)
    plot.plot(times, mins, line_style="cyan", hires_mode=HiResMode.BRAILLE)
    if marker_start is not None:
        plot.add_v_line(marker_start, line_style=START_MARKER_STYLE, label="Start")
    if marker_end is not None:
        plot.add_v_line(marker_end, line_style=END_MARKER_STYLE, label="End")
    if playhead is not None:
        plot.add_v_line(playhead, line_style=PLAYHEAD_STYLE, label="")
    plot.set_xlabel("")
    plot.set_ylabel("")
