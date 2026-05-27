from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class ExportTitleModal(ModalScreen[str | None]):
    """Prompt for the clip title used in the exported filename."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "copy_title", "Copy", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ExportTitleModal {
        align: center middle;
    }

    #export-dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #export-title-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(self, default_title: str) -> None:
        super().__init__()
        self._default_title = default_title

    def compose(self) -> ComposeResult:
        with Vertical(id="export-dialog"):
            yield Label("Export clip title")
            yield Input(self._default_title, id="export-title-input")
            yield Label("Enter = export  Esc = cancel  Ctrl+C = copy", id="export-title-hint")

    def on_mount(self) -> None:
        self.query_one("#export-title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "export-title-input":
            self._confirm()

    def action_copy_title(self) -> None:
        title = self.query_one("#export-title-input", Input).value
        if not title:
            self.notify("Nothing to copy", severity="warning")
            return
        self.app.copy_to_clipboard(title)
        self.notify("Title copied to clipboard")

    def _confirm(self) -> None:
        value = self.query_one("#export-title-input", Input).value.strip()
        if not value:
            self.notify("Title cannot be empty", severity="warning")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
