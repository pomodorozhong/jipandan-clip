from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

FILTER_ORDER = ["unsorted", "group1", "group2", "exported", "all"]
FILTER_BAR_LABELS: dict[str, str] = {
    "all": "All",
    "unsorted": "Unsorted",
    "group1": "G1",
    "group2": "G2",
    "exported": "Exported",
}

FILTER_LABELS: dict[str, str] = {
    "all": "All",
    "unsorted": "Unsorted",
    "group1": "Group 1",
    "group2": "Group 2",
    "exported": "Exported",
}


def _filter_index(mode: str) -> int:
    try:
        return FILTER_ORDER.index(mode)
    except ValueError:
        return 0


class FilterSelectionModal(ModalScreen[str | None]):
    """Pick which clip filter to show in the review list."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "confirm", "Apply", show=False),
    ]

    DEFAULT_CSS = """
    FilterSelectionModal {
        align: center middle;
    }

    #filter-dialog {
        width: 48;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #filter-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(self, current_filter: str) -> None:
        super().__init__()
        self._current_filter = current_filter

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"):
            yield Label("Filter clips")
            yield OptionList(
                *[
                    Option(FILTER_LABELS[mode], id=mode)
                    for mode in FILTER_ORDER
                ],
                id="filter-list",
            )
            yield Label(
                "Enter = apply  Esc = cancel",
                id="filter-hint",
            )

    def on_mount(self) -> None:
        option_list = self.query_one("#filter-list", OptionList)
        option_list.focus()
        option_list.highlighted = _filter_index(self._current_filter)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "filter-list":
            return
        mode = event.option.id
        if mode in FILTER_ORDER:
            self.dismiss(mode)

    def _selected_mode(self) -> str | None:
        option_list = self.query_one("#filter-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        mode = option_list.get_option_at_index(highlighted).id
        if mode in FILTER_ORDER:
            return mode
        return None

    def action_confirm(self) -> None:
        mode = self._selected_mode()
        if mode is None:
            self.notify("Select a filter", severity="warning")
            return
        self.dismiss(mode)

    def action_cancel(self) -> None:
        self.dismiss(None)
