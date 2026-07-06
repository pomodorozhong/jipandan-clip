import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Static, TabbedContent, TabPane

from jipandan.core.audio_playback import AudioPlayback, default_audio_playback
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.srt import seconds_to_ffmpeg_timestamp
from jipandan.tui.fine_waveform import (
    FINE_END_TAB_ID,
    FINE_EXTRACT_DURATION,
    FINE_EXTRACT_SECONDS,
    FINE_NUDGE_MODES,
    FINE_START_TAB_ID,
    TAB_TO_FINE_MODE,
    FineNudgeMode,
    FineWaveformState,
)
from jipandan.tui.waveform_service import (
    BasicWaveformState,
    WaveformService,
)
from jipandan.tui.widgets.waveform import (
    GENERATING_WAVEFORM_PLACEHOLDER,
    WaveformWidget,
    format_playback_remaining,
)
from jipandan.tui.widgets.waveform_nudge_bar import NudgeEdge

DETAIL_TAB_BASIC = "basic"
DETAIL_TAB_FINE_START = FINE_START_TAB_ID
DETAIL_TAB_FINE_END = FINE_END_TAB_ID


class DetailTabs(TabbedContent, can_focus=False):
    """Detail panel tabs; non-focusable so j/k navigation stays on the list."""


class ClipDetailPanel(Vertical):
    """Right-hand clip detail panel with basic and fine-start-nudge tabs."""

    DEFAULT_CSS = """
    ClipDetailPanel {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
    }

    #playback-status {
        height: 1;
        width: 100%;
    }

    #clip-title {
        height: auto;
        padding-bottom: 1;
    }

    #detail-tabs {
        height: 1fr;
    }

    #clip-times, #clip-status, #clip-times-fine {
        height: auto;
        padding-top: 1;
    }

    #fine-start-hints, #fine-end-hints {
        height: 1;
        width: 100%;
        color: $text-muted;
        padding-bottom: 1;
    }

    #waveform, #waveform-fine, #waveform-fine-end {
        height: 1fr;
        min-height: 6;
    }
    """

    def __init__(
        self,
        session: Session,
        waveform_cache_dir: Path,
        *,
        audio_playback: AudioPlayback | None = None,
        on_detail_updated: Callable[[], None] | None = None,
        on_nudge: Callable[[NudgeEdge, float], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._audio_playback = (
            audio_playback
            if audio_playback is not None
            else default_audio_playback
        )
        self._waveform_cache_dir = waveform_cache_dir
        self._waveform: WaveformService | None = None
        self._on_detail_updated = on_detail_updated
        self._on_nudge = on_nudge
        self._detail_tab = DETAIL_TAB_BASIC
        self._playback_end: float | None = None
        self._playback_timer: Timer | None = None
        self._playback_process: subprocess.Popen | None = None
        self._active_candidate: ClipCandidate | None = None

    @property
    def waveform_service(self) -> WaveformService:
        if self._waveform is None:
            raise RuntimeError("WaveformService is not initialized until mount")
        return self._waveform

    def compose(self) -> ComposeResult:
        with DetailTabs(initial=DETAIL_TAB_BASIC, id="detail-tabs"):
            with TabPane("Basic", id=DETAIL_TAB_BASIC):
                yield WaveformWidget(id="waveform")
            with TabPane("Fine Start", id=DETAIL_TAB_FINE_START):
                yield WaveformWidget(id="waveform-fine")
                yield Static(
                    "[ ] ±10ms  { } ±100ms  Esc → Basic",
                    id="fine-start-hints",
                    markup=False,
                )
                yield Static("", id="clip-times-fine", markup=False)
            with TabPane("Fine End", id=DETAIL_TAB_FINE_END):
                yield WaveformWidget(id="waveform-fine-end")
                yield Static(
                    "[ ] ±10ms  { } ±100ms  Esc → Basic",
                    id="fine-end-hints",
                    markup=False,
                )
        yield Static("", id="clip-title", markup=False)
        yield Static("", id="clip-times", markup=False)
        yield Static("", id="clip-status", markup=False)
        yield Static("", id="playback-status", markup=False)

    def _schedule_timer(
        self, delay: float, callback: Callable[[], None], name: str
    ) -> Callable[[], None]:
        timer = self.set_timer(delay, callback, name=name)
        return timer.stop

    def on_mount(self) -> None:
        self._waveform = WaveformService(
            self.session,
            self._waveform_cache_dir,
            schedule=self._schedule_timer,
        )
        self._configure_waveform_nudge_handlers()

    def _configure_waveform_nudge_handlers(self) -> None:
        handler = self._on_nudge
        for widget_id in ("waveform", "waveform-fine", "waveform-fine-end"):
            self.query_one(f"#{widget_id}", WaveformWidget).set_nudge_handler(handler)

    @staticmethod
    def clip_status_text(candidate: ClipCandidate) -> str:
        return (
            f"Status: {candidate.status}\n"
            f"Original: {candidate.original_start} → {candidate.original_end}"
        )

    def active_fine_mode(self) -> FineNudgeMode | None:
        return TAB_TO_FINE_MODE.get(self._detail_tab)

    def is_fine_start_tab(self) -> bool:
        return self.active_fine_mode() == "start"

    def is_fine_end_tab(self) -> bool:
        return self.active_fine_mode() == "end"

    def is_fine_tab(self) -> bool:
        return self.active_fine_mode() is not None

    def is_waveform_image_updating(self) -> bool:
        return self._active_waveform_widget().is_image_update_in_progress()

    def _active_waveform_widget(self) -> WaveformWidget:
        mode = self.active_fine_mode()
        if mode is not None:
            return self._fine_waveform_widget(mode)
        return self.query_one("#waveform", WaveformWidget)

    def _fine_waveform_widget(self, mode: FineNudgeMode) -> WaveformWidget:
        widget_id = self.waveform_service.fine(mode).spec.widget_id
        return self.query_one(f"#{widget_id}", WaveformWidget)

    def _sync_detail_tabs(self) -> None:
        tabs = self.query_one("#detail-tabs", DetailTabs)
        if tabs.active != self._detail_tab:
            tabs.active = self._detail_tab

    @on(TabbedContent.TabActivated, "#detail-tabs")
    def on_detail_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id
        if pane_id is None:
            return
        self._detail_tab = pane_id
        if self._waveform is None:
            return
        if pane_id == DETAIL_TAB_BASIC:
            self.waveform_service.cancel_fine_debounce()
        elif pane_id in TAB_TO_FINE_MODE and self._active_candidate is not None:
            mode = TAB_TO_FINE_MODE[pane_id]
            self.call_after_refresh(
                self._begin_fine_waveform, mode, self._active_candidate
            )

    def switch_to_basic_tab(self) -> None:
        if self._detail_tab == DETAIL_TAB_BASIC:
            return
        self.waveform_service.cancel_fine_debounce()
        self._detail_tab = DETAIL_TAB_BASIC
        self._sync_detail_tabs()

    def open_fine_tab(self, mode: FineNudgeMode, candidate: ClipCandidate) -> None:
        spec = self.waveform_service.fine(mode).spec
        if self._detail_tab == spec.tab_id:
            return
        self.stop_playback()
        self.waveform_service.cancel_fine_debounce()
        self._active_candidate = candidate
        if spec.has_detail_labels:
            self._update_fine_start_tab_labels(candidate)
        self._detail_tab = spec.tab_id
        self._sync_detail_tabs()

    def open_fine_start_tab(self, candidate: ClipCandidate) -> None:
        self.open_fine_tab("start", candidate)

    def open_fine_end_tab(self, candidate: ClipCandidate) -> None:
        self.open_fine_tab("end", candidate)

    def _begin_fine_waveform(
        self, mode: FineNudgeMode, candidate: ClipCandidate
    ) -> None:
        if self.active_fine_mode() == mode:
            self._show_fine_waveform(mode, candidate)

    def close_fine_tab(self, candidate: ClipCandidate | None) -> None:
        if not self.is_fine_tab():
            return
        self.switch_to_basic_tab()
        if candidate is not None:
            self._show_waveform(candidate)

    def close_fine_start_tab(self, candidate: ClipCandidate | None) -> None:
        self.close_fine_tab(candidate)

    def update_clip_status(self, text: str) -> None:
        self.query_one("#clip-status", Static).update(text)

    def clear_detail(self) -> None:
        self.waveform_service.clear_cache()
        self.query_one("#clip-title", Static).update("No clips in current filter.")
        self.query_one("#waveform", WaveformWidget).show_placeholder("No waveform.")
        self.query_one("#waveform-fine", WaveformWidget).show_placeholder("No waveform.")
        self.query_one("#waveform-fine-end", WaveformWidget).show_placeholder(
            "No waveform."
        )
        self.query_one("#clip-times", Static).update("")
        self.query_one("#clip-times-fine", Static).update("")
        self.query_one("#clip-status", Static).update("")

    def _update_fine_start_tab_labels(self, candidate: ClipCandidate) -> None:
        start_offset = candidate.start_offset_seconds()
        self.query_one("#clip-times-fine", Static).update(
            f"Start: {candidate.start}  ({start_offset:+.3f}s from original)"
        )

    def _update_nudge_times_labels(self, candidate: ClipCandidate) -> None:
        start_offset = candidate.start_offset_seconds()
        end_offset = candidate.end_offset_seconds()
        times_text = (
            f"Start: {candidate.start}  ({start_offset:+.3f}s from original)\n"
            f"End: {candidate.end}  ({end_offset:+.3f}s from original)  "
            f"Duration: {candidate.duration}s"
        )
        self.query_one("#clip-times", Static).update(times_text)
        if self.active_fine_mode() == "start":
            self._update_fine_start_tab_labels(candidate)

    def _update_clip_detail_labels(self, candidate: ClipCandidate) -> None:
        start_offset = candidate.start_offset_seconds()
        end_offset = candidate.end_offset_seconds()
        self.query_one("#clip-title", Static).update(
            f"#{candidate.clip_id}  {candidate.title}"
        )
        times_text = (
            f"Start: {candidate.start}  ({start_offset:+.3f}s from original)\n"
            f"End: {candidate.end}  ({end_offset:+.3f}s from original)  "
            f"Duration: {candidate.duration}s"
        )
        self.query_one("#clip-times", Static).update(times_text)
        self._update_fine_start_tab_labels(candidate)
        self.query_one("#clip-status", Static).update(
            self.clip_status_text(candidate)
        )

    def _fine_debounce_handler(self, mode: FineNudgeMode) -> Callable[[str], None]:
        def on_fire(clip_id: str) -> None:
            self._on_fine_debounce_fire(mode, clip_id)

        return on_fire

    def update_after_nudge(self, candidate: ClipCandidate) -> None:
        """Refresh trim labels and markers; regen waveform when trim leaves the view."""
        self._active_candidate = candidate
        self._update_nudge_times_labels(candidate)
        waveform = self.waveform_service
        mode = self.active_fine_mode()
        if mode is not None:
            self.stop_playback()
            self._refresh_fine_waveform_markers(mode, candidate)
            self.waveform_service.fine(mode).schedule_feedback(
                candidate.clip_id, self._fine_debounce_handler(mode)
            )
        else:
            self._refresh_waveform_markers(candidate)
            if waveform.needs_basic_regen(candidate):
                waveform.schedule_basic_refresh(
                    candidate.clip_id, on_fire=self._on_basic_debounce_fire
                )
            else:
                waveform.cancel_basic_debounce()
        waveform.schedule_fine_pregen(
            candidate.clip_id, self._on_fine_pregen_fire
        )

    def update_detail(
        self,
        candidate: ClipCandidate,
        *,
        debounce_waveform: bool = False,
        waveform_regen_on_debounce: bool = True,
        force_waveform_regen: bool = False,
    ) -> None:
        self._active_candidate = candidate
        self._update_clip_detail_labels(candidate)
        if self._on_detail_updated is not None:
            self._on_detail_updated()
        waveform = self.waveform_service
        mode = self.active_fine_mode()
        if debounce_waveform:
            if mode is not None:
                self.waveform_service.fine(mode).schedule_feedback(
                    candidate.clip_id, self._fine_debounce_handler(mode)
                )
                self._refresh_fine_waveform_markers(mode, candidate)
            else:
                if waveform_regen_on_debounce:
                    waveform.schedule_basic_refresh(
                        candidate.clip_id,
                        force_regen=force_waveform_regen,
                        on_fire=self._on_basic_debounce_fire,
                    )
                self._refresh_waveform_markers(candidate)
        else:
            waveform.cancel_waveform_debounce()
            if mode is not None:
                self._show_fine_waveform(mode, candidate)
            else:
                self._show_waveform(candidate)
        waveform.schedule_fine_pregen(
            candidate.clip_id, self._on_fine_pregen_fire
        )

    def _on_basic_debounce_fire(self, clip_id: str, force_regen: bool) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._refresh_waveform_markers(candidate)
        if force_regen or self.waveform_service.needs_basic_regen(candidate):
            self.waveform_service.begin_basic_generation()
            self._show_waveform(candidate, keep_previous=True)

    def _on_fine_debounce_fire(self, mode: FineNudgeMode, clip_id: str) -> None:
        if self.active_fine_mode() != mode:
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._refresh_fine_waveform_markers(mode, candidate)
        if self.waveform_service.fine(mode).needs_regen(candidate):
            self._refresh_fine_feedback(
                mode, candidate, keep_previous=True, play=False
            )
        self.run_play_fine_preview(mode, candidate)

    def _on_fine_pregen_fire(self, clip_id: str) -> None:
        if (
            self._active_candidate is None
            or self._active_candidate.clip_id != clip_id
        ):
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None or self.waveform_service.fine_pair_ready(candidate):
            return
        generation = self.waveform_service.begin_fine_pregen()
        self._run_fine_waveform_pregen(clip_id, generation)

    @work(thread=True, exclusive=True, group="fine-pregen")
    def _run_fine_waveform_pregen(self, clip_id: str, generation: int) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        waveform = self.waveform_service
        states: dict[FineNudgeMode, FineWaveformState] = {}
        try:
            for mode in FINE_NUDGE_MODES:
                slice_ = waveform.fine(mode)
                mp3, duration = slice_.generate(candidate)
                states[mode] = FineWaveformState(
                    path=mp3,
                    extract_start=slice_.extract_start(candidate),
                    media_duration=duration,
                )
        except Exception:
            return
        if not waveform.is_fine_pregen_current(generation):
            return
        self.app.call_from_thread(
            waveform.store_fine_pregen,
            clip_id,
            generation=generation,
            states=states,
        )

    def is_playing(self) -> bool:
        process = self._playback_process
        return process is not None and process.poll() is None

    def stop_playback(self) -> None:
        process = self._playback_process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()

    def play_preview(self, candidate: ClipCandidate) -> None:
        mode = self.active_fine_mode()
        if mode is not None:
            self.run_play_fine_preview(mode, candidate)
        else:
            self.run_play_preview(candidate)

    def _clear_playback_status(self) -> None:
        self._playback_end = None
        if self._playback_timer is not None:
            self._playback_timer.stop()
            self._playback_timer = None
        self.query_one("#playback-status", Static).update("")

    def _start_playback_status(self, duration_seconds: float) -> None:
        self._playback_end = time.monotonic() + duration_seconds
        self._update_playback_status()
        if self._playback_timer is not None:
            self._playback_timer.stop()
        self._playback_timer = self.set_interval(0.2, self._update_playback_status)

    def _update_playback_status(self) -> None:
        if self._playback_end is None:
            return
        remaining = self._playback_end - time.monotonic()
        if remaining <= 0:
            self._clear_playback_status()
            return
        self.query_one("#playback-status", Static).update(
            format_playback_remaining(remaining)
        )

    def _refresh_fine_feedback(
        self,
        mode: FineNudgeMode,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play: bool = True,
    ) -> None:
        slice_ = self.waveform_service.fine(mode)
        cached = slice_.cache_path(candidate, suffix=".mp3")
        if cached.exists():
            self._present_fine_waveform(
                mode,
                candidate,
                cached,
                media_duration=self.waveform_service.media_duration(cached),
            )
            if play:
                self.run_play_fine_preview(mode, candidate)
            return
        self._start_fine_waveform_generation(
            mode, candidate, keep_previous=keep_previous, play_after=play
        )

    def _present_waveform(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        viewport_start: str | None = None,
        viewport_duration: str | None = None,
    ) -> None:
        state = self.waveform_service.record_basic_display(
            candidate,
            path,
            media_duration=media_duration,
            viewport_start=viewport_start,
            viewport_duration=viewport_duration,
        )
        self.query_one("#waveform", WaveformWidget).display_waveform(
            path,
            state.viewport_start,
            state.viewport_duration,
            media_duration=state.media_duration,
            source_audio=self.session.audio,
        )
        self._refresh_waveform_markers(candidate)

    def _present_from_basic_state(
        self, candidate: ClipCandidate, state: BasicWaveformState
    ) -> None:
        self._present_waveform(
            candidate,
            state.path,
            media_duration=state.media_duration,
            viewport_start=state.viewport_start,
            viewport_duration=state.viewport_duration,
        )

    def _present_fine_slice_waveform(
        self,
        widget: WaveformWidget,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
        refresh_markers: Callable[[ClipCandidate], None],
    ) -> None:
        viewport_start = (
            seconds_to_ffmpeg_timestamp(extract_start)
            if extract_start is not None
            else "00:00:00.000"
        )
        widget.display_waveform(
            path,
            viewport_start,
            FINE_EXTRACT_DURATION,
            media_duration=media_duration,
            source_audio=self.session.audio,
        )
        widget._flush_pending_display()
        refresh_markers(candidate)
        widget.refresh()

    def _present_fine_waveform(
        self,
        mode: FineNudgeMode,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> None:
        self.waveform_service.fine(mode).record_display(
            candidate,
            path,
            media_duration=media_duration,
            extract_start=extract_start,
        )
        self._present_fine_slice_waveform(
            self._fine_waveform_widget(mode),
            candidate,
            path,
            media_duration=media_duration,
            extract_start=extract_start,
            refresh_markers=lambda c, m=mode: self._refresh_fine_waveform_markers(m, c),
        )

    def _overlay_fine_slice_markers(
        self,
        widget: WaveformWidget,
        extract_start: float | None,
        candidate: ClipCandidate,
    ) -> None:
        del extract_start
        widget.overlay_trim_bounds(candidate.start, candidate.end)

    def _refresh_waveform_markers(self, candidate: ClipCandidate) -> None:
        if not self.waveform_service.has_displayed_basic_viewport():
            return
        self.query_one("#waveform", WaveformWidget).overlay_trim_bounds(
            candidate.start,
            candidate.end,
        )

    def _refresh_fine_waveform_markers(
        self, mode: FineNudgeMode, candidate: ClipCandidate
    ) -> None:
        self._overlay_fine_slice_markers(
            self._fine_waveform_widget(mode),
            self.waveform_service.fine(mode).displayed_extract(),
            candidate,
        )

    def _show_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        if state := waveform.try_reuse_basic(candidate):
            self._present_from_basic_state(candidate, state)
            return
        cached = waveform.basic_cache_path(candidate, suffix=".mp3")
        if cached.exists():
            self._present_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            return
        self._generate_waveform(candidate, keep_previous=keep_previous)

    def _show_fine_waveform(
        self, mode: FineNudgeMode, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        slice_ = waveform.fine(mode)
        if state := slice_.try_reuse(candidate):
            self._present_fine_waveform(
                mode,
                candidate,
                state.path,
                media_duration=state.media_duration,
                extract_start=state.extract_start,
            )
            return
        cached = slice_.cache_path(candidate, suffix=".mp3")
        if cached.exists():
            self._present_fine_waveform(
                mode,
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            return
        self._start_fine_waveform_generation(
            mode, candidate, keep_previous=keep_previous
        )

    def _start_fine_waveform_generation(
        self,
        mode: FineNudgeMode,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play_after: bool = False,
    ) -> None:
        slice_ = self.waveform_service.fine(mode)
        generation = slice_.begin_generation()
        if not keep_previous:
            self._set_fine_waveform_placeholder(
                mode, GENERATING_WAVEFORM_PLACEHOLDER
            )
        self._run_fine_waveform_generation(
            mode, candidate, generation, play_after
        )

    @work(thread=True, exclusive=True, group="detail-fine-waveform")
    def _run_fine_waveform_generation(
        self,
        mode: FineNudgeMode,
        candidate: ClipCandidate,
        generation: int,
        play_after: bool,
    ) -> None:
        slice_ = self.waveform_service.fine(mode)
        try:
            target_mp3, media_duration = slice_.generate(candidate)
        except Exception as exc:
            if slice_.is_generation_current(generation):
                self.app.call_from_thread(
                    self._set_fine_waveform_placeholder,
                    mode,
                    f"Waveform failed: {exc}",
                )
            return
        if not slice_.is_generation_current(generation):
            return

        def on_ready() -> None:
            self._present_fine_waveform(
                mode, candidate, target_mp3, media_duration=media_duration
            )
            if play_after:
                self.run_play_fine_preview(mode, candidate)

        self.app.call_from_thread(on_ready)

    def _set_fine_waveform_placeholder(
        self, mode: FineNudgeMode, message: str
    ) -> None:
        self._fine_waveform_widget(mode).show_placeholder(message)

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_preview(self, candidate: ClipCandidate) -> None:
        duration = float(candidate.duration)
        self.app.call_from_thread(self._start_playback_status, duration)
        process: subprocess.Popen | None = None
        try:
            process = self._audio_playback.spawn_play_preview(
                self.session.audio, candidate.start, candidate.duration
            )
            self._playback_process = process
            process.wait()
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"Playback failed: {exc}", severity="error"
            )
        finally:
            if self._playback_process is process:
                self._playback_process = None
            self.app.call_from_thread(self._clear_playback_status)

    def _fine_playback_range(
        self, mode: FineNudgeMode, candidate: ClipCandidate
    ) -> tuple[str, float]:
        waveform = self.waveform_service
        spec = waveform.fine(mode).spec
        return spec.playback_range(
            candidate,
            waveform.clip_start_seconds(candidate),
            waveform.clip_end_seconds(candidate),
        )

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_fine_preview(
        self, mode: FineNudgeMode, candidate: ClipCandidate
    ) -> None:
        start, duration = self._fine_playback_range(mode, candidate)
        self._run_play_fine_slice_preview(candidate, start, duration)

    def _run_play_fine_slice_preview(
        self,
        candidate: ClipCandidate,
        start: str,
        duration_seconds: float,
    ) -> None:
        duration_str = f"{duration_seconds:.3f}"
        self.app.call_from_thread(self._start_playback_status, duration_seconds)
        process: subprocess.Popen | None = None
        try:
            process = self._audio_playback.spawn_play_preview(
                self.session.audio,
                start,
                duration_str,
            )
            self._playback_process = process
            process.wait()
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"Playback failed: {exc}", severity="error"
            )
        finally:
            if self._playback_process is process:
                self._playback_process = None
            self.app.call_from_thread(self._clear_playback_status)

    @work(thread=True, exclusive=True, group="detail-full-waveform")
    def _generate_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        generation = waveform.begin_basic_generation()
        if not (keep_previous and waveform.has_displayed_basic_viewport()):
            self.app.call_from_thread(
                self._set_full_waveform_placeholder,
                GENERATING_WAVEFORM_PLACEHOLDER,
            )
        try:
            target_mp3, media_duration = waveform.generate_basic(candidate)
            if not waveform.is_basic_generation_current(generation):
                return
            self.app.call_from_thread(
                self._present_waveform,
                candidate,
                target_mp3,
                media_duration=media_duration,
            )
        except Exception as exc:
            if not waveform.is_basic_generation_current(generation):
                return
            self.app.call_from_thread(
                self._set_full_waveform_placeholder,
                f"Waveform failed: {exc}",
            )

    def _set_full_waveform_placeholder(self, message: str) -> None:
        self.query_one("#waveform", WaveformWidget).show_placeholder(message)
