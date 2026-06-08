import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from rich.text import Text
from textual import events
from textual.timer import Timer
from textual.widget import Widget

from jipandan.core.models import MIN_CLIP_DURATION_SECONDS

if TYPE_CHECKING:
    from jipandan.tui.widgets.waveform import WaveformWidget

MARKER_EPSILON_SECONDS = 0.001
_START_HANDLE_STYLE = "rgb(255,200,0)"
_END_HANDLE_STYLE = "rgb(255,80,200)"
_NUDGE_TRACK_STYLE = "rgb(90,90,122)"
_NUDGE_HANDLE_GRAB_RADIUS = 1
_NUDGE_DRAG_DEBOUNCE_SECONDS = 0.4
_NUDGE_DRAG_DEBOUNCE_MAX_SECONDS = 1.0
_NUDGE_MIN_SCHEDULE_DELAY_SECONDS = 0.001
NudgeEdge = Literal["start", "end"]


def time_to_pixel_x(
    time_seconds: float,
    range_start: float,
    range_duration: float,
    image_width: int,
) -> int:
    """Map a timestamp to an inclusive x coordinate in [0, image_width - 1]."""
    if range_duration <= 0 or image_width <= 1:
        return 0
    fraction = (time_seconds - range_start) / range_duration
    fraction = max(0.0, min(1.0, fraction))
    return min(image_width - 1, int(round(fraction * (image_width - 1))))


def pixel_x_to_time(
    pixel_x: float,
    range_start: float,
    range_duration: float,
    width: int,
) -> float:
    if range_duration <= 0 or width <= 1:
        return range_start
    fraction = max(0.0, min(1.0, pixel_x / (width - 1)))
    return range_start + fraction * range_duration


class WaveformNudgeBar(Widget):
    """Draggable trim handles rendered under the waveform image."""

    DEFAULT_CSS = """
    WaveformNudgeBar {
        height: 1;
        width: 100%;
        display: none;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._waveform: WaveformWidget | None = None
        self._on_nudge: Callable[[NudgeEdge, float], None] | None = None
        self._range_start: float | None = None
        self._range_duration: float | None = None
        self._marker_start: float | None = None
        self._marker_end: float | None = None
        self._preview_start: float | None = None
        self._preview_end: float | None = None
        self._dragging: NudgeEdge | None = None
        self._drag_anchor_start: float | None = None
        self._drag_anchor_end: float | None = None
        self._debounce_timer: Timer | None = None
        self._debounce_started_at: float | None = None
        self._pending_commit_edge: NudgeEdge | None = None

    def bind_waveform(self, waveform: "WaveformWidget") -> None:
        self._waveform = waveform

    def set_nudge_handler(
        self, handler: Callable[[NudgeEdge, float], None] | None
    ) -> None:
        self._on_nudge = handler

    def set_time_range(self, range_start: float, range_duration: float) -> None:
        if (
            self._range_start == range_start
            and self._range_duration == range_duration
        ):
            return
        self._range_start = range_start
        self._range_duration = range_duration
        if self._dragging is None:
            self._clear_preview()
        self.refresh()

    def sync_markers(self, marker_start: float, marker_end: float) -> None:
        self._marker_start = marker_start
        self._marker_end = marker_end
        if self._dragging is None:
            self._preview_start = None
            self._preview_end = None
        self.refresh()

    def clear(self) -> None:
        self._cancel_debounce()
        self._dragging = None
        self._drag_anchor_start = None
        self._drag_anchor_end = None
        self._range_start = None
        self._range_duration = None
        self._marker_start = None
        self._marker_end = None
        self._preview_start = None
        self._preview_end = None
        self.display = False
        self.refresh()

    def show(self) -> None:
        self.display = True
        self.refresh()

    def _clear_preview(self) -> None:
        self._preview_start = None
        self._preview_end = None
        if self._waveform is not None:
            self._waveform.clear_marker_preview()

    def _effective_start(self) -> float | None:
        if self._preview_start is not None:
            return self._preview_start
        return self._marker_start

    def _effective_end(self) -> float | None:
        if self._preview_end is not None:
            return self._preview_end
        return self._marker_end

    def _handle_x_positions(self, width: int) -> tuple[int | None, int | None]:
        if (
            self._range_start is None
            or self._range_duration is None
            or width <= 0
        ):
            return None, None
        start_time = self._effective_start()
        end_time = self._effective_end()
        if start_time is None or end_time is None:
            return None, None
        start_x = time_to_pixel_x(
            start_time,
            self._range_start,
            self._range_duration,
            width,
        )
        end_x = time_to_pixel_x(
            end_time,
            self._range_start,
            self._range_duration,
            width,
        )
        return start_x, end_x

    def _clamp_start(self, time_seconds: float, end_time: float) -> float:
        if self._range_start is None:
            return time_seconds
        latest_start = max(self._range_start, end_time - MIN_CLIP_DURATION_SECONDS)
        return max(self._range_start, min(latest_start, time_seconds))

    def _clamp_end(self, time_seconds: float, start_time: float) -> float:
        range_end = self._range_start
        if range_end is None or self._range_duration is None:
            return time_seconds
        range_end += self._range_duration
        earliest_end = start_time + MIN_CLIP_DURATION_SECONDS
        return max(earliest_end, min(range_end, time_seconds))

    def _apply_preview(self) -> None:
        if self._waveform is None:
            return
        start_time = self._effective_start()
        end_time = self._effective_end()
        if start_time is None or end_time is None:
            return
        self._waveform.set_marker_preview(start_time, end_time)
        self.refresh()

    def _cancel_debounce(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None
        self._debounce_started_at = None
        self._pending_commit_edge = None

    def _schedule_commit(self, edge: NudgeEdge) -> None:
        self._pending_commit_edge = edge
        now = time.monotonic()
        if self._debounce_started_at is None:
            self._debounce_started_at = now

        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None

        elapsed = now - self._debounce_started_at
        if elapsed >= _NUDGE_DRAG_DEBOUNCE_MAX_SECONDS:
            delay = 0.0
        else:
            delay = min(
                _NUDGE_DRAG_DEBOUNCE_SECONDS,
                _NUDGE_DRAG_DEBOUNCE_MAX_SECONDS - elapsed,
            )

        def commit() -> None:
            self._debounce_timer = None
            self._debounce_started_at = None
            pending_edge = self._pending_commit_edge
            self._pending_commit_edge = None
            if pending_edge is None:
                return
            self._commit_pending(pending_edge)

        self._debounce_timer = self.set_timer(
            max(delay, _NUDGE_MIN_SCHEDULE_DELAY_SECONDS),
            commit,
            name="nudge-drag-debounce",
        )

    def _commit_pending(self, edge: NudgeEdge) -> None:
        if self._on_nudge is None:
            return
        if self._waveform is not None and self._waveform.is_image_update_in_progress():
            return

        if edge == "start":
            anchor = self._drag_anchor_start
            preview = self._effective_start()
            if anchor is None or preview is None:
                return
            delta = preview - anchor
            if abs(delta) < MARKER_EPSILON_SECONDS:
                return
            self._on_nudge("start", delta)
            self._drag_anchor_start = self._marker_start
            if self._dragging is None:
                self._preview_start = None
            elif self._marker_start is not None:
                self._preview_start = self._marker_start
        else:
            anchor = self._drag_anchor_end
            preview = self._effective_end()
            if anchor is None or preview is None:
                return
            delta = preview - anchor
            if abs(delta) < MARKER_EPSILON_SECONDS:
                return
            self._on_nudge("end", delta)
            self._drag_anchor_end = self._marker_end
            if self._dragging is None:
                self._preview_end = None
            elif self._marker_end is not None:
                self._preview_end = self._marker_end

        if self._dragging is None:
            self._clear_preview()
        else:
            start_time = self._effective_start()
            end_time = self._effective_end()
            if start_time is not None and end_time is not None:
                self._apply_preview()
        self.refresh()

    def _hit_test(self, x: float) -> NudgeEdge | None:
        width = self.size.width
        if width <= 0:
            return None
        start_x, end_x = self._handle_x_positions(width)
        if start_x is None or end_x is None:
            return None
        if abs(x - start_x) <= _NUDGE_HANDLE_GRAB_RADIUS:
            return "start"
        if abs(x - end_x) <= _NUDGE_HANDLE_GRAB_RADIUS:
            return "end"
        return None

    def _time_from_event(self, event: events.MouseEvent) -> float | None:
        if self._range_start is None or self._range_duration is None:
            return None
        width = self.size.width
        if width <= 0:
            return None
        return pixel_x_to_time(
            event.x,
            self._range_start,
            self._range_duration,
            width,
        )

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self._waveform is not None and self._waveform.is_image_update_in_progress():
            return
        edge = self._hit_test(event.x)
        if edge is None:
            return
        if self._marker_start is None or self._marker_end is None:
            return
        event.stop()
        self.capture_mouse()
        self._cancel_debounce()
        self._dragging = edge
        self._drag_anchor_start = self._marker_start
        self._drag_anchor_end = self._marker_end
        self._preview_start = self._marker_start
        self._preview_end = self._marker_end

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging is None:
            return
        time_seconds = self._time_from_event(event)
        if time_seconds is None:
            return
        event.stop()
        start_time = self._effective_start()
        end_time = self._effective_end()
        if start_time is None or end_time is None:
            return
        if self._dragging == "start":
            self._preview_start = self._clamp_start(time_seconds, end_time)
        else:
            self._preview_end = self._clamp_end(time_seconds, start_time)
        self._apply_preview()
        self._schedule_commit(self._dragging)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging is None:
            return
        event.stop()
        edge = self._dragging
        self._dragging = None
        self.release_mouse()
        self._schedule_commit(edge)

    def render(self) -> Text:
        width = max(self.size.width, 0)
        if (
            width <= 0
            or self._range_start is None
            or self._range_duration is None
        ):
            return Text("")

        start_x, end_x = self._handle_x_positions(width)
        if start_x is None or end_x is None:
            return Text("")

        line = Text()
        for x in range(width):
            if x == start_x:
                line.append("█", style=_START_HANDLE_STYLE)
            elif x == end_x:
                line.append("█", style=_END_HANDLE_STYLE)
            else:
                line.append("─", style=_NUDGE_TRACK_STYLE)
        return line
