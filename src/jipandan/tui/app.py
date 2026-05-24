from pathlib import Path

from textual.app import App

from jipandan.core.models import Session
from jipandan.tui.screens.review import ReviewScreen
from jipandan.tui.screens.transcribe import TranscribeScreen


class JipandanApp(App):
    TITLE = "jipandan"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        audio: Path,
        srt_path: Path | None = None,
        clip_dir: Path | None = None,
        resume: bool = False,
        model: str = "large-v3",
        language: str | None = None,
        temperature: float = 0.0,
        max_context: int = 0,
        entropy_thold: float = 3.0,
    ) -> None:
        super().__init__()
        self.audio = audio.resolve()
        self.srt_path = (srt_path or self.audio.with_suffix(".srt")).resolve()
        self.clip_dir = (clip_dir or Path("clip")).resolve()
        self.resume = resume
        self.model = model
        self.language = language
        self.temperature = temperature
        self.max_context = max_context
        self.entropy_thold = entropy_thold

    def on_mount(self) -> None:
        session_path = self.audio.with_suffix(".jipandan.json")

        if not self.srt_path.exists():
            self.push_screen(
                TranscribeScreen(
                    audio=self.audio,
                    srt_path=self.srt_path,
                    clip_dir=self.clip_dir,
                    model=self.model,
                    language=self.language,
                    temperature=self.temperature,
                    max_context=self.max_context,
                    entropy_thold=self.entropy_thold,
                )
            )
            return

        if self.resume and session_path.exists():
            session = Session.load(session_path)
            session.audio = self.audio
            session.srt = self.srt_path
            session.clip_dir = self.clip_dir
            warnings = session.merge_with_srt()
            for warning in warnings:
                self.notify(warning, severity="warning")
            session.save()
            self.push_screen(ReviewScreen(session))
            return

        if session_path.exists():
            session = Session.load(session_path)
            session.audio = self.audio
            session.srt = self.srt_path
            session.clip_dir = self.clip_dir
            session.merge_with_srt()
            session.save()
            self.push_screen(ReviewScreen(session))
            return

        session = Session.from_srt(self.audio, self.srt_path, self.clip_dir)
        session.save()
        self.push_screen(ReviewScreen(session))
