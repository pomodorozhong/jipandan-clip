"""Shared textual-plot rendering helpers for waveform widgets."""

from __future__ import annotations

import numpy as np
from textual_plot import DurationFormatter, HiResMode, PlotWidget
from textual_plot.plot_widget import map_pixel_to_coordinate

START_MARKER_STYLE = "rgb(255,200,0)"
END_MARKER_STYLE = "rgb(255,80,200)"
DEFAULT_ENVELOPE_BUCKETS = 800


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
    use_duration_axis: bool = True,
    x_limits: tuple[float, float] | None = None,
) -> None:
    plot.clear()
    if use_duration_axis:
        plot.set_x_formatter(DurationFormatter())
    plot.plot(times, maxs, line_style="cyan", hires_mode=HiResMode.BRAILLE)
    plot.plot(times, mins, line_style="cyan", hires_mode=HiResMode.BRAILLE)
    if marker_start is not None:
        plot.add_v_line(marker_start, line_style=START_MARKER_STYLE, label="Start")
    if marker_end is not None:
        plot.add_v_line(marker_end, line_style=END_MARKER_STYLE, label="End")
    plot.set_xlabel("Time")
    plot.set_ylabel("Amplitude")
    if x_limits is not None:
        plot.set_xlimits(x_limits[0], x_limits[1])
        plot.set_ylimits(None, None)
