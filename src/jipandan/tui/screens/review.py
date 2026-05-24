import time
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, ClipStatus, Session
from jipandan.core.ffmpeg import ExportOptions
from jipandan.tui.screens.export_mode import ExportModeModal
from jipandan.tui.screens.export_title import ExportTitleModal
from jipandan.tui.widgets.waveform import FINETUNE_HELP, WaveformWidget, format_playback_remaining

STATUS_BADGE: dict[ClipStatus, str] = {
    "pending": "  ",
    "group1": "G1",
    "group2": "G2",
    "exported": "EX",
    "skipped": "--",
}

FILTER_ORDER = ["all", "group1", "group2", "exported"]
FILTER_LABELS = {
    "all": "All",
    "group1": "G1",
    "group2": "G2",
    "exported": "Exported",
}

SKIPPED_HIDDEN_CLASS = "skipped-hidden"
WAVEFORM_DEBOUNCE_SECONDS = 0.4


class ClipListItem(ListItem):
    def __init__(self, candidate: ClipCandidate) -> None:
        self.candidate_index = candidate.index
        super().__init__(Label(self.label_text(candidate)))

    @staticmethod
    def label_text(candidate: ClipCandidate) -> str:
        badge = STATUS_BADGE[candidate.status]
        title = candidate.title
        if len(title) > 48:
            title = title[:45] + "..."
        return f"{candidate.index:4d} ({badge}) {title}"

    def refresh_candidate(self, candidate: ClipCandidate) -> None:
        self.query_one(Label).update(self.label_text(candidate))


class ReviewScreen(Screen):
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("1", "mark_group1", "Group 1"),
        Binding("2", "mark_group2", "Group 2"),
        Binding("x", "mark_skipped", "Skip"),
        Binding("u", "undo_skip", "Undo skip"),
        Binding("ctrl+shift+x", "bulk_skip_above", "Skip above"),
        Binding("space", "play_preview", "Play"),
        Binding("[", "nudge_start_down", "Start -"),
        Binding("]", "nudge_start_up", "Start +"),
        Binding("{", "nudge_end_down", "End -"),
        Binding("}", "nudge_end_up", "End +"),
        Binding("e", "export_clip", "Export"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("h", "toggle_hide_skipped", "Hide skipped"),
        Binding("ctrl+s", "save_session", "Save"),
        Binding("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    ReviewScreen {
        layout: vertical;
    }

    #filter-bar {
        height: 1;
        padding: 0 1;
        background: $surface;
    }

    #main-pane {
        height: 1fr;
    }

    #clip-list {
        width: 40%;
        border: solid $primary;
    }

    #clip-list ListItem.skipped-hidden {
        display: none;
    }

    #detail-panel {
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

    #waveform-hints {
        height: 1;
        width: 100%;
        color: $text-muted;
        padding-bottom: 1;
    }

    #clip-times, #clip-status {
        height: auto;
        padding-top: 1;
    }

    #help-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.filter_mode = "all"
        self.hide_skipped = True
        self.filtered_indices: list[int] = []
        self._waveform_generation = 0
        self._waveform_cache: dict[tuple[int, str, str], Path] = {}
        self._skip_undo_stack: list[tuple[int, ClipStatus]] = []
        self._playback_end: float | None = None
        self._playback_timer: Timer | None = None
        self._waveform_debounce_timer: Timer | None = None
        self._pending_waveform_index: int | None = None
        self._displayed_waveform_viewport: tuple[str, str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._filter_bar_text(include_position=False), id="filter-bar")
        with Horizontal(id="main-pane"):
            yield ListView(id="clip-list")
            with Vertical(id="detail-panel"):
                yield Static("", id="playback-status")
                yield Static("", id="clip-title")
                yield WaveformWidget(id="waveform")
                yield Static(FINETUNE_HELP, id="waveform-hints")
                yield Static("", id="clip-times")
                yield Static("", id="clip-status")
        yield Static(self._help_text(), id="help-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_list(select_first=True)

    def _filter_bar_text(self, include_position: bool = True) -> str:
        total = len(self.session.candidates)
        position = ""
        if include_position:
            current = self._current_candidate()
            if current is not None:
                try:
                    pos = self.filtered_indices.index(current.index) + 1
                    position = f"  {pos}/{len(self.filtered_indices)}"
                except ValueError:
                    pass
        filters = " | ".join(
            f"({FILTER_LABELS[mode]})" if mode == self.filter_mode else FILTER_LABELS[mode]
            for mode in FILTER_ORDER
        )
        hide_label = "on" if self.hide_skipped else "off"
        return (
            f"{self.session.audio.name}  Filter: {filters}  "
            f"Hide skipped: {hide_label}{position}  ({total} clips)"
        )

    def _help_text(self) -> str:
        return (
            "j/k nav  1/2 group  x skip  u undo skip  Ctrl+Shift+X skip above  "
            "f filter  h hide skipped  Ctrl+S save  q quit"
        )

    def _visible_candidates(self) -> list[ClipCandidate]:
        if self.filter_mode == "all":
            candidates = self.session.candidates
        else:
            candidates = [
                candidate
                for candidate in self.session.candidates
                if candidate.status == self.filter_mode
            ]
        if self.hide_skipped:
            candidates = [candidate for candidate in candidates if candidate.status != "skipped"]
        return candidates

    def _candidate_index_after_removing(self, visible_index: int) -> int | None:
        if visible_index + 1 < len(self.filtered_indices):
            return self.filtered_indices[visible_index + 1]
        if visible_index > 0:
            return self.filtered_indices[visible_index - 1]
        return None

    @staticmethod
    def _is_visible_item(item: ListItem) -> bool:
        return isinstance(item, ClipListItem) and SKIPPED_HIDDEN_CLASS not in item.classes

    def _visible_position(self, list_view: ListView, dom_index: int) -> int:
        visible = 0
        for index, item in enumerate(list_view.children):
            if index == dom_index:
                return visible
            if self._is_visible_item(item):
                visible += 1
        raise IndexError(dom_index)

    def _next_visible_dom_index(
        self,
        list_view: ListView,
        from_dom_index: int,
        *,
        forward: bool = True,
    ) -> int | None:
        if forward:
            indices = range(from_dom_index + 1, len(list_view.children))
        else:
            indices = range(from_dom_index - 1, -1, -1)
        for index in indices:
            if self._is_visible_item(list_view.children[index]):
                return index
        return None

    def _sync_filtered_indices(self, list_view: ListView) -> None:
        self.filtered_indices = [
            item.candidate_index
            for item in list_view.children
            if self._is_visible_item(item)
        ]

    def _select_after_hide(
        self,
        list_view: ListView,
        hidden_dom_index: int,
        next_candidate_index: int | None,
    ) -> None:
        next_dom = self._next_visible_dom_index(list_view, hidden_dom_index)
        if next_dom is None:
            next_dom = self._next_visible_dom_index(
                list_view, hidden_dom_index, forward=False
            )
        if next_dom is not None:
            list_view.index = next_dom
        else:
            list_view.index = None
        self.query_one("#filter-bar", Static).update(self._filter_bar_text())
        if next_candidate_index is not None:
            self._update_detail(next_candidate_index)
        else:
            self._clear_detail()

    def _find_list_item(self, candidate_index: int) -> ClipListItem | None:
        list_view = self.query_one("#clip-list", ListView)
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_index == candidate_index:
                return item
        return None

    def _restore_skipped(
        self,
        candidate_index: int,
        previous_status: ClipStatus,
    ) -> None:
        candidate = self.session.get_candidate(candidate_index)
        if candidate is None:
            return
        candidate.status = previous_status
        list_view = self.query_one("#clip-list", ListView)
        item = self._find_list_item(candidate_index)
        if item is None:
            return
        item.remove_class(SKIPPED_HIDDEN_CLASS)
        item.refresh_candidate(candidate)
        self._sync_filtered_indices(list_view)
        list_view.index = list_view.children.index(item)
        self._update_detail(candidate_index)

    def _hide_skipped_at(
        self,
        list_view: ListView,
        dom_index: int,
        next_candidate_index: int | None,
    ) -> None:
        item = list_view.children[dom_index]
        if isinstance(item, ClipListItem):
            item.add_class(SKIPPED_HIDDEN_CLASS)
        visible_index = self._visible_position(list_view, dom_index)
        del self.filtered_indices[visible_index]
        self._select_after_hide(list_view, dom_index, next_candidate_index)

    def _hide_skipped_bulk(
        self,
        list_view: ListView,
        candidate_indices: list[int],
        next_candidate_index: int | None,
    ) -> None:
        candidate_set = set(candidate_indices)
        hidden_dom_index = list_view.index or 0
        for item in list_view.children:
            if not isinstance(item, ClipListItem):
                continue
            if item.candidate_index not in candidate_set:
                continue
            candidate = self.session.get_candidate(item.candidate_index)
            if candidate is not None and candidate.status == "skipped":
                item.add_class(SKIPPED_HIDDEN_CLASS)
        self._sync_filtered_indices(list_view)
        self._select_after_hide(list_view, hidden_dom_index, next_candidate_index)

    @work(exclusive=True)
    async def _rebuild_list(
        self,
        select_first: bool = False,
        preserve_index: int | None = None,
    ) -> None:
        list_view = self.query_one("#clip-list", ListView)
        await list_view.clear()
        self.filtered_indices = []
        items: list[ClipListItem] = []
        for candidate in self._visible_candidates():
            self.filtered_indices.append(candidate.index)
            items.append(ClipListItem(candidate))
        self.query_one("#filter-bar", Static).update(self._filter_bar_text())
        if items:
            await list_view.mount(*items)
        if preserve_index is not None and preserve_index in self.filtered_indices:
            list_view.index = self.filtered_indices.index(preserve_index)
            self._update_detail(preserve_index)
        elif preserve_index is not None and self.filtered_indices:
            list_view.index = 0
            self._update_detail(self.filtered_indices[0])
        elif select_first and self.filtered_indices:
            list_view.index = 0
            self._update_detail(self.filtered_indices[0])
        elif not self.filtered_indices:
            list_view.index = None
            self._clear_detail()

    def _highlighted_item(self) -> ClipListItem | None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return None
        try:
            item = list_view.children[list_view.index]
        except IndexError:
            return None
        if self._is_visible_item(item):
            return item
        return None

    def _current_candidate(self) -> ClipCandidate | None:
        item = self._highlighted_item()
        if item is None:
            return None
        return self.session.get_candidate(item.candidate_index)

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

    def _clear_detail(self) -> None:
        self._displayed_waveform_viewport = None
        self.query_one("#clip-title", Static).update("No clips in current filter.")
        self.query_one("#waveform", WaveformWidget).show_placeholder("No waveform.")
        self.query_one("#clip-times", Static).update("")
        self.query_one("#clip-status", Static).update("")

    def _cancel_waveform_debounce(self) -> None:
        if self._waveform_debounce_timer is not None:
            self._waveform_debounce_timer.stop()
            self._waveform_debounce_timer = None
        self._pending_waveform_index = None

    def _schedule_waveform_refresh(self, candidate_index: int) -> None:
        self._waveform_generation += 1
        self._cancel_waveform_debounce()
        self._pending_waveform_index = candidate_index

        def refresh_waveform() -> None:
            self._waveform_debounce_timer = None
            if self._pending_waveform_index != candidate_index:
                return
            candidate = self.session.get_candidate(candidate_index)
            if candidate is None:
                return
            self._show_waveform(candidate)

        self._waveform_debounce_timer = self.set_timer(
            WAVEFORM_DEBOUNCE_SECONDS,
            refresh_waveform,
            name="waveform-debounce",
        )

    def _update_detail(self, index: int, *, debounce_waveform: bool = False) -> None:
        candidate = self.session.get_candidate(index)
        if candidate is None:
            self._clear_detail()
            return

        offset = candidate.start_offset_seconds()
        offset_text = f"{offset:+.3f}s from original"
        self.query_one("#clip-title", Static).update(
            f"#{candidate.index}  {candidate.title}"
        )
        self.query_one("#clip-times", Static).update(
            f"Start: {candidate.start}  ({offset_text})\n"
            f"End: {candidate.end}  Duration: {candidate.duration}s"
        )
        self.query_one("#clip-status", Static).update(
            f"Status: {candidate.status}  Original: {candidate.original_start} → {candidate.original_end}"
        )
        self.query_one("#filter-bar", Static).update(self._filter_bar_text())
        if debounce_waveform:
            self._schedule_waveform_refresh(index)
            self._refresh_waveform_markers(candidate)
        else:
            self._cancel_waveform_debounce()
            self._show_waveform(candidate)

    @staticmethod
    def _waveform_cache_key(candidate: ClipCandidate) -> tuple[int, str, str]:
        return (candidate.index, candidate.start, candidate.duration)

    def _present_waveform(
        self,
        path: Path,
        viewport_start: str,
        viewport_duration: str,
    ) -> None:
        self._displayed_waveform_viewport = (viewport_start, viewport_duration)
        self.query_one("#waveform", WaveformWidget).display_waveform(
            path,
            viewport_start,
            viewport_duration,
        )

    def _refresh_waveform_markers(self, candidate: ClipCandidate) -> None:
        if self._displayed_waveform_viewport is None:
            return
        self.query_one("#waveform", WaveformWidget).overlay_trim_bounds(
            candidate.start,
            candidate.end,
        )

    def _show_waveform(self, candidate: ClipCandidate) -> None:
        cache_key = self._waveform_cache_key(candidate)
        cached = self._waveform_cache.get(cache_key)
        if cached is not None and cached.exists():
            self._present_waveform(cached, candidate.start, candidate.duration)
            return
        self._generate_waveform(candidate)

    @on(ListView.Selected)
    def on_list_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ClipListItem):
            self._update_detail(item.candidate_index)

    def _refresh_list_item(self, candidate: ClipCandidate) -> None:
        list_view = self.query_one("#clip-list", ListView)
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_index == candidate.index:
                item.refresh_candidate(candidate)
                break

    def _persist(self) -> None:
        self.session.save()

    def _set_status(self, status: ClipStatus) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        list_view = self.query_one("#clip-list", ListView)
        dom_index = list_view.index
        visible_index = (
            self._visible_position(list_view, dom_index)
            if dom_index is not None
            else None
        )
        preserve = (
            self._candidate_index_after_removing(visible_index)
            if visible_index is not None
            else None
        )
        previous_status = candidate.status
        candidate.status = status
        if self.hide_skipped and status == "skipped":
            self._skip_undo_stack.append((candidate.index, previous_status))
            self._persist()
            if dom_index is not None:
                self._hide_skipped_at(list_view, dom_index, preserve)
            return
        self._refresh_list_item(candidate)
        if status == "skipped":
            self._skip_undo_stack.append((candidate.index, previous_status))
        self.query_one("#clip-status", Static).update(f"Status: {candidate.status}")
        self._persist()

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        next_dom = self._next_visible_dom_index(list_view, list_view.index)
        if next_dom is None:
            return
        list_view.index = next_dom
        item = list_view.children[next_dom]
        if isinstance(item, ClipListItem):
            self._update_detail(item.candidate_index)

    def action_cursor_up(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        next_dom = self._next_visible_dom_index(
            list_view, list_view.index, forward=False
        )
        if next_dom is None:
            return
        list_view.index = next_dom
        item = list_view.children[next_dom]
        if isinstance(item, ClipListItem):
            self._update_detail(item.candidate_index)

    def action_mark_group1(self) -> None:
        self._set_status("group1")

    def action_mark_group2(self) -> None:
        self._set_status("group2")

    def action_mark_skipped(self) -> None:
        self._set_status("skipped")

    def action_undo_skip(self) -> None:
        if not self._skip_undo_stack:
            self.notify("Nothing to undo")
            return
        candidate_index, previous_status = self._skip_undo_stack.pop()
        candidate = self.session.get_candidate(candidate_index)
        if candidate is None or candidate.status != "skipped":
            self.notify("Nothing to undo")
            return
        self._restore_skipped(candidate_index, previous_status)
        self._persist()
        self.notify(f"Restored #{candidate_index}")

    def action_bulk_skip_above(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None or not self.filtered_indices:
            return
        dom_index = list_view.index
        visible_index = self._visible_position(list_view, dom_index)
        preserve = self._candidate_index_after_removing(visible_index)
        indices_to_skip = self.filtered_indices[: visible_index + 1]
        restored_before_skip = [
            (index, "pending")
            for index in indices_to_skip
            if (candidate := self.session.get_candidate(index)) is not None
            and candidate.status == "pending"
        ]
        count = self.session.bulk_skip(indices_to_skip)
        for entry in restored_before_skip:
            self._skip_undo_stack.append(entry)
        self._persist()
        if self.hide_skipped and count > 0:
            self._hide_skipped_bulk(list_view, indices_to_skip, preserve)
        else:
            for index in indices_to_skip:
                candidate = self.session.get_candidate(index)
                if candidate is not None:
                    self._refresh_list_item(candidate)
            current = self._current_candidate()
            if current is not None:
                self.query_one("#clip-status", Static).update(f"Status: {current.status}")
        self.notify(f"Skipped {count} unmarked clips (current and above)")

    def action_cycle_filter(self) -> None:
        current_idx = FILTER_ORDER.index(self.filter_mode)
        self.filter_mode = FILTER_ORDER[(current_idx + 1) % len(FILTER_ORDER)]
        self._rebuild_list(select_first=True)

    def action_toggle_hide_skipped(self) -> None:
        self.hide_skipped = not self.hide_skipped
        current = self._current_candidate()
        preserve = current.index if current is not None else None
        self._rebuild_list(preserve_index=preserve)
        state = "hidden" if self.hide_skipped else "shown"
        self.notify(f"Skipped clips {state}")

    def action_save_session(self) -> None:
        self._persist()
        self.notify("Session saved.")

    def action_nudge_start_down(self) -> None:
        self._nudge_start(-0.1)

    def action_nudge_start_up(self) -> None:
        self._nudge_start(0.1)

    def action_nudge_end_down(self) -> None:
        self._nudge_end(-0.1)

    def action_nudge_end_up(self) -> None:
        self._nudge_end(0.1)

    def _nudge_start(self, delta: float) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.session.nudge_start(candidate.index, delta)
        self._update_detail(candidate.index, debounce_waveform=True)
        self._persist()

    def _nudge_end(self, delta: float) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.session.nudge_end(candidate.index, delta)
        self._update_detail(candidate.index, debounce_waveform=True)
        self._persist()

    def action_play_preview(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.run_play_preview(candidate)

    @work(thread=True, exclusive=True)
    def run_play_preview(self, candidate: ClipCandidate) -> None:
        duration = float(candidate.duration)
        self.app.call_from_thread(self._start_playback_status, duration)
        try:
            ffmpeg.play_preview(self.session.audio, candidate.start, candidate.duration)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"mpv failed: {exc}", severity="error")
        finally:
            self.app.call_from_thread(self._clear_playback_status)

    def action_export_clip(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.app.push_screen(
            ExportModeModal(),
            lambda options: self._after_export_mode(candidate.index, options),
        )

    def _after_export_mode(
        self, candidate_index: int, options: ExportOptions | None
    ) -> None:
        if options is None:
            return
        candidate = self.session.get_candidate(candidate_index)
        if candidate is None:
            return
        self.app.push_screen(
            ExportTitleModal(candidate.title),
            lambda title: self._start_export(candidate_index, options, title),
        )

    def _start_export(
        self,
        candidate_index: int,
        export_options: ExportOptions,
        title: str | None,
    ) -> None:
        if title is None:
            return
        candidate = self.session.get_candidate(candidate_index)
        if candidate is None:
            return
        candidate.title = title
        self._refresh_list_item(candidate)
        self._update_detail(candidate.index)
        self.run_export(candidate, title, export_options)

    @work(thread=True, exclusive=True)
    def run_export(
        self,
        candidate: ClipCandidate,
        export_title: str,
        export_options: ExportOptions,
    ) -> None:
        try:
            output = ffmpeg.export_clip(
                self.session.audio,
                candidate,
                self.session.clip_dir,
                export_title=export_title,
                export_options=export_options,
            )
            candidate.status = "exported"
            self.app.call_from_thread(self._after_export, candidate, output)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Export failed: {exc}", severity="error")

    def _after_export(self, candidate: ClipCandidate, output: Path) -> None:
        self._refresh_list_item(candidate)
        self.query_one("#clip-status", Static).update(
            f"Status: exported  Saved: {output}"
        )
        self._persist()
        self.notify(f"Exported {output.name}")
        self.run_play_exported(output, float(candidate.duration))

    @work(thread=True, exclusive=True)
    def run_play_exported(self, output: Path, duration: float) -> None:
        self.app.call_from_thread(self._start_playback_status, duration)
        try:
            ffmpeg.play_file(output)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"mpv failed: {exc}", severity="error")
        finally:
            self.app.call_from_thread(self._clear_playback_status)

    @work(thread=True, exclusive=True)
    def _generate_waveform(self, candidate: ClipCandidate) -> None:
        cache_key = self._waveform_cache_key(candidate)
        generation = self._waveform_generation + 1
        self._waveform_generation = generation
        tmp_dir = Path("tmp")
        tmp_mp3 = tmp_dir / f"clip_{candidate.index:04d}.mp3"
        tmp_png = tmp_dir / f"clip_{candidate.index:04d}.png"
        self.app.call_from_thread(
            self.query_one("#waveform", WaveformWidget).show_placeholder,
            "Generating waveform…",
        )
        try:
            ffmpeg.extract_preview(
                self.session.audio,
                candidate.start,
                candidate.duration,
                tmp_mp3,
            )
            ffmpeg.render_waveform(tmp_mp3, tmp_png)
            if generation != self._waveform_generation:
                return
            self._waveform_cache[cache_key] = tmp_png
            self.app.call_from_thread(
                self._present_waveform,
                tmp_png,
                candidate.start,
                candidate.duration,
            )
        except Exception as exc:
            if generation != self._waveform_generation:
                return
            self.app.call_from_thread(
                self.query_one("#waveform", WaveformWidget).show_placeholder,
                f"Waveform failed: {exc}",
            )
