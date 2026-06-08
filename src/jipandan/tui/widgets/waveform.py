import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static
from textual_image.widget._base import Image as BaseWaveformImage

from jipandan.core.ffmpeg import WAVEFORM_PIXEL_SIZE
from jipandan.core.models import MIN_CLIP_DURATION_SECONDS
from jipandan.tui.widgets.waveform_renderers import waveform_image_class
from jipandan.core.srt import srt_time_to_seconds

_MARKER_EPSILON_SECONDS = 0.001
_START_MARKER_COLOR = (255, 200, 0, 255)
_END_MARKER_COLOR = (255, 80, 200, 255)
_START_HANDLE_STYLE = "rgb(255,200,0)"
_END_HANDLE_STYLE = "rgb(255,80,200)"
_NUDGE_TRACK_STYLE = "rgb(90,90,122)"
_MARKER_WIDTH_PX = 2
_NUDGE_HANDLE_GRAB_RADIUS = 1
_NUDGE_DRAG_DEBOUNCE_SECONDS = 0.4
_NUDGE_DRAG_DEBOUNCE_MAX_SECONDS = 1.0
_NUDGE_MIN_SCHEDULE_DELAY_SECONDS = 0.001
_NudgeEdge = Literal["start", "end"]

GENERATING_WAVEFORM_PLACEHOLDER = "Generating waveform…"
GENERATING_PREVIEW_PLACEHOLDER = "Generating preview…"
_LOADING_PLACEHOLDERS = frozenset(
    {GENERATING_WAVEFORM_PLACEHOLDER, GENERATING_PREVIEW_PLACEHOLDER}
)


def format_playback_remaining(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"Playing audio ({minutes}:{secs:02d} remaining)"


def _timestamp_seconds(value: str) -> float:
    return srt_time_to_seconds(value.replace(".", ","))


def _time_to_pixel_x(
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


def _time_to_pixel_x_exclusive(
    time_seconds: float,
    range_start: float,
    range_duration: float,
    image_width: int,
) -> int:
    """Map a timestamp to an exclusive right edge for cropping (0..image_width)."""
    if range_duration <= 0 or image_width <= 1:
        return 0
    fraction = (time_seconds - range_start) / range_duration
    fraction = max(0.0, min(1.0, fraction))
    if fraction >= 1.0:
        return image_width
    return min(image_width, int(round(fraction * image_width)))


def _pixel_x_to_time(
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
        self._on_nudge: Callable[[_NudgeEdge, float], None] | None = None
        self._range_start: float | None = None
        self._range_duration: float | None = None
        self._marker_start: float | None = None
        self._marker_end: float | None = None
        self._preview_start: float | None = None
        self._preview_end: float | None = None
        self._dragging: _NudgeEdge | None = None
        self._drag_anchor_start: float | None = None
        self._drag_anchor_end: float | None = None
        self._debounce_timer: Timer | None = None
        self._debounce_started_at: float | None = None
        self._pending_commit_edge: _NudgeEdge | None = None

    def bind_waveform(self, waveform: "WaveformWidget") -> None:
        self._waveform = waveform

    def set_nudge_handler(
        self, handler: Callable[[_NudgeEdge, float], None] | None
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
        start_x = _time_to_pixel_x(
            start_time,
            self._range_start,
            self._range_duration,
            width,
        )
        end_x = _time_to_pixel_x(
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

    def _schedule_commit(self, edge: _NudgeEdge) -> None:
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

    def _commit_pending(self, edge: _NudgeEdge) -> None:
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
            if abs(delta) < _MARKER_EPSILON_SECONDS:
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
            if abs(delta) < _MARKER_EPSILON_SECONDS:
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

    def _hit_test(self, x: float) -> _NudgeEdge | None:
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
        return _pixel_x_to_time(
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


class WaveformWidget(Vertical, can_focus=True):
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

    #waveform-image {
        width: 100%;
        height: 1fr;
        display: none;
    }

    #waveform-placeholder-panel {
        height: 1fr;
        width: 100%;
        align: center middle;
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

    #waveform-update-overlay {
        layer: overlay;
        width: 100%;
        height: 1fr;
        align: center middle;
        background: $surface 50%;
        display: none;
    }

    #waveform-update-loading {
        height: auto;
        width: auto;
    }

    #waveform-nudge-bar {
        height: 1;
        width: 100%;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._base_image_path: Path | None = None
        self._cached_base_path: Path | None = None
        self._cached_base_image: Image.Image | None = None
        self._viewport_start: float | None = None
        self._viewport_duration: float | None = None
        self._media_duration: float | None = None
        self._marker_start: float | None = None
        self._marker_end: float | None = None
        self._preview_marker_start: float | None = None
        self._preview_marker_end: float | None = None
        self._nudge_handler: Callable[[_NudgeEdge, float], None] | None = None
        self._pending_placeholder: str | None = None
        self._pending_image_apply = False
        self._image_update_in_progress = False
        self._image_update_token = 0
        self._nudge_bar: WaveformNudgeBar | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="waveform-placeholder-panel"):
            with Center(id="waveform-loading-row"):
                yield LoadingIndicator(id="waveform-loading")
            with Center(id="waveform-placeholder-row"):
                yield Static(
                    GENERATING_WAVEFORM_PLACEHOLDER,
                    id="waveform-placeholder",
                    markup=False,
                )

    def on_mount(self) -> None:
        image = waveform_image_class(is_web=self.app.is_web)(id="waveform-image")
        image.display = False
        self.mount(image)
        overlay = Center(
            LoadingIndicator(id="waveform-update-loading"),
            id="waveform-update-overlay",
        )
        overlay.display = False
        self.mount(overlay)
        nudge_bar = WaveformNudgeBar(id="waveform-nudge-bar")
        nudge_bar.bind_waveform(self)
        self.mount(nudge_bar)
        self._nudge_bar = nudge_bar
        if self._nudge_handler is not None:
            nudge_bar.set_nudge_handler(self._nudge_handler)
        if self._image_update_in_progress:
            overlay.display = True
        self._flush_pending_display()

    def set_nudge_handler(
        self, handler: Callable[[_NudgeEdge, float], None] | None
    ) -> None:
        self._nudge_handler = handler
        if self._nudge_bar is not None:
            self._nudge_bar.set_nudge_handler(handler)

    def set_marker_preview(self, marker_start: float, marker_end: float) -> None:
        self._preview_marker_start = marker_start
        self._preview_marker_end = marker_end
        if not self._nodes_ready():
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
        if self._base_image_path is None or not self._nodes_ready():
            return
        self._apply_marker_overlay()

    def is_image_update_in_progress(self) -> bool:
        return self._image_update_in_progress

    def _nodes_ready(self) -> bool:
        return (
            len(self.query("#waveform-placeholder-panel")) > 0
            and len(self.query("#waveform-placeholder")) > 0
            and len(self.query("#waveform-image")) > 0
        )

    def _update_overlay_ready(self) -> bool:
        return len(self.query("#waveform-update-overlay")) > 0

    def _show_update_overlay(self) -> None:
        if not self._update_overlay_ready():
            return
        self.query_one("#waveform-update-overlay", Center).display = True

    def _hide_update_overlay(self) -> None:
        if not self._update_overlay_ready():
            return
        self.query_one("#waveform-update-overlay", Center).display = False

    def _begin_image_update(self) -> int:
        self._image_update_token += 1
        self._image_update_in_progress = True
        self._show_update_overlay()
        return self._image_update_token

    def _cancel_image_update(self, token: int | None = None) -> None:
        if token is not None and token != self._image_update_token:
            return
        self._image_update_in_progress = False
        self._hide_update_overlay()

    def _finish_image_update(self, token: int) -> None:
        if token != self._image_update_token:
            return

        def after_layout() -> None:
            if token != self._image_update_token:
                return

            def after_sixel_mount() -> None:
                self._cancel_image_update(token)

            self.call_after_refresh(after_sixel_mount)

        self.call_after_refresh(after_layout)

    @staticmethod
    def _shows_loading_indicator(message: str) -> bool:
        return message in _LOADING_PLACEHOLDERS

    def _clear_base_image_cache(self) -> None:
        self._cached_base_path = None
        self._cached_base_image = None

    def _load_base_image(self) -> Image.Image:
        if self._base_image_path is None:
            raise ValueError("No waveform image loaded")
        path = self._base_image_path
        if (
            self._cached_base_image is not None
            and self._cached_base_path == path
        ):
            return self._cached_base_image
        loaded = Image.open(path).convert("RGBA")
        self._cached_base_path = path
        self._cached_base_image = loaded
        return loaded

    def _flush_pending_display(self) -> None:
        if not self._nodes_ready():
            return
        if self._pending_placeholder is not None:
            message = self._pending_placeholder
            self._pending_placeholder = None
            self.show_placeholder(message)
            return
        if self._pending_image_apply:
            self._pending_image_apply = False
            self._apply_image()

    def show_placeholder(self, message: str) -> None:
        self._cancel_image_update()
        self._base_image_path = None
        self._clear_base_image_cache()
        self._viewport_start = None
        self._viewport_duration = None
        self._media_duration = None
        self._marker_start = None
        self._marker_end = None
        self._preview_marker_start = None
        self._preview_marker_end = None
        self._pending_image_apply = False
        if not self._nodes_ready():
            self._pending_placeholder = message
            return
        self._pending_placeholder = None
        if self._nudge_bar is not None:
            self._nudge_bar.clear()
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        loading = self.query_one("#waveform-loading", LoadingIndicator)
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", BaseWaveformImage)
        placeholder.update(message)
        loading.display = self._shows_loading_indicator(message)
        panel.display = True
        image.display = False

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
        if path != self._base_image_path:
            self._clear_base_image_cache()
        self._base_image_path = path
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
            self._pending_image_apply = True
            self._pending_placeholder = None
            self.call_after_refresh(self._flush_pending_display)
            return
        self._pending_image_apply = False
        self._apply_image()
        self._sync_nudge_bar()

    def overlay_trim_bounds(self, clip_start: str, clip_end: str) -> None:
        if self._base_image_path is None or self._viewport_start is None:
            return
        if self._viewport_duration is None:
            return
        marker_start = _timestamp_seconds(clip_start)
        marker_end = _timestamp_seconds(clip_end)
        if (
            self._marker_start is not None
            and self._marker_end is not None
            and abs(self._marker_start - marker_start) < _MARKER_EPSILON_SECONDS
            and abs(self._marker_end - marker_end) < _MARKER_EPSILON_SECONDS
        ):
            return
        self._marker_start = marker_start
        self._marker_end = marker_end
        if not self._nodes_ready():
            self._pending_image_apply = True
            self._pending_placeholder = None
            self.call_after_refresh(self._flush_pending_display)
            return
        self._pending_image_apply = False
        self._apply_image()
        self._sync_nudge_bar()

    def _sync_nudge_bar(self) -> None:
        if self._nudge_bar is None:
            return
        if self._base_image_path is None or self._marker_start is None:
            self._nudge_bar.clear()
            return
        if self._marker_end is None:
            self._nudge_bar.clear()
            return
        image_start, image_duration, _image_end = self._image_time_range()
        self._nudge_bar.set_time_range(image_start, image_duration)
        self._nudge_bar.sync_markers(self._marker_start, self._marker_end)
        self._nudge_bar.show()

    def _markers_match_viewport(self) -> bool:
        if (
            self._viewport_start is None
            or self._viewport_duration is None
            or self._marker_start is None
            or self._marker_end is None
        ):
            return True
        marker_duration = self._marker_end - self._marker_start
        return (
            abs(self._marker_start - self._viewport_start) < _MARKER_EPSILON_SECONDS
            and abs(marker_duration - self._viewport_duration)
            < _MARKER_EPSILON_SECONDS
        )

    def _image_time_range(self) -> tuple[float, float, float]:
        image_start = self._viewport_start
        assert image_start is not None
        image_duration = self._media_duration or self._viewport_duration
        assert image_duration is not None
        return image_start, image_duration, image_start + image_duration

    def _marker_draw_range(self) -> tuple[float, float, float, float, float]:
        """Return image bounds and marker times clamped to the loaded waveform."""
        image_start, image_duration, image_end = self._image_time_range()
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
        assert marker_start is not None and marker_end is not None
        draw_start = max(image_start, min(marker_start, image_end))
        draw_end = max(draw_start, min(marker_end, image_end))
        return image_start, image_duration, image_end, draw_start, draw_end

    def _render_image(self) -> Image.Image:
        base = self._load_base_image()
        if self._markers_match_viewport():
            return base.copy()

        image_start, image_duration, image_end, draw_start, draw_end = (
            self._marker_draw_range()
        )

        width, height = base.size
        canvas = base.copy()

        start_x = _time_to_pixel_x(
            draw_start, image_start, image_duration, width
        )
        end_x = _time_to_pixel_x(
            draw_end, image_start, image_duration, width
        )
        draw = ImageDraw.Draw(canvas)
        for x, color in ((start_x, _START_MARKER_COLOR), (end_x, _END_MARKER_COLOR)):
            x0 = max(0, x - _MARKER_WIDTH_PX // 2)
            x1 = min(width - 1, x + _MARKER_WIDTH_PX // 2)
            draw.rectangle((x0, 0, x1, height - 1), fill=color)
        return canvas

    def _apply_marker_overlay(self) -> None:
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        image = self.query_one("#waveform-image", BaseWaveformImage)
        try:
            image.image = self._render_image()
        except OSError:
            return
        panel.display = False
        image.display = True
        image.refresh()

    def _apply_image(self) -> None:
        token = self._begin_image_update()
        panel = self.query_one("#waveform-placeholder-panel", Vertical)
        image = self.query_one("#waveform-image", BaseWaveformImage)
        try:
            image.image = self._render_image()
        except OSError as exc:
            self._cancel_image_update(token)
            self.show_placeholder(f"Waveform failed: {exc}")
            return
        panel.display = False
        image.display = True
        image.refresh()
        self.call_after_refresh(partial(self._finish_image_update, token))

    @staticmethod
    def expected_pixel_size() -> tuple[int, int]:
        return WAVEFORM_PIXEL_SIZE
