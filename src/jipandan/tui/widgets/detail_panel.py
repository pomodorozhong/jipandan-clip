import hashlib
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Static, TabbedContent, TabPane

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.tui.widgets.waveform import (
    GENERATING_WAVEFORM_PLACEHOLDER,
    WaveformWidget,
    format_playback_remaining,
)

WAVEFORM_DEBOUNCE_SECONDS = 0.4
WAVEFORM_DEBOUNCE_MAX_SECONDS = 1.0
WAVEFORM_REGEN_MARGIN_SECONDS = 0.05
MIN_SCHEDULE_DELAY_SECONDS = 0.001
FINE_REGEN_LINE_FRACTION = 0.6
FINE_VIEW_SECONDS = 0.5
FINE_START_REGEN_RIGHT_THRESHOLD = FINE_VIEW_SECONDS * FINE_REGEN_LINE_FRACTION
FINE_END_REGEN_LEFT_THRESHOLD = FINE_VIEW_SECONDS * (1.0 - FINE_REGEN_LINE_FRACTION)
FINE_VIEW_DURATION = f"{FINE_VIEW_SECONDS:.3f}"
FINE_NUDGE_FINE = 0.01
FINE_NUDGE_COARSE = 0.1
FINE_START_VIEW_SECONDS = FINE_VIEW_SECONDS
FINE_START_VIEW_DURATION = FINE_VIEW_DURATION
FINE_START_NUDGE_FINE = FINE_NUDGE_FINE
FINE_START_NUDGE_COARSE = FINE_NUDGE_COARSE
DETAIL_TAB_BASIC = "basic"
DETAIL_TAB_FINE_START = "fine-start"
DETAIL_TAB_FINE_END = "fine-end"
FINE_START_CACHE_SUFFIX = "_fine"
FINE_END_CACHE_SUFFIX = "_fine-end"


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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._waveform_cache_dir = waveform_cache_dir
        self._on_detail_updated = on_detail_updated
        self._detail_tab = DETAIL_TAB_BASIC
        self._waveform_generation = 0
        self._fine_waveform_generation = 0
        self._fine_end_waveform_generation = 0
        self._playback_end: float | None = None
        self._playback_timer: Timer | None = None
        self._playback_process: subprocess.Popen | None = None
        self._waveform_debounce_timer: Timer | None = None
        self._fine_debounce_timer: Timer | None = None
        self._fine_end_debounce_timer: Timer | None = None
        self._pending_waveform_id: str | None = None
        self._pending_fine_clip_id: str | None = None
        self._pending_fine_end_clip_id: str | None = None
        self._waveform_debounce_started_at: float | None = None
        self._fine_debounce_started_at: float | None = None
        self._fine_end_debounce_started_at: float | None = None
        self._displayed_waveform_viewport: tuple[str, str] | None = None
        self._displayed_fine_extract_start: float | None = None
        self._displayed_fine_end_extract_start: float | None = None
        self._active_candidate: ClipCandidate | None = None

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
        if pane_id == DETAIL_TAB_BASIC:
            self._cancel_fine_debounce()
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
        self._cancel_fine_debounce()
        self._detail_tab = DETAIL_TAB_BASIC
        self._sync_detail_tabs()

    def open_fine_start_tab(self, candidate: ClipCandidate) -> None:
        if self._detail_tab == DETAIL_TAB_FINE_START:
            return
        self.stop_playback()
        self._cancel_fine_debounce()
        self._active_candidate = candidate
        self._update_fine_start_tab_labels(candidate)
        self._detail_tab = DETAIL_TAB_FINE_START
        self._sync_detail_tabs()

    def open_fine_end_tab(self, candidate: ClipCandidate) -> None:
        if self._detail_tab == DETAIL_TAB_FINE_END:
            return
        self.stop_playback()
        self._cancel_fine_debounce()
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
        self._displayed_waveform_viewport = None
        self._displayed_fine_extract_start = None
        self._displayed_fine_end_extract_start = None
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

    @staticmethod
    def _fine_slice_marker_positions(
        extract_start: float, candidate: ClipCandidate
    ) -> tuple[float, float]:
        clip_start = ClipDetailPanel._clip_start_seconds(candidate)
        clip_end = ClipDetailPanel._clip_end_seconds(candidate)
        rel_start = clip_start - extract_start
        rel_end = clip_end - extract_start
        return rel_start, rel_end

    def _needs_fine_start_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_fine_extract_start is None:
            return True
        margin = WAVEFORM_REGEN_MARGIN_SECONDS
        window = FINE_VIEW_SECONDS
        extract = self._displayed_fine_extract_start
        rel_start, _rel_end = self._fine_slice_marker_positions(extract, candidate)
        if rel_start < -margin or rel_start > window + margin:
            return True
        return rel_start >= FINE_START_REGEN_RIGHT_THRESHOLD

    def _needs_fine_end_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_fine_end_extract_start is None:
            return True
        margin = WAVEFORM_REGEN_MARGIN_SECONDS
        window = FINE_VIEW_SECONDS
        extract = self._displayed_fine_end_extract_start
        _rel_start, rel_end = self._fine_slice_marker_positions(extract, candidate)
        if rel_end < -margin or rel_end > window + margin:
            return True
        return rel_end <= FINE_END_REGEN_LEFT_THRESHOLD

    def update_after_nudge(self, candidate: ClipCandidate) -> None:
        """Refresh trim labels and markers; regen waveform when trim leaves the view."""
        self._active_candidate = candidate
        self._update_nudge_times_labels(candidate)
        if self.is_fine_start_tab():
            self._refresh_fine_start_waveform_markers(candidate)
            self._schedule_fine_start_feedback(candidate.clip_id)
        elif self.is_fine_end_tab():
            self._refresh_fine_end_waveform_markers(candidate)
            self._schedule_fine_end_feedback(candidate.clip_id)
        else:
            self._refresh_waveform_markers(candidate)
            if self._needs_waveform_regen(candidate):
                self._schedule_waveform_refresh(candidate.clip_id)
            elif self._waveform_debounce_timer is not None:
                self._waveform_debounce_timer.stop()
                self._waveform_debounce_timer = None
                self._pending_waveform_id = None
                self._waveform_debounce_started_at = None

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
        if debounce_waveform:
            if self.is_fine_start_tab():
                self._schedule_fine_start_feedback(candidate.clip_id)
                self._refresh_fine_start_waveform_markers(candidate)
            elif self.is_fine_end_tab():
                self._schedule_fine_end_feedback(candidate.clip_id)
                self._refresh_fine_end_waveform_markers(candidate)
            else:
                if waveform_regen_on_debounce:
                    self._schedule_waveform_refresh(
                        candidate.clip_id, force_regen=force_waveform_regen
                    )
                self._refresh_waveform_markers(candidate)
        else:
            self._cancel_waveform_debounce()
            if self.is_fine_start_tab():
                self._show_fine_start_waveform(candidate)
            elif self.is_fine_end_tab():
                self._show_fine_end_waveform(candidate)
            else:
                self._show_waveform(candidate)

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

    def _cancel_fine_start_debounce(self) -> None:
        if self._fine_debounce_timer is not None:
            self._fine_debounce_timer.stop()
            self._fine_debounce_timer = None
        self._pending_fine_clip_id = None
        self._fine_debounce_started_at = None

    def _cancel_fine_end_debounce(self) -> None:
        if self._fine_end_debounce_timer is not None:
            self._fine_end_debounce_timer.stop()
            self._fine_end_debounce_timer = None
        self._pending_fine_end_clip_id = None
        self._fine_end_debounce_started_at = None

    def _cancel_fine_debounce(self) -> None:
        self._cancel_fine_start_debounce()
        self._cancel_fine_end_debounce()

    def _cancel_waveform_debounce(self) -> None:
        if self._waveform_debounce_timer is not None:
            self._waveform_debounce_timer.stop()
            self._waveform_debounce_timer = None
        self._pending_waveform_id = None
        self._waveform_debounce_started_at = None
        self._cancel_fine_debounce()

    def _needs_waveform_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_waveform_viewport is None:
            return True
        disp_start = srt_time_to_seconds(
            self._displayed_waveform_viewport[0].replace(".", ",")
        )
        disp_end = disp_start + float(self._displayed_waveform_viewport[1])
        clip_start = self._clip_start_seconds(candidate)
        clip_end = self._clip_end_seconds(candidate)
        margin = WAVEFORM_REGEN_MARGIN_SECONDS
        return (
            clip_start < disp_start - margin or clip_end > disp_end + margin
        )

    def _schedule_waveform_refresh(
        self, clip_id: str, *, force_regen: bool = False
    ) -> None:
        self._pending_waveform_id = clip_id
        now = time.monotonic()
        if self._waveform_debounce_started_at is None:
            self._waveform_debounce_started_at = now

        if self._waveform_debounce_timer is not None:
            self._waveform_debounce_timer.stop()
            self._waveform_debounce_timer = None

        elapsed = now - self._waveform_debounce_started_at
        if elapsed >= WAVEFORM_DEBOUNCE_MAX_SECONDS:
            delay = 0.0
        else:
            delay = min(
                WAVEFORM_DEBOUNCE_SECONDS,
                WAVEFORM_DEBOUNCE_MAX_SECONDS - elapsed,
            )

        def refresh_waveform() -> None:
            self._waveform_debounce_timer = None
            self._waveform_debounce_started_at = None
            pending_id = self._pending_waveform_id
            self._pending_waveform_id = None
            if pending_id != clip_id:
                return
            candidate = self.session.get_candidate(clip_id)
            if candidate is None:
                return
            self._refresh_waveform_markers(candidate)
            if force_regen or self._needs_waveform_regen(candidate):
                self._waveform_generation += 1
                self._show_waveform(candidate, keep_previous=True)

        self._waveform_debounce_timer = self.set_timer(
            max(delay, MIN_SCHEDULE_DELAY_SECONDS),
            refresh_waveform,
            name="waveform-debounce",
        )

    def _schedule_fine_start_feedback(self, clip_id: str) -> None:
        self._pending_fine_clip_id = clip_id
        now = time.monotonic()
        if self._fine_debounce_started_at is None:
            self._fine_debounce_started_at = now

        if self._fine_debounce_timer is not None:
            self._fine_debounce_timer.stop()
            self._fine_debounce_timer = None

        elapsed = now - self._fine_debounce_started_at
        if elapsed >= WAVEFORM_DEBOUNCE_MAX_SECONDS:
            delay = 0.0
        else:
            delay = min(
                WAVEFORM_DEBOUNCE_SECONDS,
                WAVEFORM_DEBOUNCE_MAX_SECONDS - elapsed,
            )

        def refresh_fine() -> None:
            self._fine_debounce_timer = None
            self._fine_debounce_started_at = None
            pending_id = self._pending_fine_clip_id
            self._pending_fine_clip_id = None
            if pending_id != clip_id:
                return
            if not self.is_fine_start_tab():
                return
            candidate = self.session.get_candidate(clip_id)
            if candidate is None:
                return
            self._refresh_fine_start_waveform_markers(candidate)
            if self._needs_fine_start_regen(candidate):
                self._refresh_fine_start_feedback(
                    candidate, keep_previous=True, play=False
                )
            self.run_play_fine_start_preview(candidate)

        self._fine_debounce_timer = self.set_timer(
            max(delay, MIN_SCHEDULE_DELAY_SECONDS),
            refresh_fine,
            name="fine-debounce",
        )

    def _refresh_fine_start_feedback(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play: bool = True,
    ) -> None:
        cached = self._fine_waveform_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_start_waveform(
                candidate,
                cached,
                media_duration=self._waveform_media_duration(cached),
            )
            if play:
                self.run_play_fine_start_preview(candidate)
            return
        self._start_fine_start_waveform_generation(
            candidate, keep_previous=keep_previous, play_after=play
        )

    def _schedule_fine_end_feedback(self, clip_id: str) -> None:
        self._pending_fine_end_clip_id = clip_id
        now = time.monotonic()
        if self._fine_end_debounce_started_at is None:
            self._fine_end_debounce_started_at = now

        if self._fine_end_debounce_timer is not None:
            self._fine_end_debounce_timer.stop()
            self._fine_end_debounce_timer = None

        elapsed = now - self._fine_end_debounce_started_at
        if elapsed >= WAVEFORM_DEBOUNCE_MAX_SECONDS:
            delay = 0.0
        else:
            delay = min(
                WAVEFORM_DEBOUNCE_SECONDS,
                WAVEFORM_DEBOUNCE_MAX_SECONDS - elapsed,
            )

        def refresh_fine_end() -> None:
            self._fine_end_debounce_timer = None
            self._fine_end_debounce_started_at = None
            pending_id = self._pending_fine_end_clip_id
            self._pending_fine_end_clip_id = None
            if pending_id != clip_id:
                return
            if not self.is_fine_end_tab():
                return
            candidate = self.session.get_candidate(clip_id)
            if candidate is None:
                return
            self._refresh_fine_end_waveform_markers(candidate)
            if self._needs_fine_end_regen(candidate):
                self._refresh_fine_end_feedback(
                    candidate, keep_previous=True, play=False
                )
            self.run_play_fine_end_preview(candidate)

        self._fine_end_debounce_timer = self.set_timer(
            max(delay, MIN_SCHEDULE_DELAY_SECONDS),
            refresh_fine_end,
            name="fine-end-debounce",
        )

    def _refresh_fine_end_feedback(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play: bool = True,
    ) -> None:
        cached = self._fine_end_waveform_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_end_waveform(
                candidate,
                cached,
                media_duration=self._waveform_media_duration(cached),
            )
            if play:
                self.run_play_fine_end_preview(candidate)
            return
        self._start_fine_end_waveform_generation(
            candidate, keep_previous=keep_previous, play_after=play
        )

    @staticmethod
    def _waveform_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.start}|{candidate.duration}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def waveform_cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._waveform_key_digest(candidate)
        return self._waveform_cache_dir / f"{candidate.filename_token}_{digest}{suffix}"

    @staticmethod
    def _fine_start_waveform_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.start}|{FINE_VIEW_DURATION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def _fine_start_waveform_cache_path(
        self, candidate: ClipCandidate, *, suffix: str
    ) -> Path:
        digest = self._fine_start_waveform_key_digest(candidate)
        return (
            self._waveform_cache_dir
            / f"{candidate.filename_token}_{digest}{FINE_START_CACHE_SUFFIX}{suffix}"
        )

    @staticmethod
    def _fine_end_waveform_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.end}|{FINE_VIEW_DURATION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def _fine_end_waveform_cache_path(
        self, candidate: ClipCandidate, *, suffix: str
    ) -> Path:
        digest = self._fine_end_waveform_key_digest(candidate)
        return (
            self._waveform_cache_dir
            / f"{candidate.filename_token}_{digest}{FINE_END_CACHE_SUFFIX}{suffix}"
        )

    def _fine_waveform_cache_path(
        self, candidate: ClipCandidate, *, suffix: str
    ) -> Path:
        return self._fine_start_waveform_cache_path(candidate, suffix=suffix)

    def _present_waveform(
        self,
        path: Path,
        viewport_start: str,
        viewport_duration: str,
        *,
        media_duration: float | None = None,
    ) -> None:
        self._displayed_waveform_viewport = (viewport_start, viewport_duration)
        self.query_one("#waveform", WaveformWidget).display_waveform(
            path,
            viewport_start,
            viewport_duration,
            media_duration=media_duration,
        )

    def _fine_start_waveform_widget(self) -> WaveformWidget:
        return self.query_one("#waveform-fine", WaveformWidget)

    def _fine_end_waveform_widget(self) -> WaveformWidget:
        return self.query_one("#waveform-fine-end", WaveformWidget)

    def _fine_waveform_widget(self) -> WaveformWidget:
        return self._fine_start_waveform_widget()

    def _set_fine_start_waveform_placeholder(self, message: str) -> None:
        self._fine_start_waveform_widget().show_placeholder(message)

    def _set_fine_end_waveform_placeholder(self, message: str) -> None:
        self._fine_end_waveform_widget().show_placeholder(message)

    def _set_fine_waveform_placeholder(self, message: str) -> None:
        self._set_fine_start_waveform_placeholder(message)

    @staticmethod
    def _clip_start_seconds(candidate: ClipCandidate) -> float:
        return srt_time_to_seconds(candidate.start.replace(".", ","))

    @staticmethod
    def _clip_end_seconds(candidate: ClipCandidate) -> float:
        return srt_time_to_seconds(candidate.end.replace(".", ","))

    @staticmethod
    def _fine_end_extract_start(candidate: ClipCandidate) -> float:
        start = ClipDetailPanel._clip_start_seconds(candidate)
        end = ClipDetailPanel._clip_end_seconds(candidate)
        return max(start, end - FINE_VIEW_SECONDS)

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
            FINE_VIEW_DURATION,
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
    ) -> None:
        self._displayed_fine_extract_start = self._clip_start_seconds(candidate)
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
    ) -> None:
        self._displayed_fine_end_extract_start = self._fine_end_extract_start(
            candidate
        )
        self._present_fine_slice_waveform(
            self._fine_end_waveform_widget(),
            candidate,
            path,
            media_duration=media_duration,
            refresh_markers=self._refresh_fine_end_waveform_markers,
        )

    def _present_fine_waveform(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
    ) -> None:
        self._present_fine_start_waveform(
            candidate, path, media_duration=media_duration
        )

    @staticmethod
    def _waveform_media_duration(png_path: Path) -> float | None:
        mp3_path = png_path.with_name(png_path.stem + ".mp3")
        if not mp3_path.exists():
            return None
        try:
            return ffmpeg.probe_duration_seconds(mp3_path)
        except (OSError, subprocess.CalledProcessError, ValueError):
            return None

    def _overlay_fine_slice_markers(
        self,
        widget: WaveformWidget,
        extract_start: float | None,
        candidate: ClipCandidate,
    ) -> None:
        if extract_start is None:
            return
        rel_start, rel_end = self._fine_slice_marker_positions(
            extract_start, candidate
        )
        window = FINE_VIEW_SECONDS
        marker_start = max(0.0, min(rel_start, window))
        marker_end = max(marker_start, min(rel_end, window))
        widget.overlay_trim_bounds(
            seconds_to_ffmpeg_timestamp(marker_start),
            seconds_to_ffmpeg_timestamp(marker_end),
        )

    def _refresh_waveform_markers(self, candidate: ClipCandidate) -> None:
        if self._displayed_waveform_viewport is None:
            return
        self.query_one("#waveform", WaveformWidget).overlay_trim_bounds(
            candidate.start,
            candidate.end,
        )

    def _refresh_fine_start_waveform_markers(self, candidate: ClipCandidate) -> None:
        self._overlay_fine_slice_markers(
            self._fine_start_waveform_widget(),
            self._displayed_fine_extract_start,
            candidate,
        )

    def _refresh_fine_end_waveform_markers(self, candidate: ClipCandidate) -> None:
        self._overlay_fine_slice_markers(
            self._fine_end_waveform_widget(),
            self._displayed_fine_end_extract_start,
            candidate,
        )

    def _refresh_fine_waveform_markers(self, candidate: ClipCandidate) -> None:
        self._refresh_fine_start_waveform_markers(candidate)

    def _show_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        cached = self.waveform_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_waveform(
                cached,
                candidate.start,
                candidate.duration,
                media_duration=self._waveform_media_duration(cached),
            )
            return
        self._generate_waveform(candidate, keep_previous=keep_previous)

    def _show_fine_start_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        cached = self._fine_start_waveform_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_start_waveform(
                candidate,
                cached,
                media_duration=self._waveform_media_duration(cached),
            )
            return
        self._start_fine_start_waveform_generation(
            candidate, keep_previous=keep_previous
        )

    def _show_fine_end_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        cached = self._fine_end_waveform_cache_path(candidate, suffix=".png")
        if cached.exists():
            self._present_fine_end_waveform(
                candidate,
                cached,
                media_duration=self._waveform_media_duration(cached),
            )
            return
        self._start_fine_end_waveform_generation(
            candidate, keep_previous=keep_previous
        )

    def _show_fine_waveform(
        self, candidate: ClipCandidate, *, keep_previous: bool = False
    ) -> None:
        self._show_fine_start_waveform(candidate, keep_previous=keep_previous)

    def _start_fine_slice_waveform_generation(
        self,
        *,
        candidate: ClipCandidate,
        generation_attr: str,
        set_placeholder: Callable[[str], None],
        present: Callable[[ClipCandidate, Path, float | None], None],
        generate_file: Callable[[ClipCandidate], tuple[Path, float]],
        play_after: bool = False,
        play_preview: Callable[[ClipCandidate], None] | None = None,
        keep_previous: bool = False,
    ) -> None:
        generation = getattr(self, generation_attr) + 1
        setattr(self, generation_attr, generation)
        if not keep_previous:
            set_placeholder(GENERATING_WAVEFORM_PLACEHOLDER)

        app = self.app

        def run() -> None:
            try:
                target_png, media_duration = generate_file(candidate)
            except Exception as exc:
                if generation == getattr(self, generation_attr):
                    app.call_from_thread(set_placeholder, f"Waveform failed: {exc}")
                return
            if generation != getattr(self, generation_attr):
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
        self._start_fine_slice_waveform_generation(
            candidate=candidate,
            generation_attr="_fine_waveform_generation",
            set_placeholder=self._set_fine_start_waveform_placeholder,
            present=lambda c, path, dur: self._present_fine_start_waveform(
                c, path, media_duration=dur
            ),
            generate_file=self._generate_fine_start_waveform_file,
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
        self._start_fine_slice_waveform_generation(
            candidate=candidate,
            generation_attr="_fine_end_waveform_generation",
            set_placeholder=self._set_fine_end_waveform_placeholder,
            present=lambda c, path, dur: self._present_fine_end_waveform(
                c, path, media_duration=dur
            ),
            generate_file=self._generate_fine_end_waveform_file,
            play_after=play_after,
            play_preview=self.run_play_fine_end_preview,
            keep_previous=keep_previous,
        )

    def _start_fine_waveform_generation(
        self,
        candidate: ClipCandidate,
        *,
        keep_previous: bool = False,
        play_after: bool = False,
    ) -> None:
        self._start_fine_start_waveform_generation(
            candidate, keep_previous=keep_previous, play_after=play_after
        )

    def generate_waveform_file(self, candidate: ClipCandidate) -> tuple[Path, float]:
        """Generate (or reuse) the cached waveform PNG for ``candidate``.

        Safe to call from a worker thread; performs no UI work.
        """
        target_png = self.waveform_cache_path(candidate, suffix=".png")
        target_mp3 = self.waveform_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        target_png.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.extract_preview(
            self.session.audio,
            candidate.start,
            candidate.duration,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

    def _generate_fine_start_waveform_file(
        self, candidate: ClipCandidate
    ) -> tuple[Path, float]:
        target_png = self._fine_start_waveform_cache_path(candidate, suffix=".png")
        target_mp3 = self._fine_start_waveform_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        target_png.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.extract_preview(
            self.session.audio,
            candidate.start,
            FINE_VIEW_DURATION,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

    def _generate_fine_end_waveform_file(
        self, candidate: ClipCandidate
    ) -> tuple[Path, float]:
        target_png = self._fine_end_waveform_cache_path(candidate, suffix=".png")
        target_mp3 = self._fine_end_waveform_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        extract_start = self._fine_end_extract_start(candidate)
        extract_duration = min(
            FINE_VIEW_SECONDS,
            self._clip_end_seconds(candidate) - extract_start,
        )
        duration_str = f"{extract_duration:.3f}"
        target_png.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.extract_preview(
            self.session.audio,
            seconds_to_ffmpeg_timestamp(extract_start),
            duration_str,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

    def _generate_fine_waveform_file(
        self, candidate: ClipCandidate
    ) -> tuple[Path, float]:
        return self._generate_fine_start_waveform_file(candidate)

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

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_fine_start_preview(self, candidate: ClipCandidate) -> None:
        self._run_play_fine_slice_preview(
            candidate,
            candidate.start,
            FINE_VIEW_SECONDS,
        )

    @work(thread=True, exclusive=True, group="detail-playback")
    def run_play_fine_end_preview(self, candidate: ClipCandidate) -> None:
        extract_start = self._fine_end_extract_start(candidate)
        duration = min(
            FINE_VIEW_SECONDS,
            self._clip_end_seconds(candidate) - extract_start,
        )
        self._run_play_fine_slice_preview(
            candidate,
            seconds_to_ffmpeg_timestamp(extract_start),
            duration,
        )

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
        generation = self._waveform_generation + 1
        self._waveform_generation = generation
        if not (keep_previous and self._displayed_waveform_viewport is not None):
            self.app.call_from_thread(
                self._set_full_waveform_placeholder,
                GENERATING_WAVEFORM_PLACEHOLDER,
            )
        try:
            target_png, media_duration = self.generate_waveform_file(candidate)
            if generation != self._waveform_generation:
                return
            self.app.call_from_thread(
                self._present_waveform,
                target_png,
                candidate.start,
                candidate.duration,
                media_duration=media_duration,
            )
        except Exception as exc:
            if generation != self._waveform_generation:
                return
            self.app.call_from_thread(
                self._set_full_waveform_placeholder,
                f"Waveform failed: {exc}",
            )

    def _set_full_waveform_placeholder(self, message: str) -> None:
        self.query_one("#waveform", WaveformWidget).show_placeholder(message)

