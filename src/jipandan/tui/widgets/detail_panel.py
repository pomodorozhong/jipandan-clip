import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Static, TabbedContent, TabPane

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.srt import seconds_to_ffmpeg_timestamp
from jipandan.tui.waveform_service import (
    FINE_CLIP_SECONDS,
    FINE_EXTRACT_DURATION,
    FINE_EXTRACT_SECONDS,
    BasicWaveformState,
    FineWaveformState,
    WaveformService,
)
from jipandan.tui.widgets.waveform import (
    GENERATING_WAVEFORM_PLACEHOLDER,
    WaveformWidget,
    format_playback_remaining,
)

DETAIL_TAB_BASIC = "basic"
DETAIL_TAB_FINE_START = "fine-start"
DETAIL_TAB_FINE_END = "fine-end"
NudgeEdge = Literal["start", "end"]


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
        on_detail_updated: Callable[[], None] | None = None,
        on_nudge: Callable[[NudgeEdge, float], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
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

    def is_fine_start_tab(self) -> bool:
        return self._detail_tab == DETAIL_TAB_FINE_START

    def is_fine_end_tab(self) -> bool:
        return self._detail_tab == DETAIL_TAB_FINE_END

    def is_fine_tab(self) -> bool:
        return self._detail_tab in (DETAIL_TAB_FINE_START, DETAIL_TAB_FINE_END)

    def is_waveform_image_updating(self) -> bool:
        return self._active_waveform_widget().is_image_update_in_progress()

    def _active_waveform_widget(self) -> WaveformWidget:
        if self.is_fine_start_tab():
            return self._fine_start_waveform_widget()
        if self.is_fine_end_tab():
            return self._fine_end_waveform_widget()
        return self.query_one("#waveform", WaveformWidget)

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
        elif pane_id == DETAIL_TAB_FINE_START and self._active_candidate is not None:
            self.call_after_refresh(
                self._begin_fine_start_waveform, self._active_candidate
            )
        elif pane_id == DETAIL_TAB_FINE_END and self._active_candidate is not None:
            self.call_after_refresh(
                self._begin_fine_end_waveform, self._active_candidate
            )

    def switch_to_basic_tab(self) -> None:
        if self._detail_tab == DETAIL_TAB_BASIC:
            return
        self.waveform_service.cancel_fine_debounce()
        self._detail_tab = DETAIL_TAB_BASIC
        self._sync_detail_tabs()

    def open_fine_start_tab(self, candidate: ClipCandidate) -> None:
        if self._detail_tab == DETAIL_TAB_FINE_START:
            return
        self.stop_playback()
        self.waveform_service.cancel_fine_debounce()
        self._active_candidate = candidate
        self._update_fine_start_tab_labels(candidate)
        self._detail_tab = DETAIL_TAB_FINE_START
        self._sync_detail_tabs()

    def open_fine_end_tab(self, candidate: ClipCandidate) -> None:
        if self._detail_tab == DETAIL_TAB_FINE_END:
            return
        self.stop_playback()
        self.waveform_service.cancel_fine_debounce()
        self._active_candidate = candidate
        self._detail_tab = DETAIL_TAB_FINE_END
        self._sync_detail_tabs()

    def _begin_fine_start_waveform(self, candidate: ClipCandidate) -> None:
        if self.is_fine_start_tab():
            self._show_fine_start_waveform(candidate)

    def _begin_fine_end_waveform(self, candidate: ClipCandidate) -> None:
        if self.is_fine_end_tab():
            self._show_fine_end_waveform(candidate)

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
        if self.is_fine_start_tab():
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

    def update_after_nudge(self, candidate: ClipCandidate) -> None:
        """Refresh trim labels and markers; regen waveform when trim leaves the view."""
        self._active_candidate = candidate
        self._update_nudge_times_labels(candidate)
        waveform = self.waveform_service
        if self.is_fine_start_tab():
            self.stop_playback()
            self._refresh_fine_start_waveform_markers(candidate)
            waveform.schedule_fine_start_feedback(
                candidate.clip_id, self._on_fine_start_debounce_fire
            )
        elif self.is_fine_end_tab():
            self.stop_playback()
            self._refresh_fine_end_waveform_markers(candidate)
            waveform.schedule_fine_end_feedback(
                candidate.clip_id, self._on_fine_end_debounce_fire
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
        if debounce_waveform:
            if self.is_fine_start_tab():
                waveform.schedule_fine_start_feedback(
                    candidate.clip_id, self._on_fine_start_debounce_fire
                )
                self._refresh_fine_start_waveform_markers(candidate)
            elif self.is_fine_end_tab():
                waveform.schedule_fine_end_feedback(
                    candidate.clip_id, self._on_fine_end_debounce_fire
                )
                self._refresh_fine_end_waveform_markers(candidate)
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
            if self.is_fine_start_tab():
                self._show_fine_start_waveform(candidate)
            elif self.is_fine_end_tab():
                self._show_fine_end_waveform(candidate)
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

    def _on_fine_start_debounce_fire(self, clip_id: str) -> None:
        if not self.is_fine_start_tab():
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._refresh_fine_start_waveform_markers(candidate)
        if self.waveform_service.needs_fine_start_regen(candidate):
            self._refresh_fine_start_feedback(
                candidate, keep_previous=True, play=False
            )
        self.run_play_fine_start_preview(candidate)

    def _on_fine_end_debounce_fire(self, clip_id: str) -> None:
        if not self.is_fine_end_tab():
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._refresh_fine_end_waveform_markers(candidate)
        if self.waveform_service.needs_fine_end_regen(candidate):
            self._refresh_fine_end_feedback(
                candidate, keep_previous=True, play=False
            )
        self.run_play_fine_end_preview(candidate)

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
        try:
            start_png, start_duration = waveform.generate_fine_start(candidate)
            end_png, end_duration = waveform.generate_fine_end(candidate)
        except Exception:
            return
        if not waveform.is_fine_pregen_current(generation):
            return
        start_state = FineWaveformState(
            path=start_png,
            extract_start=waveform.fine_start_extract_start(candidate),
            media_duration=start_duration,
        )
        end_state = FineWaveformState(
            path=end_png,
            extract_start=waveform.fine_end_extract_start(candidate),
            media_duration=end_duration,
        )
        self.app.call_from_thread(
            waveform.store_fine_pregen,
            clip_id,
            generation=generation,
            start_state=start_state,
            end_state=end_state,
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
        if self.is_fine_start_tab():
            self.run_play_fine_start_preview(candidate)
        elif self.is_fine_end_tab():
            self.run_play_fine_end_preview(candidate)
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

    def _refresh_fine_start_feedback(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play: bool = True,
    ) -> None:
        waveform = self.waveform_service
        cached = waveform.fine_start_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_start_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            if play:
                self.run_play_fine_start_preview(candidate)
            return
        self._start_fine_start_waveform_generation(
            candidate, keep_previous=keep_previous, play_after=play
        )

    def _refresh_fine_end_feedback(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play: bool = True,
    ) -> None:
        waveform = self.waveform_service
        cached = waveform.fine_end_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_end_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            if play:
                self.run_play_fine_end_preview(candidate)
            return
        self._start_fine_end_waveform_generation(
            candidate, keep_previous=keep_previous, play_after=play
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

    def _fine_start_waveform_widget(self) -> WaveformWidget:
        return self.query_one("#waveform-fine", WaveformWidget)

    def _fine_end_waveform_widget(self) -> WaveformWidget:
        return self.query_one("#waveform-fine-end", WaveformWidget)

    def _set_fine_start_waveform_placeholder(self, message: str) -> None:
        self._fine_start_waveform_widget().show_placeholder(message)

    def _set_fine_end_waveform_placeholder(self, message: str) -> None:
        self._fine_end_waveform_widget().show_placeholder(message)

    def _present_fine_slice_waveform(
        self,
        widget: WaveformWidget,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        refresh_markers: Callable[[ClipCandidate], None],
    ) -> None:
        widget.display_waveform(
            path,
            "00:00:00.000",
            FINE_EXTRACT_DURATION,
            media_duration=media_duration,
        )
        widget._flush_pending_display()
        refresh_markers(candidate)
        widget.refresh()

    def _present_fine_start_waveform(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> None:
        self.waveform_service.record_fine_start_display(
            candidate,
            path,
            media_duration=media_duration,
            extract_start=extract_start,
        )
        self._present_fine_slice_waveform(
            self._fine_start_waveform_widget(),
            candidate,
            path,
            media_duration=media_duration,
            refresh_markers=self._refresh_fine_start_waveform_markers,
        )

    def _present_fine_end_waveform(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> None:
        self.waveform_service.record_fine_end_display(
            candidate,
            path,
            media_duration=media_duration,
            extract_start=extract_start,
        )
        self._present_fine_slice_waveform(
            self._fine_end_waveform_widget(),
            candidate,
            path,
            media_duration=media_duration,
            refresh_markers=self._refresh_fine_end_waveform_markers,
        )

    def _overlay_fine_slice_markers(
        self,
        widget: WaveformWidget,
        extract_start: float | None,
        candidate: ClipCandidate,
    ) -> None:
        if extract_start is None:
            return
        rel_start, rel_end = self.waveform_service.fine_marker_times(
            extract_start, candidate
        )
        window = FINE_EXTRACT_SECONDS
        marker_start = max(0.0, min(rel_start, window))
        marker_end = max(marker_start, min(rel_end, window))
        widget.overlay_trim_bounds(
            seconds_to_ffmpeg_timestamp(marker_start),
            seconds_to_ffmpeg_timestamp(marker_end),
        )

    def _refresh_waveform_markers(self, candidate: ClipCandidate) -> None:
        if not self.waveform_service.has_displayed_basic_viewport():
            return
        self.query_one("#waveform", WaveformWidget).overlay_trim_bounds(
            candidate.start,
            candidate.end,
        )

    def _refresh_fine_start_waveform_markers(self, candidate: ClipCandidate) -> None:
        self._overlay_fine_slice_markers(
            self._fine_start_waveform_widget(),
            self.waveform_service.displayed_fine_start_extract(),
            candidate,
        )

    def _refresh_fine_end_waveform_markers(self, candidate: ClipCandidate) -> None:
        self._overlay_fine_slice_markers(
            self._fine_end_waveform_widget(),
            self.waveform_service.displayed_fine_end_extract(),
            candidate,
        )

    def _show_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        if state := waveform.try_reuse_basic(candidate):
            self._present_from_basic_state(candidate, state)
            return
        cached = waveform.basic_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            return
        self._generate_waveform(candidate, keep_previous=keep_previous)

    def _show_fine_start_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        if state := waveform.try_reuse_fine_start(candidate):
            self._present_fine_start_waveform(
                candidate,
                state.path,
                media_duration=state.media_duration,
                extract_start=state.extract_start,
            )
            return
        cached = waveform.fine_start_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_start_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            return
        self._start_fine_start_waveform_generation(
            candidate, keep_previous=keep_previous
        )

    def _show_fine_end_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        waveform = self.waveform_service
        if state := waveform.try_reuse_fine_end(candidate):
            self._present_fine_end_waveform(
                candidate,
                state.path,
                media_duration=state.media_duration,
                extract_start=state.extract_start,
            )
            return
        cached = waveform.fine_end_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_end_waveform(
                candidate,
                cached,
                media_duration=waveform.media_duration(cached),
            )
            return
        self._start_fine_end_waveform_generation(
            candidate, keep_previous=keep_previous
        )

    def _start_fine_slice_waveform_generation(
        self,
        *,
        candidate: ClipCandidate,
        begin_generation: Callable[[], int],
        is_current: Callable[[int], bool],
        set_placeholder: Callable[[str], None],
        present: Callable[[ClipCandidate, Path, float | None], None],
        generate_file: Callable[[ClipCandidate], tuple[Path, float]],
        play_after: bool = False,
        play_preview: Callable[[ClipCandidate], None] | None = None,
        keep_previous: bool = False,
    ) -> None:
        generation = begin_generation()
        if not keep_previous:
            set_placeholder(GENERATING_WAVEFORM_PLACEHOLDER)

        app = self.app

        def run() -> None:
            try:
                target_png, media_duration = generate_file(candidate)
            except Exception as exc:
                if is_current(generation):
                    app.call_from_thread(set_placeholder, f"Waveform failed: {exc}")
                return
            if not is_current(generation):
                return

            def on_ready() -> None:
                present(candidate, target_png, media_duration)
                if play_after and play_preview is not None:
                    play_preview(candidate)

            app.call_from_thread(on_ready)

        threading.Thread(target=run, daemon=True).start()

    def _start_fine_start_waveform_generation(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play_after: bool = False,
    ) -> None:
        waveform = self.waveform_service
        self._start_fine_slice_waveform_generation(
            candidate=candidate,
            begin_generation=waveform.begin_fine_start_generation,
            is_current=waveform.is_fine_start_generation_current,
            set_placeholder=self._set_fine_start_waveform_placeholder,
            present=lambda c, path, dur: self._present_fine_start_waveform(
                c, path, media_duration=dur
            ),
            generate_file=waveform.generate_fine_start,
            play_after=play_after,
            play_preview=self.run_play_fine_start_preview,
            keep_previous=keep_previous,
        )

    def _start_fine_end_waveform_generation(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play_after: bool = False,
    ) -> None:
        waveform = self.waveform_service
        self._start_fine_slice_waveform_generation(
            candidate=candidate,
            begin_generation=waveform.begin_fine_end_generation,
            is_current=waveform.is_fine_end_generation_current,
            set_placeholder=self._set_fine_end_waveform_placeholder,
            present=lambda c, path, dur: self._present_fine_end_waveform(
                c, path, media_duration=dur
            ),
            generate_file=waveform.generate_fine_end,
            play_after=play_after,
            play_preview=self.run_play_fine_end_preview,
            keep_previous=keep_previous,
        )

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_preview(self, candidate: ClipCandidate) -> None:
        duration = float(candidate.duration)
        self.app.call_from_thread(self._start_playback_status, duration)
        process: subprocess.Popen | None = None
        try:
            process = ffmpeg.spawn_play_preview(
                self.session.audio, candidate.start, candidate.duration
            )
            self._playback_process = process
            process.wait()
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"mpv failed: {exc}", severity="error"
            )
        finally:
            if self._playback_process is process:
                self._playback_process = None
            self.app.call_from_thread(self._clear_playback_status)

    def _fine_start_playback_range(self, candidate: ClipCandidate) -> tuple[str, float]:
        duration = min(FINE_CLIP_SECONDS, float(candidate.duration))
        return candidate.start, duration

    def _fine_end_playback_range(self, candidate: ClipCandidate) -> tuple[str, float]:
        waveform = self.waveform_service
        clip_start = waveform.clip_start_seconds(candidate)
        clip_end = waveform.clip_end_seconds(candidate)
        duration = min(FINE_CLIP_SECONDS, clip_end - clip_start)
        start = max(clip_start, clip_end - duration)
        return seconds_to_ffmpeg_timestamp(start), duration

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_fine_start_preview(self, candidate: ClipCandidate) -> None:
        start, duration = self._fine_start_playback_range(candidate)
        self._run_play_fine_slice_preview(candidate, start, duration)

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_fine_end_preview(self, candidate: ClipCandidate) -> None:
        start, duration = self._fine_end_playback_range(candidate)
        self._run_play_fine_slice_preview(candidate, start, duration)

    def run_play_fine_preview(self, candidate: ClipCandidate) -> None:
        self.run_play_fine_start_preview(candidate)

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
            process = ffmpeg.spawn_play_preview(
                self.session.audio,
                start,
                duration_str,
            )
            self._playback_process = process
            process.wait()
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"mpv failed: {exc}", severity="error"
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
            target_png, media_duration = waveform.generate_basic(candidate)
            if not waveform.is_basic_generation_current(generation):
                return
            self.app.call_from_thread(
                self._present_waveform,
                candidate,
                target_png,
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
