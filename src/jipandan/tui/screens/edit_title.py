from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class EditTitleModal(ModalScreen[str | None]):
    """Prompt to rename a clip's title."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+l", "clear_input", "Clear", show=False),
        Binding("ctrl+c", "copy_title", "Copy", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    EditTitleModal {
        align: center middle;
    }

    #edit-title-dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-title-buttons {
        height: auto;
        padding-top: 1;
    }

    #edit-title-clear {
        margin-right: 1;
    }

    #edit-title-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(self, current_title: str, clip_id: str) -> None:
        super().__init__()
        self._current_title = current_title
        self._clip_id = clip_id

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-title-dialog"):
            yield Label(f"Edit title for #{self._clip_id}")
            yield Input(self._current_title, id="edit-title-input")
            with Horizontal(id="edit-title-buttons"):
                yield Button("Clear", id="edit-title-clear", variant="warning")
            yield Label(
                "Enter = save  Esc = cancel  Ctrl+L = clear  Ctrl+C = copy",
                id="edit-title-hint",
            )

    def on_mount(self) -> None:
        input_widget = self.query_one("#edit-title-input", Input)
        input_widget.focus()
        input_widget.cursor_position = len(input_widget.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "edit-title-input":
            self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-title-clear":
            self._clear_input()

    def action_clear_input(self) -> None:
        self._clear_input()

    def action_copy_title(self) -> None:
        title = self.query_one("#edit-title-input", Input).value
        if not title:
            self.notify("Nothing to copy", severity="warning")
            return
        self.app.copy_to_clipboard(title)
        self.notify("Title copied to clipboard")

    def _clear_input(self) -> None:
        input_widget = self.query_one("#edit-title-input", Input)
        input_widget.value = ""
        input_widget.focus()

    def _confirm(self) -> None:
        value = self.query_one("#edit-title-input", Input).value.strip()
        if not value:
            self.notify("Title cannot be empty", severity="warning")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
