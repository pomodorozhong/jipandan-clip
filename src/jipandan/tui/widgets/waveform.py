from pathlib import Path

from PIL import Image, ImageDraw
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.widget import Image as TerminalImage

from jipandan.core.ffmpeg import WAVEFORM_PIXEL_SIZE
from jipandan.core.srt import srt_time_to_seconds

FINETUNE_HELP = (
    "Space play  [ start −0.1s  ] start +0.1s  "
    "{ end −0.1s  } end +0.1s  e export"
)

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
    viewport_start: float,
    viewport_duration: float,
    image_width: int,
) -> int:
    if viewport_duration <= 0 or image_width <= 1:
        return 0
    fraction = (time_seconds - viewport_start) / viewport_duration
    fraction = max(0.0, min(1.0, fraction))
    return int(round(fraction * (image_width - 1)))


class WaveformWidget(Vertical):
    DEFAULT_CSS = """
    WaveformWidget {
        height: 1fr;
        min-height: 6;
        padding: 1 0 0 0;
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
        self._viewport_start: float | None = None
        self._viewport_duration: float | None = None
        self._marker_start: float | None = None
        self._marker_end: float | None = None

    def compose(self) -> ComposeResult:
        yield Static("Generating waveform…", id="waveform-placeholder")
        yield TerminalImage(id="waveform-image")

    def show_placeholder(self, message: str) -> None:
        self._base_image_path = None
        self._viewport_start = None
        self._viewport_duration = None
        self._marker_start = None
        self._marker_end = None
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", TerminalImage)
        placeholder.update(message)
        placeholder.display = True
        image.display = False

    def display_waveform(
        self,
        path: Path,
        viewport_start: str,
        viewport_duration: str,
    ) -> None:
        if not path.exists():
            self.show_placeholder(f"Waveform not found: {path}")
            return
        self._base_image_path = path
        self._viewport_start = _timestamp_seconds(viewport_start)
        self._viewport_duration = float(viewport_duration)
        viewport_end = self._viewport_start + self._viewport_duration
        self._marker_start = self._viewport_start
        self._marker_end = viewport_end
        self._apply_image()

    def overlay_trim_bounds(self, clip_start: str, clip_end: str) -> None:
        if self._base_image_path is None or self._viewport_start is None:
            return
        if self._viewport_duration is None:
            return
        self._marker_start = _timestamp_seconds(clip_start)
        self._marker_end = _timestamp_seconds(clip_end)
        self._apply_image()

    def _markers_match_viewport(self) -> bool:
        if (
            self._viewport_start is None
            or self._viewport_duration is None
            or self._marker_start is None
            or self._marker_end is None
        ):
            return True
        viewport_end = self._viewport_start + self._viewport_duration
        return (
            abs(self._marker_start - self._viewport_start) < _MARKER_EPSILON_SECONDS
            and abs(self._marker_end - viewport_end) < _MARKER_EPSILON_SECONDS
        )

    def _render_image(self) -> Image.Image:
        if self._base_image_path is None:
            raise ValueError("No waveform image loaded")
        base = Image.open(self._base_image_path).convert("RGBA")
        if self._markers_match_viewport():
            return base

        width, height = base.size
        start_x = _time_to_pixel_x(
            self._marker_start,
            self._viewport_start,
            self._viewport_duration,
            width,
        )
        end_x = _time_to_pixel_x(
            self._marker_end,
            self._viewport_start,
            self._viewport_duration,
            width,
        )
        draw = ImageDraw.Draw(base)
        for x, color in ((start_x, _START_MARKER_COLOR), (end_x, _END_MARKER_COLOR)):
            x0 = max(0, x - _MARKER_WIDTH_PX // 2)
            x1 = min(width - 1, x + _MARKER_WIDTH_PX // 2)
            draw.rectangle((x0, 0, x1, height - 1), fill=color)
        return base

    def _apply_image(self) -> None:
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", TerminalImage)
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
