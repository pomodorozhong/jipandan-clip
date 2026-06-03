from pathlib import Path

from PIL import Image, ImageDraw
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.widget._base import Image as BaseWaveformImage

from jipandan.core.ffmpeg import WAVEFORM_PIXEL_SIZE
from jipandan.tui.widgets.waveform_renderers import waveform_image_class
from jipandan.core.srt import srt_time_to_seconds

_MARKER_EPSILON_SECONDS = 0.001
_START_MARKER_COLOR = (255, 200, 0, 255)
_END_MARKER_COLOR = (255, 80, 200, 255)
_MARKER_WIDTH_PX = 2


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

    #waveform-placeholder {
        height: 1fr;
        content-align: center middle;
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
        self._pending_placeholder: str | None = None
        self._pending_image_apply = False

    def compose(self) -> ComposeResult:
        yield Static(
            "Generating waveform…",
            id="waveform-placeholder",
            markup=False,
        )

    def on_mount(self) -> None:
        image = waveform_image_class(is_web=self.app.is_web)(id="waveform-image")
        image.display = False
        self.mount(image)
        self._flush_pending_display()

    def _nodes_ready(self) -> bool:
        return (
            len(self.query("#waveform-placeholder")) > 0
            and len(self.query("#waveform-image")) > 0
        )

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
        self._base_image_path = None
        self._clear_base_image_cache()
        self._viewport_start = None
        self._viewport_duration = None
        self._media_duration = None
        self._marker_start = None
        self._marker_end = None
        self._pending_image_apply = False
        if not self._nodes_ready():
            self._pending_placeholder = message
            return
        self._pending_placeholder = None
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", BaseWaveformImage)
        placeholder.update(message)
        placeholder.display = True
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
            return
        self._pending_image_apply = False
        self._apply_image()

    def overlay_trim_bounds(self, clip_start: str, clip_end: str) -> None:
        if self._base_image_path is None or self._viewport_start is None:
            return
        if self._viewport_duration is None:
            return
        self._marker_start = _timestamp_seconds(clip_start)
        self._marker_end = _timestamp_seconds(clip_end)
        if not self._nodes_ready():
            self._pending_image_apply = True
            self._pending_placeholder = None
            return
        self._pending_image_apply = False
        self._apply_image()

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

    def _render_image(self) -> Image.Image:
        base = self._load_base_image()
        if self._markers_match_viewport():
            return base.copy()

        image_start, image_duration, image_end = self._image_time_range()
        marker_start = self._marker_start
        marker_end = self._marker_end
        assert marker_start is not None and marker_end is not None

        render_start = min(image_start, marker_start)
        render_end = max(image_end, marker_end)
        render_duration = max(render_end - render_start, _MARKER_EPSILON_SECONDS)

        width, height = base.size
        if render_duration > image_duration + _MARKER_EPSILON_SECONDS:
            src_left = _time_to_pixel_x(
                image_start, image_start, image_duration, width
            )
            src_right = _time_to_pixel_x_exclusive(
                image_end, image_start, image_duration, width
            )
            crop = base.crop((src_left, 0, src_right, height))
            dst_left = _time_to_pixel_x(
                image_start, render_start, render_duration, width
            )
            dst_right = _time_to_pixel_x_exclusive(
                image_end, render_start, render_duration, width
            )
            target_width = max(1, dst_right - dst_left)
            if crop.width != target_width:
                crop = crop.resize((target_width, height), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            canvas.paste(crop, (dst_left, 0))
        else:
            canvas = base.copy()

        start_x = _time_to_pixel_x(
            marker_start, render_start, render_duration, width
        )
        end_x = _time_to_pixel_x(
            marker_end, render_start, render_duration, width
        )
        draw = ImageDraw.Draw(canvas)
        for x, color in ((start_x, _START_MARKER_COLOR), (end_x, _END_MARKER_COLOR)):
            x0 = max(0, x - _MARKER_WIDTH_PX // 2)
            x1 = min(width - 1, x + _MARKER_WIDTH_PX // 2)
            draw.rectangle((x0, 0, x1, height - 1), fill=color)
        return canvas

    def _apply_image(self) -> None:
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", BaseWaveformImage)
        try:
            image.image = self._render_image()
        except OSError as exc:
            self.show_placeholder(f"Waveform failed: {exc}")
            return
        placeholder.display = False
        image.display = True
        image.refresh()

    @staticmethod
    def expected_pixel_size() -> tuple[int, int]:
        return WAVEFORM_PIXEL_SIZE
