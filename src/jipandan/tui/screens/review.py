import threading
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, ListView, Tab, Tabs

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, ClipStatus, Session
from jipandan.core.ffmpeg import ExportOptions
from jipandan.tui.clip_list import (
    ClipListController,
    ClipListItem,
    FilterTabs,
)
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
from jipandan.tui.waveform_service import FINE_NUDGE_COARSE, FINE_NUDGE_FINE, WaveformService
from jipandan.tui.widgets.detail_panel import ClipDetailPanel

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
        self._clip_list = ClipListController(
            session,
            on_selection_changed=self._on_clip_selection_changed,
            on_list_state_changed=self._refresh_status_bars,
        )
        self._waveform_cache_dir = (
            Path("tmp") / "waveform" / session.audio.stem
        )
        self._waveform_service: WaveformService | None = None
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
            active=self._clip_list.filter_mode,
        )
        with Horizontal(id="main-pane"):
            yield ListView(id="clip-list")
            yield ClipDetailPanel(
                self.session,
                self._waveform_cache_dir,
                id="detail-panel",
                on_detail_updated=self._refresh_status_bars,
                on_nudge=self._on_detail_nudge,
            )
        # yield Static(self._help_text(), id="help-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._waveform_service = self._detail_panel().waveform_service
        self._refresh_status_bars()
        self._rebuild_list(select_first=True)

    def _list_view(self) -> ListView:
        return self.query_one("#clip-list", ListView)

    def _on_clip_selection_changed(self, clip_id: str | None) -> None:
        if clip_id is None:
            self._clear_detail()
        else:
            self._update_detail(clip_id)

    def _header_title_text(self) -> str:
        total = len(self.session.candidates)
        position = ""
        current = self._current_candidate()
        if current is not None:
            try:
                pos = self._clip_list.filtered_clip_ids.index(current.clip_id) + 1
                position = f"  {pos}/{len(self._clip_list.filtered_clip_ids)}"
            except ValueError:
                pass
        return f"{self.session.audio.name}{position}  ({total} clips)"

    def _header_sub_title_text(self) -> str:
        hide_label = "on" if self._clip_list.hide_processed else "off"
        parts = [f"Hide processed: {hide_label}"]
        if self._waveform_bulk_progress is not None:
            parts.append(self._waveform_bulk_progress)
        return "  ".join(parts)

    def _sync_filter_tabs(self) -> None:
        tabs = self.query_one("#filter-tabs", Tabs)
        if tabs.active != self._clip_list.filter_mode:
            tabs.active = self._clip_list.filter_mode

    @on(Tabs.TabActivated, "#filter-tabs")
    def on_filter_tab_activated(self, event: Tabs.TabActivated) -> None:
        mode = event.tab.id
        if mode is None or mode not in FILTER_ORDER or mode == self._clip_list.filter_mode:
            return
        self._set_filter_mode(mode)

    def _set_filter_mode(self, mode: str) -> None:
        current = self._current_candidate()
        change = self._clip_list.prepare_filter_mode_change(
            mode,
            current.clip_id if current is not None else None,
        )
        if change is None:
            return
        self._sync_filter_tabs()
        self._clip_list.apply_filter_to_items(
            self._list_view(),
            select_first=change.select_first,
            preserve_clip_id=change.preserve_clip_id,
        )

    def _detail_panel(self) -> ClipDetailPanel:
        return self.query_one("#detail-panel", ClipDetailPanel)

    def _waveform(self) -> WaveformService:
        if self._waveform_service is None:
            raise RuntimeError("WaveformService is not initialized until mount")
        return self._waveform_service

    def _on_detail_nudge(self, edge: str, delta: float) -> None:
        if edge == "start":
            self._nudge_start(delta)
        else:
            self._nudge_end(delta)

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

    @work(exclusive=True)
    async def _rebuild_list(
        self,
        select_first: bool = False,
        preserve_clip_id: str | None = None,
    ) -> None:
        list_view = self._list_view()
        if self._clip_list.needs_rebuild(list_view):
            await list_view.clear()
            items = self._clip_list.build_items()
            if items:
                await list_view.mount(*items)
        self._clip_list.apply_filter_to_items(
            list_view,
            select_first=select_first,
            preserve_clip_id=preserve_clip_id,
        )

    @work(exclusive=True)
    async def _insert_duplicate_item(
        self,
        source_clip_id: str,
        duplicate: ClipCandidate,
    ) -> None:
        list_view = self._list_view()
        insert_after = self._clip_list.find_insert_after(
            list_view,
            source_clip_id=source_clip_id,
            duplicate=duplicate,
        )
        new_item = self._clip_list.prepare_duplicate_item(duplicate)
        if insert_after is not None:
            await list_view.mount(new_item, after=insert_after)
        else:
            await list_view.mount(new_item)
        self._clip_list.after_duplicate_mounted(list_view)

    def _current_candidate(self) -> ClipCandidate | None:
        return self._clip_list.current_candidate(self._list_view())

    @on(ListView.Selected)
    def on_list_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ClipListItem):
            panel = self._detail_panel()
            panel.stop_playback()
            panel.switch_to_basic_tab()
            self._update_detail(item.candidate_id)

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
        self._clip_list.restore_list_index_if_drifted(
            self._list_view(), pinned_index
        )

    def _set_status(self, status: ClipStatus) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        list_view = self._list_view()
        dom_index = list_view.index
        preserve = self._clip_list.preserve_after_status_change(list_view, dom_index)
        previous_status = candidate.status
        if status == previous_status:
            return
        if status == "skipped":
            self._skip_undo_stack.append((candidate.clip_id, previous_status))
        candidate.status = status
        self._clip_list.apply_status_change_visibility(
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
        clip_id = self._clip_list.move_cursor(self._list_view(), forward=True)
        if clip_id is not None:
            self._update_detail(clip_id)

    def action_cursor_up(self) -> None:
        panel = self._detail_panel()
        panel.stop_playback()
        panel.switch_to_basic_tab()
        clip_id = self._clip_list.move_cursor(self._list_view(), forward=False)
        if clip_id is not None:
            self._update_detail(clip_id)

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
        candidate.status = previous_status
        self._clip_list.restore_item_visibility(self._list_view(), clip_id)
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
        self._clip_list.refresh_list_item(self._list_view(), candidate)
        self._update_detail(candidate.clip_id)
        self._persist()
        self.notify(f"Renamed #{clip_id}")

    def action_bulk_skip_above(self) -> None:
        list_view = self._list_view()
        if list_view.index is None or not self._clip_list.filtered_clip_ids:
            return
        dom_index = list_view.index
        preserve = self._clip_list.preserve_after_status_change(list_view, dom_index)
        clip_ids_to_skip = self._clip_list.filtered_clip_ids[: visible_index + 1]
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
        if self._clip_list.hide_processed and count > 0:
            self._clip_list.hide_processed_bulk(list_view, clip_ids_to_skip, preserve)
        else:
            self._clip_list.pin_processed_visible(clip_ids_to_skip)
            for clip_id in clip_ids_to_skip:
                candidate = self.session.get_candidate(clip_id)
                if candidate is None:
                    continue
                self._clip_list.refresh_list_item(list_view, candidate)
            preserve = self._clip_list.preserve_after_status_change(list_view, dom_index)
            if preserve is not None:
                self._clip_list.select_after_hide(list_view, dom_index, preserve)
            else:
                current = self._current_candidate()
                if current is not None:
                    self._detail_panel().update_clip_status(
                        ClipDetailPanel.clip_status_text(current)
                    )
        self.notify(f"Skipped {count} unmarked clips (current and above)")

    def action_cycle_filter(self) -> None:
        change = self._clip_list.cycle_filter(direction=1)
        if change is None:
            return
        self._sync_filter_tabs()
        self._clip_list.apply_filter_to_items(
            self._list_view(),
            select_first=change.select_first,
            preserve_clip_id=change.preserve_clip_id,
        )

    def action_open_filter_modal(self) -> None:
        self.app.push_screen(
            FilterSelectionModal(self._clip_list.filter_mode),
            self._handle_filter_selection,
        )

    def _handle_filter_selection(self, filter_mode: str | None) -> None:
        if filter_mode is None or filter_mode == self._clip_list.filter_mode:
            return
        self._set_filter_mode(filter_mode)

    def _jump_to_clip_id(self, clip_id: str) -> bool:
        panel = self._detail_panel()
        panel.stop_playback()
        panel.switch_to_basic_tab()
        return self._clip_list.jump_to_clip_id(self._list_view(), clip_id)

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
        target = self._clip_list.find_target_clip_id(requested_index)
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

    def action_generate_filter_waveforms(self) -> None:
        if self._waveform_bulk_progress is not None:
            self.notify("Waveform pre-generation already running.", severity="warning")
            return
        candidates = list(self._clip_list.visible_candidates())
        if not candidates:
            self.notify("No clips in current filter.")
            return
        pending = [
            candidate
            for candidate in candidates
            if not self._waveform()
            .basic_cache_path(candidate, suffix=".png")
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
        current = self._current_candidate()
        preserve = self._clip_list.toggle_hide_processed(
            current.clip_id if current is not None else None
        )
        self._clip_list.apply_filter_to_items(
            self._list_view(),
            preserve_clip_id=preserve,
        )
        state = "hidden" if self._clip_list.hide_processed else "shown"
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
        self._clip_list.refresh_list_item(self._list_view(), candidate)
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
        list_view = self._list_view()
        item = self._clip_list.find_list_item(list_view, candidate.clip_id)
        dom_index = (
            list_view.children.index(item)
            if item is not None
            else None
        )
        preserve = (
            self._clip_list.preserve_after_status_change(list_view, dom_index)
            if self._clip_list.hide_processed
            else None
        )
        self._clip_list.apply_status_change_visibility(
            candidate,
            list_view,
            dom_index=dom_index,
            preserve_clip_id=preserve,
            move_selection=self._clip_list.hide_processed,
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
        waveform = self._waveform()
        try:
            for index, candidate in enumerate(candidates, 1):
                target = waveform.basic_cache_path(candidate, suffix=".png")
                if target.exists():
                    cached += 1
                else:
                    try:
                        waveform.generate_basic(candidate)
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
