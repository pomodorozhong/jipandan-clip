from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from jipandan.core.ffmpeg import (
    DEFAULT_START_THRESHOLD_DB,
    DEFAULT_STOP_THRESHOLD_DB,
    DEFAULT_TRIM_ALL_THRESHOLD_DB,
    ExportMode,
    ExportOptions,
)
from jipandan.tui.widgets.stepper import SteppedNumberInput

_EXPORT_MODE_OPTIONS: list[tuple[ExportMode, str]] = [
    ("as_is", "As is"),
    ("trim_edges", "Remove leading and trailing silence"),
    ("trim_all", "Trim all silence (including middle)"),
]

_DEFAULT_INDEX = 1
_MIN_THRESHOLD_DB = -90.0
_MAX_THRESHOLD_DB = -5.0


def _mode_index(mode: ExportMode) -> int:
    for index, (candidate, _label) in enumerate(_EXPORT_MODE_OPTIONS):
        if candidate == mode:
            return index
    return _DEFAULT_INDEX


class ThresholdDbInput(SteppedNumberInput):
    """dB input that steps with arrow keys and clamps to the valid range."""

    def _parse(self, raw: str) -> float:
        return float(raw.strip().lower().removesuffix("db"))

    def _clamp(self, value: float) -> float:
        return max(_MIN_THRESHOLD_DB, min(_MAX_THRESHOLD_DB, value))


class ExportModeModal(ModalScreen[ExportOptions | None]):
    """Pick export mode and silence thresholds before naming the clip."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+enter", "confirm", "Continue", show=True),
    ]

    DEFAULT_CSS = """
    ExportModeModal {
        align: center middle;
    }

    #export-dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #threshold-row {
        height: auto;
        padding-top: 1;
    }

    #threshold-row Input {
        width: 1fr;
    }

    #export-mode-hint {
        color: $text-muted;
        padding-top: 1;
    }

    #threshold-row.disabled {
        opacity: 0.4;
    }
    """

    def __init__(self, initial_options: ExportOptions | None = None) -> None:
        super().__init__()
        self._initial_options = initial_options

    def compose(self) -> ComposeResult:
        with Vertical(id="export-dialog"):
            yield Label("Export mode")
            yield OptionList(
                *[
                    Option(label, id=mode)
                    for mode, label in _EXPORT_MODE_OPTIONS
                ],
                id="export-mode-list",
            )
            with Horizontal(id="threshold-row"):
                yield Label("Start dB:", classes="threshold-label")
                yield ThresholdDbInput(
                    str(DEFAULT_START_THRESHOLD_DB),
                    id="start-threshold-db",
                    type="number",
                )
                yield Label("Stop dB:", classes="threshold-label")
                yield ThresholdDbInput(
                    str(DEFAULT_STOP_THRESHOLD_DB),
                    id="stop-threshold-db",
                    type="number",
                )
            yield Label(
                "Less negative dB trims more (e.g. -30 vs -50).  Ctrl+Enter = continue  Esc = cancel",
                id="export-mode-hint",
            )

    def on_mount(self) -> None:
        option_list = self.query_one("#export-mode-list", OptionList)
        option_list.focus()
        initial = self._initial_options
        if initial is None:
            option_list.highlighted = _DEFAULT_INDEX
            self._apply_defaults_for_mode("trim_edges")
            return
        option_list.highlighted = _mode_index(initial.mode)
        self._apply_defaults_for_mode(initial.mode)
        if initial.mode != "as_is":
            self.query_one("#start-threshold-db", Input).value = str(
                initial.start_threshold_db
            )
            self.query_one("#stop-threshold-db", Input).value = str(
                initial.stop_threshold_db
            )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != "export-mode-list":
            return
        mode = event.option.id
        if mode in ("as_is", "trim_edges", "trim_all"):
            self._apply_defaults_for_mode(mode)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "export-mode-list":
            return
        mode = event.option.id
        if mode == "as_is":
            self.action_confirm()
            return
        self.query_one("#start-threshold-db", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "start-threshold-db":
            self.query_one("#stop-threshold-db", Input).focus()
            return
        if event.input.id in ("start-threshold-db", "stop-threshold-db"):
            self.action_confirm()

    def _apply_defaults_for_mode(self, mode: ExportMode) -> None:
        threshold_row = self.query_one("#threshold-row")
        start_input = self.query_one("#start-threshold-db", Input)
        stop_input = self.query_one("#stop-threshold-db", Input)
        if mode == "as_is":
            threshold_row.add_class("disabled")
            start_input.disabled = True
            stop_input.disabled = True
            return
        threshold_row.remove_class("disabled")
        start_input.disabled = False
        stop_input.disabled = False
        if mode == "trim_all":
            value = str(DEFAULT_TRIM_ALL_THRESHOLD_DB)
            start_input.value = value
            stop_input.value = value
        else:
            start_input.value = str(DEFAULT_START_THRESHOLD_DB)
            stop_input.value = str(DEFAULT_STOP_THRESHOLD_DB)

    def _selected_mode(self) -> ExportMode | None:
        option_list = self.query_one("#export-mode-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        mode = option.id
        if mode in ("as_is", "trim_edges", "trim_all"):
            return mode
        return None

    @staticmethod
    def _parse_threshold_db(raw: str, field_name: str) -> float:
        text = raw.strip().lower().removesuffix("db")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number") from exc
        if not _MIN_THRESHOLD_DB <= value <= _MAX_THRESHOLD_DB:
            raise ValueError(
                f"{field_name} must be between {_MIN_THRESHOLD_DB:g} and {_MAX_THRESHOLD_DB:g} dB"
            )
        return value

    def action_confirm(self) -> None:
        mode = self._selected_mode()
        if mode is None:
            self.notify("Select an export mode", severity="warning")
            return
        if mode == "as_is":
            self.dismiss(ExportOptions(mode=mode))
            return
        try:
            start_db = self._parse_threshold_db(
                self.query_one("#start-threshold-db", Input).value,
                "Start threshold",
            )
            stop_db = self._parse_threshold_db(
                self.query_one("#stop-threshold-db", Input).value,
                "Stop threshold",
            )
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.dismiss(
            ExportOptions(
                mode=mode,
                start_threshold_db=start_db,
                stop_threshold_db=stop_db,
            )
        )

    def action_cancel(self) -> None:
        focused = self.focused
        if focused is not None:
            if focused.id == "stop-threshold-db":
                self.query_one("#start-threshold-db", Input).focus()
                return
            if focused.id == "start-threshold-db":
                self.query_one("#export-mode-list", OptionList).focus()
                return
        self.dismiss(None)
