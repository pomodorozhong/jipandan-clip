from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


@dataclass(frozen=True)
class TrimOffsets:
    start: float
    end: float


def parse_offset_seconds(value: str, *, field_name: str) -> float:
    """Parse a signed offset in seconds, e.g. +5, -35, 0.5."""
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} offset cannot be empty")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} offset must be a number of seconds, e.g. +5 or -35"
        ) from exc


def format_offset_seconds(offset_seconds: float) -> str:
    if offset_seconds == int(offset_seconds):
        return f"{int(offset_seconds):+d}"
    return f"{offset_seconds:+.3f}"


class StartOffsetModal(ModalScreen[TrimOffsets | None]):
    """Prompt for start/end offsets in seconds relative to the original SRT times."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    StartOffsetModal {
        align: center middle;
    }

    #offset-dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #offset-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(self, default_start_offset: float, default_end_offset: float) -> None:
        super().__init__()
        self._default_start_offset = default_start_offset
        self._default_end_offset = default_end_offset

    def compose(self) -> ComposeResult:
        with Vertical(id="offset-dialog"):
            yield Label("Start offset from original (seconds)")
            yield Input(
                format_offset_seconds(self._default_start_offset),
                id="start-offset-input",
                placeholder="+5 or -35",
            )
            yield Label("End offset from original (seconds)")
            yield Input(
                format_offset_seconds(self._default_end_offset),
                id="end-offset-input",
                placeholder="+2 or -10",
            )
            yield Label(
                "Enter on end field = apply  Esc = cancel",
                id="offset-hint",
            )

    def on_mount(self) -> None:
        input_widget = self.query_one("#start-offset-input", Input)
        input_widget.focus()
        input_widget.cursor_position = len(input_widget.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "start-offset-input":
            self.query_one("#end-offset-input", Input).focus()
            return
        if event.input.id == "end-offset-input":
            self._confirm()

    def _confirm(self) -> None:
        try:
            start_offset = parse_offset_seconds(
                self.query_one("#start-offset-input", Input).value,
                field_name="Start",
            )
            end_offset = parse_offset_seconds(
                self.query_one("#end-offset-input", Input).value,
                field_name="End",
            )
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.dismiss(TrimOffsets(start=start_offset, end=end_offset))

    def action_cancel(self) -> None:
        self.dismiss(None)
