from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class JumpToIndexModal(ModalScreen[str | None]):
    """Prompt for the clip index to jump to."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    JumpToIndexModal {
        align: center middle;
    }

    #jump-index-dialog {
        width: 48;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #jump-index-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="jump-index-dialog"):
            yield Label("Jump to clip index")
            yield Input(placeholder="e.g. 123", id="jump-index-input")
            yield Label("Enter = jump  Esc = cancel", id="jump-index-hint")

    def on_mount(self) -> None:
        self.query_one("#jump-index-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "jump-index-input":
            return
        self.dismiss(event.input.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
