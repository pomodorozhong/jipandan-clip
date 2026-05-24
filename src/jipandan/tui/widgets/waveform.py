from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.widget import Image as TerminalImage

FINETUNE_HELP = (
    "Space play  [ start −0.1s  ] start +0.1s  "
    "{ end −0.1s  } end +0.1s  e export"
)


def format_playback_remaining(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"Playing audio ({minutes}:{secs:02d} remaining)"


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

    def compose(self) -> ComposeResult:
        yield Static("Generating waveform…", id="waveform-placeholder")
        yield TerminalImage(id="waveform-image")

    def show_placeholder(self, message: str) -> None:
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", TerminalImage)
        placeholder.update(message)
        placeholder.display = True
        image.display = False

    def update_image(self, path: Path) -> None:
        if not path.exists():
            self.show_placeholder(f"Waveform not found: {path}")
            return
        placeholder = self.query_one("#waveform-placeholder", Static)
        image = self.query_one("#waveform-image", TerminalImage)
        image.image = str(path)
        placeholder.display = False
        image.display = True
        image.refresh()
