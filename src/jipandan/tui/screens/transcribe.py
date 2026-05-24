from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, LoadingIndicator, Static

from jipandan.core.models import Session
from jipandan.core.whisper import transcribe_to_text
from jipandan.tui.screens.review import ReviewScreen


class TranscribeScreen(Screen):
    BINDINGS = [("q", "app.quit", "Quit")]

    DEFAULT_CSS = """
    TranscribeScreen {
        align: center middle;
    }

    #transcribe-status {
        width: 100%;
        content-align: center middle;
        text-align: center;
        padding: 1 2;
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
        entropy_thold: float = 3.0,
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical():
                yield LoadingIndicator()
                yield Static(
                    f"Transcribing {self.audio.name} with {self.model}…",
                    id="transcribe-status",
                )
        yield Footer()

    def on_mount(self) -> None:
        # Defer until the screen is active so @work scheduling is reliable.
        self.call_later(self.run_transcribe)

    @work(thread=True, exclusive=True)
    def run_transcribe(self) -> None:
        try:
            transcribe_to_text(
                input_audio=self.audio,
                output_text=self.srt_path,
                model_name=self.model,
                language=self.language,
                temperature=self.temperature,
                max_context=self.max_context,
                entropy_thold=self.entropy_thold,
                output_format="srt",
            )
            session = Session.from_srt(self.audio, self.srt_path, self.clip_dir)
            session.save()
            self.app.call_from_thread(self._on_complete, session)
        except Exception as exc:
            self.app.call_from_thread(self._on_error, str(exc))

    def _on_complete(self, session: Session) -> None:
        self.app.switch_screen(ReviewScreen(session))

    def _on_error(self, message: str) -> None:
        self.query_one("#transcribe-status", Static).update(
            f"Transcription failed:\n{message}\n\nPress q to quit."
        )
