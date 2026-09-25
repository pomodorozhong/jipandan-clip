from pathlib import Path
import hashlib

from textual.app import App

from jipandan.core.models import Session
from jipandan.tui.screens.review import ReviewScreen
from jipandan.tui.screens.transcribe import TranscribeWizardScreen


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

        if not self.srt_path.exists() and not session_path.exists():
            self.push_screen(
                TranscribeWizardScreen(
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

        if session_path.exists():
            session = Session.load(session_path)
            session.audio = self.audio
            session.srt = self.srt_path
            session.clip_dir = self.clip_dir
            changes = session.srt_merge_preview() if self.srt_path.exists() else None
            uncertain_text_change = (
                self.srt_path.exists()
                and session.srt_fingerprint is None
                and self.srt_path.stat().st_mtime_ns > session_path.stat().st_mtime_ns
            )
            changed_file = (
                self.srt_path.exists()
                and session.srt_fingerprint is not None
                and session.srt_fingerprint
                != hashlib.sha256(self.srt_path.read_bytes()).hexdigest()
            )
            if (changes and any(changes.values())) or uncertain_text_change or changed_file:
                summary = ", ".join(
                    f"{len(ids)} {kind}" for kind, ids in (changes or {}).items() if ids
                )
                if not summary:
                    summary = "file content changed"
                self.notify(
                    "SRT differs from saved session: " + summary
                    + ("; text may have changed" if uncertain_text_change else "")
                    + ". Saved clips were kept; use the web merge review to reconcile.",
                    severity="warning",
                    timeout=12,
                )
            elif not self.srt_path.exists():
                self.notify("SRT is missing; saved clips were kept.", severity="warning")
            self.push_screen(ReviewScreen(session))
            return

        session = Session.from_srt(self.audio, self.srt_path, self.clip_dir)
        session.save()
        self.push_screen(ReviewScreen(session))
