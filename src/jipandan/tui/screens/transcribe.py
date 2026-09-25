from __future__ import annotations

import io
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Footer, Header, Input, Label, LoadingIndicator, Static

from jipandan.core.models import Session
from jipandan.core.whisper import describe_transcribe_call, transcribe_to_text
from jipandan.tui.screens.review import ReviewScreen


class _OutputSink(io.TextIOBase):
    def __init__(self, on_text: callable[[str], None]) -> None:
        super().__init__()
        self._on_text = on_text

    def write(self, s: str) -> int:  # type: ignore[override]
        if s:
            self._on_text(s)
        return len(s)

    def flush(self) -> None:  # noqa: D401 - interface compatibility
        return


_ARG_INPUT_IDS = ("model", "language", "temperature", "max_context", "entropy_thold")


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


class TranscribeWizardScreen(Screen):
    BINDINGS = [
        ("q", "app.quit", "Quit"),
        Binding("escape", "focus_previous_arg", "Previous", show=False),
        Binding("enter", "open_review", "Open review", show=False),
    ]

    DEFAULT_CSS = """
    TranscribeWizardScreen {
        layout: vertical;
    }

    #wizard-body {
        height: 1fr;
        padding: 1 2;
    }

    #args-panel {
        border: round $primary;
        padding: 1 2;
        height: auto;
    }

    #log-panel {
        border: round $primary;
        padding: 1 2;
        height: 1fr;
    }

    #transcribe-log {
        height: 1fr;
    }

    #buttons-row {
        height: auto;
        padding-top: 1;
    }

    #elapsed {
        color: $text-muted;
    }

    .arg-row {
        height: auto;
        width: 100%;
    }

    .arg-row > .arg-label {
        width: 16;
        color: $text;
    }

    .arg-row > Input {
        width: 1fr;
        min-width: 1;
    }
    """

    def __init__(
        self,
        audio: Path,
        srt_path: Path,
        clip_dir: Path,
        model: str = "large-v3",
        language: str | None = None,
        temperature: float = 0.0,
        max_context: int = 0,
        entropy_thold: float = 2.4,
    ) -> None:
        super().__init__()
        self.audio = audio
        self.srt_path = srt_path
        self.clip_dir = clip_dir
        self.model = model
        self.language = language
        self.temperature = temperature
        self.max_context = max_context
        self.entropy_thold = entropy_thold
        self._start_time: float | None = None
        self._elapsed_timer: Timer | None = None
        self._session: Session | None = None
        self._log_buffer: list[str] = []
        self._transcribe_started = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wizard-body"):
            yield Label(
                f"No SRT found for {self.audio.name}. Configure transcription first.",
                id="wizard-title",
            )
            yield Static("Elapsed: 0:00", id="elapsed", markup=False)
            with Vertical(id="args-panel"):
                yield Label("Whisper arguments", id="args-title")
                yield Static("", id="args-preview", markup=False)
                with Horizontal(id="row-model", classes="arg-row"):
                    yield Label("Model:", classes="arg-label")
                    yield Input(self.model, id="model")
                with Horizontal(id="row-language", classes="arg-row"):
                    yield Label("Language:", classes="arg-label")
                    yield Input(self.language or "", id="language", placeholder="auto")
                with Horizontal(id="row-temperature", classes="arg-row"):
                    yield Label("Temperature:", classes="arg-label")
                    yield Input(str(self.temperature), id="temperature")
                with Horizontal(id="row-max_context", classes="arg-row"):
                    yield Label("Max context:", classes="arg-label")
                    yield Input(str(self.max_context), id="max_context")
                with Horizontal(id="row-entropy_thold", classes="arg-row"):
                    yield Label("Comp. ratio:", classes="arg-label")
                    yield Input(str(self.entropy_thold), id="entropy_thold")
            with Vertical(id="log-panel"):
                yield Label("Verbose output", id="log-title")
                with VerticalScroll(id="transcribe-log"):
                    yield Static("", id="transcribe-output", markup=False)
            with Horizontal(id="buttons-row"):
                yield Button("Confirm & start", id="confirm", variant="primary")
                yield Button(
                    "Open review",
                    id="open-review",
                    variant="success",
                    disabled=True,
                )
                yield LoadingIndicator(id="spinner")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#spinner", LoadingIndicator).display = False
        self.query_one("#log-panel").display = False
        self.query_one("#elapsed").display = False
        self._refresh_args_preview()

    def _refresh_args_preview(self) -> None:
        try:
            model = self.query_one("#model", Input).value.strip() or "large-v3"
            language_raw = self.query_one("#language", Input).value.strip()
            language = language_raw or None
            temperature = float(self.query_one("#temperature", Input).value.strip() or "0.0")
            max_context = int(float(self.query_one("#max_context", Input).value.strip() or "0"))
            entropy_thold = float(self.query_one("#entropy_thold", Input).value.strip() or "2.4")
        except Exception as exc:
            self.query_one("#args-preview", Static).update(f"Invalid arguments: {exc}")
            return
        repo, kwargs = describe_transcribe_call(
            model_name=model,
            language=language,
            temperature=temperature,
            max_context=max_context,
            entropy_thold=entropy_thold,
        )
        lines = [
            f"input_audio={self.audio}",
            f"output_srt={self.srt_path}",
            f"path_or_hf_repo={repo}",
            "mlx_whisper.transcribe kwargs:",
        ]
        for key in sorted(kwargs):
            lines.append(f"  - {key}={kwargs[key]!r}")
        self.query_one("#args-preview", Static).update("\n".join(lines))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in _ARG_INPUT_IDS:
            self._refresh_args_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id not in _ARG_INPUT_IDS:
            return
        idx = _ARG_INPUT_IDS.index(event.input.id)
        if idx + 1 < len(_ARG_INPUT_IDS):
            self.query_one(f"#{_ARG_INPUT_IDS[idx + 1]}", Input).focus()
        else:
            self.query_one("#confirm", Button).focus()

    def action_focus_previous_arg(self) -> None:
        if self._transcribe_started:
            return
        focused = self.focused
        if not isinstance(focused, Input) or focused.id not in _ARG_INPUT_IDS:
            return
        idx = _ARG_INPUT_IDS.index(focused.id)
        if idx == 0:
            return
        self.query_one(f"#{_ARG_INPUT_IDS[idx - 1]}", Input).focus()

    def action_open_review(self) -> None:
        if self._session is None:
            return
        self.app.push_screen(ReviewScreen(self._session))

    def on_click(self, event: events.Click) -> None:
        # Make the whole input row (label + empty space) focus the input.
        # We avoid tight coupling to Click's concrete type across Textual versions.
        widget = getattr(event, "widget", None)
        if widget is None:
            return

        current = widget
        while current is not None:
            if "arg-row" in getattr(current, "classes", set()):
                input_widget = current.query_one(Input)
                input_widget.focus()
                return
            current = getattr(current, "parent", None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            if self._transcribe_started:
                return
            self._transcribe_started = True
            self._begin_transcribe()
            return
        if event.button.id == "open-review":
            self.action_open_review()
            return

    def _append_output(self, text: str) -> None:
        # Keep a bounded buffer so the UI stays responsive.
        self._log_buffer.append(text)
        if len(self._log_buffer) > 4000:
            self._log_buffer = self._log_buffer[-2000:]
        joined = "".join(self._log_buffer)
        self.query_one("#transcribe-output", Static).update(joined)
        self.call_after_refresh(self._scroll_log_to_end)

    def _scroll_log_to_end(self) -> None:
        self.query_one("#transcribe-log", VerticalScroll).scroll_end(
            animate=False,
            immediate=True,
        )

    def _begin_transcribe(self) -> None:
        self.query_one("#args-panel").display = False
        self.query_one("#log-panel").display = True
        self.query_one("#elapsed").display = True
        self.query_one("#spinner", LoadingIndicator).display = True
        self.query_one("#confirm", Button).disabled = True
        self._start_time = time.monotonic()
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
        self._elapsed_timer = self.set_interval(0.2, self._update_elapsed)
        self._append_output("Starting transcription…\n")
        self.call_later(self.run_transcribe)

    def _update_elapsed(self) -> None:
        if self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        self.query_one("#elapsed", Static).update(f"Elapsed: {_format_elapsed(elapsed)}")

    @work(thread=True, exclusive=True)
    def run_transcribe(self) -> None:
        try:
            # Re-parse arguments at run time (the preview already validates).
            model = self.query_one("#model", Input).value.strip() or "large-v3"
            language_raw = self.query_one("#language", Input).value.strip()
            language = language_raw or None
            temperature = float(self.query_one("#temperature", Input).value.strip() or "0.0")
            max_context = int(float(self.query_one("#max_context", Input).value.strip() or "0"))
            entropy_thold = float(self.query_one("#entropy_thold", Input).value.strip() or "2.4")

            repo, kwargs = describe_transcribe_call(
                model_name=model,
                language=language,
                temperature=temperature,
                max_context=max_context,
                entropy_thold=entropy_thold,
            )
            self.app.call_from_thread(
                self._append_output,
                "Resolved whisper call:\n"
                f"- path_or_hf_repo={repo}\n"
                + "".join(f"- {k}={kwargs[k]!r}\n" for k in sorted(kwargs))
                + "\n",
            )

            sink = _OutputSink(lambda s: self.app.call_from_thread(self._append_output, s))
            with redirect_stdout(sink), redirect_stderr(sink):
                transcribe_to_text(
                    input_audio=self.audio,
                    output_text=self.srt_path,
                    model_name=model,
                    language=language,
                    temperature=temperature,
                    max_context=max_context,
                    entropy_thold=entropy_thold,
                    output_format="srt",
                )
            session = Session.from_srt(self.audio, self.srt_path, self.clip_dir)
            session.save()
            self.app.call_from_thread(self._on_complete, session)
        except Exception as exc:
            self.app.call_from_thread(self._on_error, str(exc))

    def _on_complete(self, session: Session) -> None:
        self._session = session
        self.query_one("#spinner", LoadingIndicator).display = False
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        open_review = self.query_one("#open-review", Button)
        open_review.disabled = False
        open_review.focus()
        self._append_output("\nTranscription complete.\n")

    def _on_error(self, message: str) -> None:
        self.query_one("#spinner", LoadingIndicator).display = False
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        self._append_output(f"\nTranscription failed:\n{message}\n")


# Backwards-compatible alias (older code may still import TranscribeScreen).
TranscribeScreen = TranscribeWizardScreen
