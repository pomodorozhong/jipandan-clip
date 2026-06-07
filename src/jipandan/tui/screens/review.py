import threading
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Label, ListItem, ListView, Tab, Tabs

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, ClipStatus, Session
from jipandan.core.ffmpeg import ExportOptions
from jipandan.tui.screens.edit_title import EditTitleModal
from jipandan.tui.screens.export_mode import ExportModeModal
from jipandan.tui.screens.export_preview import (
    DEFAULT_PRELOAD_EXPORT_OPTIONS,
    ExportConfirm,
    ExportPreviewArtifacts,
    ExportPreviewModal,
    build_export_preview_artifacts,
    default_export_title,
    export_preview_key,
)
from jipandan.tui.screens.filter_selection import (
    FILTER_BAR_LABELS,
    FILTER_ORDER,
    FilterSelectionModal,
)
from jipandan.tui.screens.jump_to_index import JumpToIndexModal
from jipandan.tui.screens.start_offset import StartOffsetModal, TrimOffsets
from jipandan.tui.widgets.detail_panel import (
    ClipDetailPanel,
    FINE_NUDGE_COARSE,
    FINE_NUDGE_FINE,
)

STATUS_BADGE: dict[ClipStatus, str] = {
    "pending": "  ",
    "group1": "G1",
    "group2": "G2",
    "exported": "EX",
    "skipped": "--",
}

PROCESSED_HIDDEN_CLASS = "processed-hidden"
FILTER_HIDDEN_CLASS = "filter-hidden"


class FilterTabs(Tabs, can_focus=False):
    """Clip filter tabs; non-focusable so j/k navigation stays on the list."""


class ClipListItem(ListItem):
    DEFAULT_CSS = """
    ClipListItem > Horizontal {
        width: 100%;
        height: 1;
    }
    ClipListItem .clip-main {
        width: 1fr;
        height: 1;
    }
    ClipListItem .clip-duration {
        width: auto;
        height: 1;
        padding-left: 1;
    }
    """

    def __init__(self, candidate: ClipCandidate) -> None:
        self.candidate_id = candidate.clip_id
        super().__init__(
            Horizontal(
                Label(
                    self.label_text(candidate),
                    classes="clip-main",
                    markup=False,
                ),
                Label(
                    self.duration_text(candidate),
                    classes="clip-duration",
                    markup=False,
                ),
            )
        )

    @staticmethod
    def label_text(candidate: ClipCandidate) -> str:
        badge = STATUS_BADGE[candidate.status]
        title = candidate.title
        if len(title) > 48:
            title = title[:45] + "..."
        return f"{candidate.clip_id:>6s} ({badge}) {title}"

    @staticmethod
    def duration_text(candidate: ClipCandidate) -> str:
        return f"[{float(candidate.duration):.0f}s]"

    def refresh_candidate(self, candidate: ClipCandidate) -> None:
        self.query_one(".clip-main", Label).update(self.label_text(candidate))
        self.query_one(".clip-duration", Label).update(self.duration_text(candidate))


class ReviewScreen(Screen):
    BINDINGS = [
        Binding("j,down", "cursor_down", show=False, priority=True),
        Binding("k,up", "cursor_up", show=False, priority=True),
        Binding("1", "mark_group1", "Group 1"),
        Binding("2", "mark_group2", "Group 2"),
        Binding("x", "mark_skipped", "Skip"),
        Binding("u", "undo_skip", "Undo skip"),
        Binding("d", "duplicate_clip", "Duplicate"),
        Binding("r", "rename_title", "Rename"),
        Binding("ctrl+shift+x", "bulk_skip_above", "Skip above"),
        Binding("space,enter", "play_preview", "Play"),
        Binding(
            "left_square_bracket,[",
            "nudge_start_down",
            "Start -",
            priority=True,
        ),
        Binding(
            "right_square_bracket,]",
            "nudge_start_up",
            "Start +",
            priority=True,
        ),
        Binding("o", "set_trim_offsets", "Trim offsets"),
        Binding(
            "left_curly_bracket,{",
            "nudge_end_down",
            "End -",
            priority=True,
        ),
        Binding(
            "right_curly_bracket,}",
            "nudge_end_up",
            "End +",
            priority=True,
        ),
        Binding("e", "export_clip", "Export"),
        # Binding("f", "cycle_filter", "Filter"),
        Binding("f", "open_filter_modal", "Filter picker"),
        Binding("g", "jump_to_index_prompt", "Jump index"),
        Binding("ctrl+g", "generate_filter_waveforms", "Pregen waveforms"),
        Binding("h", "toggle_hide_processed", "Hide processed"),
        Binding("ctrl+s", "save_session", "Save"),
        Binding("q", "app.quit", "Quit"),
        Binding("comma", "open_fine_start_tab", show=False, priority=True),
        Binding("period,full_stop", "open_fine_end_tab", show=False, priority=True),
        Binding("escape", "close_fine_tab", show=False),
    ]

    DEFAULT_CSS = """
    ReviewScreen {
        layout: vertical;
    }

    #filter-tabs {
        width: 100%;
    }

    #main-pane {
        height: 1fr;
    }

    #clip-list {
        width: 40%;
        border: solid $primary;
    }

    #clip-list ListItem.processed-hidden,
    #clip-list ListItem.filter-hidden {
        display: none;
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
        self.filter_mode = "unsorted"
        self.hide_processed = False
        self._pinned_processed_visible: set[str] = set()
        self._processed_hidden: set[str] = set()
        self.filtered_clip_ids: list[str] = []
        self._waveform_cache_dir = (
            Path("tmp") / "waveform" / session.audio.stem
        )
        self._skip_undo_stack: list[tuple[str, ClipStatus]] = []
        self._waveform_bulk_progress: str | None = None
        self._persist_debounce_timer: Timer | None = None
        self._export_preview_preload_generation = 0
        self._export_preview_preload_key: tuple[object, ...] | None = None
        self._export_preview_preload: ExportPreviewArtifacts | None = None
        self._export_preview_preload_error: str | None = None
        self._export_preview_preload_ready = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterTabs(
            *(
                Tab(FILTER_BAR_LABELS[mode], id=mode)
                for mode in FILTER_ORDER
            ),
            id="filter-tabs",
            active=self.filter_mode,
        )
        with Horizontal(id="main-pane"):
            yield ListView(id="clip-list")
            yield ClipDetailPanel(
                self.session,
                self._waveform_cache_dir,
                id="detail-panel",
                on_detail_updated=self._refresh_status_bars,
            )
        # yield Static(self._help_text(), id="help-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status_bars()
        self._rebuild_list(select_first=True)

    def _header_title_text(self) -> str:
        total = len(self.session.candidates)
        position = ""
        current = self._current_candidate()
        if current is not None:
            try:
                pos = self.filtered_clip_ids.index(current.clip_id) + 1
                position = f"  {pos}/{len(self.filtered_clip_ids)}"
            except ValueError:
                pass
        return f"{self.session.audio.name}{position}  ({total} clips)"

    def _header_sub_title_text(self) -> str:
        hide_label = "on" if self.hide_processed else "off"
        parts = [f"Hide processed: {hide_label}"]
        if self._waveform_bulk_progress is not None:
            parts.append(self._waveform_bulk_progress)
        return "  ".join(parts)

    def _sync_filter_tabs(self) -> None:
        tabs = self.query_one("#filter-tabs", Tabs)
        if tabs.active != self.filter_mode:
            tabs.active = self.filter_mode

    @on(Tabs.TabActivated, "#filter-tabs")
    def on_filter_tab_activated(self, event: Tabs.TabActivated) -> None:
        mode = event.tab.id
        if mode is None or mode not in FILTER_ORDER or mode == self.filter_mode:
            return
        self.filter_mode = mode
        self._reset_processed_visibility_state()
        self._apply_filter_to_items(select_first=True)

    def _reset_processed_visibility_state(self) -> None:
        self._pinned_processed_visible.clear()
        self._processed_hidden.clear()

    def _detail_panel(self) -> ClipDetailPanel:
        return self.query_one("#detail-panel", ClipDetailPanel)

    def action_open_fine_start_tab(self) -> None:
        candidate = self._current_candidate()
        if candidate is not None:
            self._detail_panel().open_fine_start_tab(candidate)

    def action_close_fine_tab(self) -> None:
        self._detail_panel().close_fine_tab(self._current_candidate())

    def action_open_fine_end_tab(self) -> None:
        candidate = self._current_candidate()
        if candidate is not None:
            self._detail_panel().open_fine_end_tab(candidate)

    def _update_detail(
        self,
        clip_id: str,
        *,
        debounce_waveform: bool = False,
        waveform_regen_on_debounce: bool = True,
        force_waveform_regen: bool = False,
    ) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            self._detail_panel().clear_detail()
            return
        self._detail_panel().update_detail(
            candidate,
            debounce_waveform=debounce_waveform,
            waveform_regen_on_debounce=waveform_regen_on_debounce,
            force_waveform_regen=force_waveform_regen,
        )

    def _clear_detail(self) -> None:
        self._detail_panel().clear_detail()

    def _help_text(self) -> str:
        return (
            "j/k nav  1/2 group  x skip  u undo skip  Ctrl+Shift+X skip above  "
            "f filter  Ctrl+Shift+F filter picker  h hide processed  Ctrl+S save  q quit"
        )

    def _refresh_status_bars(self) -> None:
        self.title = self._header_title_text()
        self.sub_title = self._header_sub_title_text()

    def _candidate_matches_filter(self, candidate: ClipCandidate) -> bool:
        if self.filter_mode == "unsorted":
            if candidate.status != "pending":
                return False
        elif self.filter_mode != "all" and candidate.status != self.filter_mode:
            return False
        return True

    def _item_would_be_visible(self, candidate: ClipCandidate) -> bool:
        if candidate.clip_id in self._processed_hidden:
            return False
        if candidate.clip_id in self._pinned_processed_visible:
            return True
        return self._candidate_matches_filter(candidate)

    def _visible_candidates(self) -> list[ClipCandidate]:
        return [
            candidate
            for candidate in self.session.candidates
            if self._item_would_be_visible(candidate)
        ]

    def _clip_id_after_removing(self, visible_index: int) -> str | None:
        if visible_index + 1 < len(self.filtered_clip_ids):
            return self.filtered_clip_ids[visible_index + 1]
        if visible_index > 0:
            return self.filtered_clip_ids[visible_index - 1]
        return None

    @staticmethod
    def _is_visible_item(item: ListItem) -> bool:
        return (
            isinstance(item, ClipListItem)
            and FILTER_HIDDEN_CLASS not in item.classes
            and PROCESSED_HIDDEN_CLASS not in item.classes
        )

    def _sync_item_visibility(self, item: ClipListItem) -> None:
        candidate = self.session.get_candidate(item.candidate_id)
        visible = candidate is not None and self._item_would_be_visible(candidate)
        if visible:
            item.remove_class(FILTER_HIDDEN_CLASS)
            item.remove_class(PROCESSED_HIDDEN_CLASS)
        else:
            item.add_class(FILTER_HIDDEN_CLASS)
            if candidate is not None and candidate.clip_id in self._processed_hidden:
                item.add_class(PROCESSED_HIDDEN_CLASS)
            else:
                item.remove_class(PROCESSED_HIDDEN_CLASS)

    def _first_visible_dom_index(self, list_view: ListView) -> int | None:
        for index, item in enumerate(list_view.children):
            if self._is_visible_item(item):
                return index
        return None

    def _apply_filter_to_items(
        self,
        *,
        select_first: bool = False,
        preserve_clip_id: str | None = None,
    ) -> None:
        list_view = self.query_one("#clip-list", ListView)
        for item in list_view.children:
            if isinstance(item, ClipListItem):
                self._sync_item_visibility(item)
        self._sync_filtered_clip_ids(list_view)
        self._refresh_status_bars()

        if preserve_clip_id is not None:
            for index, item in enumerate(list_view.children):
                if (
                    isinstance(item, ClipListItem)
                    and item.candidate_id == preserve_clip_id
                    and self._is_visible_item(item)
                ):
                    list_view.index = index
                    self._update_detail(preserve_clip_id)
                    return
            if self.filtered_clip_ids:
                first_dom = self._first_visible_dom_index(list_view)
                if first_dom is not None:
                    list_view.index = first_dom
                    first_item = list_view.children[first_dom]
                    if isinstance(first_item, ClipListItem):
                        self._update_detail(first_item.candidate_id)
                return

        if select_first:
            first_dom = self._first_visible_dom_index(list_view)
            if first_dom is not None:
                list_view.index = first_dom
                first_item = list_view.children[first_dom]
                if isinstance(first_item, ClipListItem):
                    self._update_detail(first_item.candidate_id)
            else:
                list_view.index = None
                self._clear_detail()

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

    def _sync_filtered_clip_ids(self, list_view: ListView) -> None:
        self.filtered_clip_ids = [
            item.candidate_id
            for item in list_view.children
            if self._is_visible_item(item)
        ]

    def _select_after_hide(
        self,
        list_view: ListView,
        hidden_dom_index: int,
        next_clip_id: str | None,
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
        self._refresh_status_bars()
        if next_clip_id is not None:
            self._update_detail(next_clip_id)
        else:
            self._clear_detail()

    def _find_list_item(self, clip_id: str) -> ClipListItem | None:
        list_view = self.query_one("#clip-list", ListView)
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_id == clip_id:
                return item
        return None

    def _restore_skipped(
        self,
        clip_id: str,
        previous_status: ClipStatus,
    ) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        candidate.status = previous_status
        list_view = self.query_one("#clip-list", ListView)
        item = self._find_list_item(clip_id)
        if item is None:
            return
        item.remove_class(PROCESSED_HIDDEN_CLASS)
        self._pinned_processed_visible.discard(clip_id)
        self._processed_hidden.discard(clip_id)
        item.refresh_candidate(candidate)
        self._sync_item_visibility(item)
        self._sync_filtered_clip_ids(list_view)
        list_view.index = list_view.children.index(item)
        self._update_detail(clip_id)

    def _hide_processed_bulk(
        self,
        list_view: ListView,
        clip_ids: list[str],
        next_clip_id: str | None,
    ) -> None:
        hidden_dom_index = list_view.index or 0
        for clip_id in clip_ids:
            self._processed_hidden.add(clip_id)
            candidate = self.session.get_candidate(clip_id)
            if candidate is not None:
                self._refresh_list_item(candidate)
        self._select_after_hide(list_view, hidden_dom_index, next_clip_id)

    def _preserve_after_status_change(
        self,
        list_view: ListView,
        dom_index: int | None,
    ) -> str | None:
        if dom_index is None:
            return None
        try:
            visible_index = self._visible_position(list_view, dom_index)
        except IndexError:
            return None
        return self._clip_id_after_removing(visible_index)

    def _apply_status_change_visibility(
        self,
        candidate: ClipCandidate,
        list_view: ListView,
        *,
        dom_index: int | None,
        preserve_clip_id: str | None,
        move_selection: bool = True,
    ) -> None:
        clip_id = candidate.clip_id
        if preserve_clip_id is None:
            preserve_clip_id = self._preserve_after_status_change(
                list_view, dom_index
            )

        if self.hide_processed:
            self._pinned_processed_visible.discard(clip_id)
            self._processed_hidden.add(clip_id)
        else:
            self._pinned_processed_visible.add(clip_id)
            self._processed_hidden.discard(clip_id)

        self._refresh_list_item(candidate)

        if not move_selection:
            return

        if dom_index is None:
            item = self._find_list_item(clip_id)
            if item is None:
                return
            dom_index = list_view.children.index(item)

        if preserve_clip_id is None:
            preserve_clip_id = self._preserve_after_status_change(
                list_view, dom_index
            )

        self._select_after_hide(list_view, dom_index, preserve_clip_id)

    @work(exclusive=True)
    async def _rebuild_list(
        self,
        select_first: bool = False,
        preserve_clip_id: str | None = None,
    ) -> None:
        list_view = self.query_one("#clip-list", ListView)
        expected_ids = {candidate.clip_id for candidate in self.session.candidates}
        existing_ids = {
            item.candidate_id
            for item in list_view.children
            if isinstance(item, ClipListItem)
        }
        if expected_ids != existing_ids:
            await list_view.clear()
            items = [ClipListItem(candidate) for candidate in self.session.candidates]
            if items:
                await list_view.mount(*items)
        self._apply_filter_to_items(
            select_first=select_first,
            preserve_clip_id=preserve_clip_id,
        )

    @work(exclusive=True)
    async def _insert_duplicate_item(
        self,
        source_clip_id: str,
        duplicate: ClipCandidate,
    ) -> None:
        list_view = self.query_one("#clip-list", ListView)
        insert_after: ClipListItem | None = None
        for item in list_view.children:
            if not isinstance(item, ClipListItem):
                continue
            candidate = self.session.get_candidate(item.candidate_id)
            if candidate is not None and candidate.index == duplicate.index:
                insert_after = item

        if insert_after is None:
            insert_after = self._find_list_item(source_clip_id)

        new_item = ClipListItem(duplicate)
        self._sync_item_visibility(new_item)
        if insert_after is not None:
            await list_view.mount(new_item, after=insert_after)
        else:
            await list_view.mount(new_item)
        self._sync_filtered_clip_ids(list_view)
        self._refresh_status_bars()

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
        return self.session.get_candidate(item.candidate_id)

    @on(ListView.Selected)
    def on_list_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ClipListItem):
            panel = self._detail_panel()
            panel.stop_playback()
            panel.switch_to_basic_tab()
            self._update_detail(item.candidate_id)

    def _refresh_list_item(self, candidate: ClipCandidate) -> None:
        list_view = self.query_one("#clip-list", ListView)
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_id == candidate.clip_id:
                item.refresh_candidate(candidate)
                self._sync_item_visibility(item)
                self._sync_filtered_clip_ids(list_view)
                self._refresh_status_bars()
                break

    def _persist(self) -> None:
        self.session.save()

    def _persist_debounced(self, *, delay_seconds: float = 0.5) -> None:
        if self._persist_debounce_timer is not None:
            self._persist_debounce_timer.stop()
            self._persist_debounce_timer = None

        def save_session() -> None:
            self._persist_debounce_timer = None
            self._persist()

        self._persist_debounce_timer = self.set_timer(
            delay_seconds,
            save_session,
            name="persist-debounce",
        )

    def _restore_list_index_if_drifted(self, pinned_index: int | None) -> None:
        if pinned_index is None:
            return
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index != pinned_index:
            list_view.index = pinned_index

    def _set_status(self, status: ClipStatus) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        list_view = self.query_one("#clip-list", ListView)
        dom_index = list_view.index
        preserve = self._preserve_after_status_change(list_view, dom_index)
        previous_status = candidate.status
        if status == previous_status:
            return
        if status == "skipped":
            self._skip_undo_stack.append((candidate.clip_id, previous_status))
        candidate.status = status
        self._apply_status_change_visibility(
            candidate,
            list_view,
            dom_index=dom_index,
            preserve_clip_id=preserve,
        )
        self._persist()

    def action_cursor_down(self) -> None:
        panel = self._detail_panel()
        panel.stop_playback()
        panel.switch_to_basic_tab()
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        next_dom = self._next_visible_dom_index(list_view, list_view.index)
        if next_dom is None:
            for index, item in enumerate(list_view.children):
                if self._is_visible_item(item):
                    next_dom = index
                    break
        if next_dom is None:
            return
        list_view.index = next_dom
        item = list_view.children[next_dom]
        if isinstance(item, ClipListItem):
            self._update_detail(item.candidate_id)

    def action_cursor_up(self) -> None:
        panel = self._detail_panel()
        panel.stop_playback()
        panel.switch_to_basic_tab()
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        next_dom = self._next_visible_dom_index(
            list_view, list_view.index, forward=False
        )
        if next_dom is None:
            for index in range(len(list_view.children) - 1, -1, -1):
                if self._is_visible_item(list_view.children[index]):
                    next_dom = index
                    break
        if next_dom is None:
            return
        list_view.index = next_dom
        item = list_view.children[next_dom]
        if isinstance(item, ClipListItem):
            self._update_detail(item.candidate_id)

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
        clip_id, previous_status = self._skip_undo_stack.pop()
        candidate = self.session.get_candidate(clip_id)
        if candidate is None or candidate.status != "skipped":
            self.notify("Nothing to undo")
            return
        self._restore_skipped(clip_id, previous_status)
        self._persist()
        self.notify(f"Restored #{clip_id}")

    def action_duplicate_clip(self) -> None:
        current = self._current_candidate()
        if current is None:
            return
        source_clip_id = current.clip_id
        duplicate = self.session.duplicate_candidate(source_clip_id)
        if duplicate is None:
            return
        self._persist()
        self._insert_duplicate_item(source_clip_id, duplicate)
        self.notify(f"Duplicated #{source_clip_id} → #{duplicate.clip_id}")

    def action_rename_title(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        clip_id = candidate.clip_id
        self.app.push_screen(
            EditTitleModal(candidate.title, clip_id),
            lambda title: self._after_rename_title(clip_id, title),
        )

    def _after_rename_title(self, clip_id: str, title: str | None) -> None:
        if title is None:
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        if candidate.title == title:
            return
        candidate.title = title
        candidate.last_export_title = title
        self._refresh_list_item(candidate)
        self._update_detail(candidate.clip_id)
        self._persist()
        self.notify(f"Renamed #{clip_id}")

    def action_bulk_skip_above(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None or not self.filtered_clip_ids:
            return
        dom_index = list_view.index
        visible_index = self._visible_position(list_view, dom_index)
        preserve = self._clip_id_after_removing(visible_index)
        clip_ids_to_skip = self.filtered_clip_ids[: visible_index + 1]
        restored_before_skip = [
            (clip_id, "pending")
            for clip_id in clip_ids_to_skip
            if (candidate := self.session.get_candidate(clip_id)) is not None
            and candidate.status == "pending"
        ]
        count = self.session.bulk_skip(clip_ids_to_skip)
        for entry in restored_before_skip:
            self._skip_undo_stack.append(entry)
        self._persist()
        if self.hide_processed and count > 0:
            self._hide_processed_bulk(list_view, clip_ids_to_skip, preserve)
        else:
            for clip_id in clip_ids_to_skip:
                candidate = self.session.get_candidate(clip_id)
                if candidate is None:
                    continue
                self._pinned_processed_visible.add(clip_id)
                self._refresh_list_item(candidate)
            preserve = self._preserve_after_status_change(list_view, dom_index)
            if preserve is not None:
                self._select_after_hide(list_view, dom_index, preserve)
            else:
                current = self._current_candidate()
                if current is not None:
                    self._detail_panel().update_clip_status(
                        ClipDetailPanel.clip_status_text(current)
                    )
        self.notify(f"Skipped {count} unmarked clips (current and above)")

    def action_cycle_filter(self) -> None:
        self._cycle_filter(direction=1)

    def action_open_filter_modal(self) -> None:
        self.app.push_screen(
            FilterSelectionModal(self.filter_mode),
            self._handle_filter_selection,
        )

    def _handle_filter_selection(self, filter_mode: str | None) -> None:
        if filter_mode is None or filter_mode == self.filter_mode:
            return
        self.filter_mode = filter_mode
        self._reset_processed_visibility_state()
        self._sync_filter_tabs()
        self._apply_filter_to_items(select_first=True)

    @staticmethod
    def _parse_clip_index(clip_id: str) -> int | None:
        try:
            return int(clip_id)
        except ValueError:
            return None

    def _find_target_clip_id(self, requested_index: int) -> tuple[str, bool] | None:
        if not self.filtered_clip_ids:
            return None
        parsed: list[tuple[str, int]] = []
        for clip_id in self.filtered_clip_ids:
            parsed_index = self._parse_clip_index(clip_id)
            if parsed_index is None:
                continue
            parsed.append((clip_id, parsed_index))
        if not parsed:
            return None
        for clip_id, value in parsed:
            if value == requested_index:
                return clip_id, True
        nearest_clip_id, _nearest_value = min(
            parsed,
            key=lambda pair: (abs(pair[1] - requested_index), pair[1]),
        )
        return nearest_clip_id, False

    def _jump_to_clip_id(self, clip_id: str) -> bool:
        list_view = self.query_one("#clip-list", ListView)
        for index, item in enumerate(list_view.children):
            if (
                isinstance(item, ClipListItem)
                and item.candidate_id == clip_id
                and self._is_visible_item(item)
            ):
                list_view.index = index
                panel = self._detail_panel()
                panel.stop_playback()
                panel.switch_to_basic_tab()
                self._update_detail(clip_id)
                return True
        return False

    def _handle_jump_to_index(self, index_value: str | None) -> None:
        if index_value is None:
            return
        value = index_value.strip()
        if not value:
            self.notify("Index cannot be empty", severity="warning")
            return
        try:
            requested_index = int(value)
        except ValueError:
            self.notify("Index must be an integer", severity="warning")
            return
        target = self._find_target_clip_id(requested_index)
        if target is None:
            self.notify("No clips available in current filter", severity="warning")
            return
        target_clip_id, exact = target
        if not self._jump_to_clip_id(target_clip_id):
            self.notify("Could not jump to the requested clip", severity="error")
            return
        if exact:
            self.notify(f"Jumped to #{target_clip_id}")
        else:
            self.notify(
                f"No #{requested_index} in current filter; jumped to nearest #{target_clip_id}"
            )

    def action_jump_to_index_prompt(self) -> None:
        self.app.push_screen(
            JumpToIndexModal(),
            self._handle_jump_to_index,
        )

    def _cycle_filter(self, *, direction: int) -> None:
        current_idx = FILTER_ORDER.index(self.filter_mode)
        self.filter_mode = FILTER_ORDER[
            (current_idx + direction) % len(FILTER_ORDER)
        ]
        self._reset_processed_visibility_state()
        self._sync_filter_tabs()
        self._apply_filter_to_items(select_first=True)

    def action_generate_filter_waveforms(self) -> None:
        if self._waveform_bulk_progress is not None:
            self.notify("Waveform pre-generation already running.", severity="warning")
            return
        candidates = list(self._visible_candidates())
        if not candidates:
            self.notify("No clips in current filter.")
            return
        pending = [
            candidate
            for candidate in candidates
            if not self._detail_panel()
            .waveform_cache_path(candidate, suffix=".png")
            .exists()
        ]
        cached = len(candidates) - len(pending)
        if not pending:
            self.notify(
                f"All {len(candidates)} clip waveforms already cached."
            )
            return
        self.notify(
            f"Generating {len(pending)} waveforms "
            f"({cached} already cached)..."
        )
        self._run_bulk_waveform_generation(candidates)

    def action_toggle_hide_processed(self) -> None:
        self.hide_processed = not self.hide_processed
        if self.hide_processed:
            self._pinned_processed_visible.clear()
        else:
            self._processed_hidden.clear()
        current = self._current_candidate()
        preserve = current.clip_id if current is not None else None
        self._apply_filter_to_items(preserve_clip_id=preserve)
        state = "hidden" if self.hide_processed else "shown"
        self.notify(f"Processed clips {state}")

    def action_save_session(self) -> None:
        self._persist()
        self.notify("Session saved.")

    def action_nudge_start_down(self) -> None:
        panel = self._detail_panel()
        if panel.is_fine_end_tab():
            self._nudge_end(-FINE_NUDGE_FINE)
        elif panel.is_fine_start_tab():
            self._nudge_start(-FINE_NUDGE_FINE)
        else:
            self._nudge_start(-FINE_NUDGE_COARSE)

    def action_nudge_start_up(self) -> None:
        panel = self._detail_panel()
        if panel.is_fine_end_tab():
            self._nudge_end(FINE_NUDGE_FINE)
        elif panel.is_fine_start_tab():
            self._nudge_start(FINE_NUDGE_FINE)
        else:
            self._nudge_start(FINE_NUDGE_COARSE)

    def action_set_trim_offsets(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        clip_id = candidate.clip_id
        self.app.push_screen(
            StartOffsetModal(
                candidate.start_offset_seconds(),
                candidate.end_offset_seconds(),
            ),
            lambda offsets: self._after_trim_offsets(clip_id, offsets),
        )

    def _after_trim_offsets(
        self, clip_id: str, offsets: TrimOffsets | None
    ) -> None:
        if offsets is None:
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self.session.set_trim_offsets(
            clip_id, offsets.start, offsets.end
        )
        self._update_detail(
            clip_id,
            debounce_waveform=True,
            force_waveform_regen=True,
        )
        self._persist()
        self.notify(
            f"Offsets set: start {offsets.start:+.3f}s, end {offsets.end:+.3f}s from original"
        )

    def action_nudge_end_down(self) -> None:
        panel = self._detail_panel()
        if panel.is_fine_start_tab():
            self._nudge_start(-FINE_NUDGE_COARSE)
        elif panel.is_fine_end_tab():
            self._nudge_end(-FINE_NUDGE_COARSE)
        else:
            self._nudge_end(-FINE_NUDGE_COARSE)

    def action_nudge_end_up(self) -> None:
        panel = self._detail_panel()
        if panel.is_fine_start_tab():
            self._nudge_start(FINE_NUDGE_COARSE)
        elif panel.is_fine_end_tab():
            self._nudge_end(FINE_NUDGE_COARSE)
        else:
            self._nudge_end(FINE_NUDGE_COARSE)

    def _nudge_start(self, delta: float) -> None:
        if self._detail_panel().is_waveform_image_updating():
            return
        candidate = self._current_candidate()
        if candidate is None:
            return
        clip_id = candidate.clip_id
        list_view = self.query_one("#clip-list", ListView)
        pinned_index = list_view.index
        self.session.nudge_start(clip_id, delta)
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._detail_panel().update_after_nudge(candidate)
        self.call_after_refresh(self._restore_list_index_if_drifted, pinned_index)
        self._persist_debounced()

    def _nudge_end(self, delta: float) -> None:
        if self._detail_panel().is_waveform_image_updating():
            return
        candidate = self._current_candidate()
        if candidate is None:
            return
        clip_id = candidate.clip_id
        list_view = self.query_one("#clip-list", ListView)
        pinned_index = list_view.index
        self.session.nudge_end(clip_id, delta)
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self._detail_panel().update_after_nudge(candidate)
        self.call_after_refresh(self._restore_list_index_if_drifted, pinned_index)
        self._persist_debounced()

    def action_play_preview(self) -> None:
        panel = self._detail_panel()
        if panel.is_playing():
            panel.stop_playback()
            return
        candidate = self._current_candidate()
        if candidate is None:
            return
        panel.play_preview(candidate)

    def action_export_clip(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self._detail_panel().stop_playback()
        clip_id = candidate.clip_id
        initial_options: ExportOptions | None = None
        mode = candidate.last_export_mode
        if mode in ("as_is", "trim_edges", "trim_all"):
            kwargs: dict[str, object] = {"mode": mode}
            if candidate.last_export_start_threshold_db is not None:
                kwargs["start_threshold_db"] = candidate.last_export_start_threshold_db
            if candidate.last_export_stop_threshold_db is not None:
                kwargs["stop_threshold_db"] = candidate.last_export_stop_threshold_db
            initial_options = ExportOptions(**kwargs)  # type: ignore[arg-type]
        self._open_export_mode_modal(clip_id, initial_options)

    def _invalidate_export_preview_preload(self) -> None:
        self._export_preview_preload_generation += 1
        self._export_preview_preload_key = None
        self._export_preview_preload = None
        self._export_preview_preload_error = None
        self._export_preview_preload_ready.clear()

    def _start_export_preview_preload(self, clip_id: str) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        options = DEFAULT_PRELOAD_EXPORT_OPTIONS
        preview_title = default_export_title(candidate)
        generation = self._export_preview_preload_generation + 1
        self._export_preview_preload_generation = generation
        self._export_preview_preload_key = export_preview_key(
            candidate, options, preview_title
        )
        self._export_preview_preload = None
        self._export_preview_preload_error = None
        self._export_preview_preload_ready.clear()
        self._run_export_preview_preload(clip_id, generation)

    @work(thread=True, exclusive=True, group="export-preview-preload")
    def _run_export_preview_preload(self, clip_id: str, generation: int) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        try:
            artifacts = build_export_preview_artifacts(
                self.session.audio,
                candidate,
                DEFAULT_PRELOAD_EXPORT_OPTIONS,
            )
        except Exception as exc:
            if generation != self._export_preview_preload_generation:
                return
            self._export_preview_preload_error = str(exc)
            self._export_preview_preload_ready.set()
            return
        if generation != self._export_preview_preload_generation:
            return
        self._export_preview_preload = artifacts
        self._export_preview_preload_ready.set()

    def _consume_export_preview_preload(
        self,
        candidate: ClipCandidate,
        options: ExportOptions,
    ) -> ExportPreviewArtifacts | None:
        preview_title = default_export_title(candidate)
        key = export_preview_key(candidate, options, preview_title)
        if self._export_preview_preload_key != key:
            return None
        self._export_preview_preload_ready.wait()
        if self._export_preview_preload_key != key:
            return None
        if self._export_preview_preload_error is not None:
            return None
        return self._export_preview_preload

    def _open_export_mode_modal(
        self, clip_id: str, initial_options: ExportOptions | None
    ) -> None:
        self._start_export_preview_preload(clip_id)
        self.app.push_screen(
            ExportModeModal(initial_options=initial_options),
            lambda options: self._after_export_mode(clip_id, options),
        )

    def _after_export_mode(
        self, clip_id: str, options: ExportOptions | None
    ) -> None:
        if options is None:
            self._invalidate_export_preview_preload()
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        self.app.push_screen(
            ExportPreviewModal(
                self.session.audio,
                candidate,
                options,
                try_preloaded=lambda: self._consume_export_preview_preload(
                    candidate, options
                ),
            ),
            lambda result: self._after_export_preview(clip_id, options, result),
        )

    def _after_export_preview(
        self,
        clip_id: str,
        options: ExportOptions,
        result: ExportConfirm | bool | None,
    ) -> None:
        if result is False:
            # Esc on the preview reopens the export mode picker so the user
            # can tweak settings without restarting the export flow.
            candidate = self.session.get_candidate(clip_id)
            if candidate is None:
                return
            self._open_export_mode_modal(clip_id, options)
            return
        if result is None:
            return
        self._start_export(clip_id, options, result)

    def _start_export(
        self,
        clip_id: str,
        export_options: ExportOptions,
        confirm: ExportConfirm,
    ) -> None:
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        title = confirm.title
        candidate.title = title
        candidate.last_export_title = title
        candidate.last_export_mode = export_options.mode
        candidate.last_export_start_threshold_db = export_options.start_threshold_db
        candidate.last_export_stop_threshold_db = export_options.stop_threshold_db
        self._refresh_list_item(candidate)
        self._update_detail(candidate.clip_id)
        self.run_export(
            candidate,
            title,
            export_options,
            confirm.preview_path,
            confirm.wait_for_preview_path,
        )

    @work(thread=True, exclusive=True)
    def run_export(
        self,
        candidate: ClipCandidate,
        export_title: str,
        export_options: ExportOptions,
        preview_path: Path | None = None,
        wait_for_preview_path: Callable[[], Path | None] | None = None,
    ) -> None:
        try:
            if preview_path is None and wait_for_preview_path is not None:
                self.app.call_from_thread(
                    self.notify,
                    "Finishing preview…",
                    severity="information",
                )
                preview_path = wait_for_preview_path()
            if preview_path is not None and preview_path.exists():
                output = ffmpeg.publish_prebuilt_clip(
                    preview_path,
                    self.session.audio,
                    candidate,
                    self.session.clip_dir,
                    export_title,
                )
            else:
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
        list_view = self.query_one("#clip-list", ListView)
        item = self._find_list_item(candidate.clip_id)
        dom_index = (
            list_view.children.index(item)
            if item is not None
            else None
        )
        preserve = (
            self._preserve_after_status_change(list_view, dom_index)
            if self.hide_processed
            else None
        )
        self._apply_status_change_visibility(
            candidate,
            list_view,
            dom_index=dom_index,
            preserve_clip_id=preserve,
            move_selection=self.hide_processed,
        )
        self._detail_panel().update_clip_status(
            f"{ClipDetailPanel.clip_status_text(candidate)}\nSaved: {output}"
        )
        self._persist()
        self.notify(f"Exported {output.name}")

    @work(thread=True, exclusive=True, group="bulk-waveform")
    def _run_bulk_waveform_generation(
        self, candidates: list[ClipCandidate]
    ) -> None:
        total = len(candidates)
        generated = 0
        cached = 0
        failed = 0
        panel = self._detail_panel()
        try:
            for index, candidate in enumerate(candidates, 1):
                target = panel.waveform_cache_path(candidate, suffix=".png")
                if target.exists():
                    cached += 1
                else:
                    try:
                        panel.generate_waveform_file(candidate)
                        generated += 1
                    except Exception:
                        failed += 1
                self._waveform_bulk_progress = (
                    f"Pregen waveforms: {index}/{total}"
                )
                self.app.call_from_thread(self._refresh_status_bars)
        finally:
            self._waveform_bulk_progress = None
            self.app.call_from_thread(self._refresh_status_bars)
        self.app.call_from_thread(
            self.notify,
            f"Waveform pre-generation done: "
            f"{generated} generated, {cached} cached, {failed} failed.",
        )
