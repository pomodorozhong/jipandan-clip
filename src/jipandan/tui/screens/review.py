from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, ClipStatus, Session
from jipandan.tui.widgets.waveform import FINETUNE_HELP, WaveformWidget

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

    #detail-panel {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._filter_bar_text(include_position=False), id="filter-bar")
        with Horizontal(id="main-pane"):
            yield ListView(id="clip-list")
            with Vertical(id="detail-panel"):
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
            "j/k nav  1/2 group  x skip  Ctrl+Shift+X skip above  "
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

    def _rebuild_list(
        self,
        select_first: bool = False,
        preserve_index: int | None = None,
    ) -> None:
        list_view = self.query_one("#clip-list", ListView)
        list_view.clear()
        self.filtered_indices = []
        for candidate in self._visible_candidates():
            self.filtered_indices.append(candidate.index)
            list_view.append(ClipListItem(candidate))
        self.query_one("#filter-bar", Static).update(self._filter_bar_text())
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
            self._clear_detail()

    def _current_candidate(self) -> ClipCandidate | None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return None
        try:
            index = self.filtered_indices[list_view.index]
        except IndexError:
            return None
        return self.session.get_candidate(index)

    def _clear_detail(self) -> None:
        self.query_one("#clip-title", Static).update("No clips in current filter.")
        self.query_one("#waveform", WaveformWidget).show_placeholder("No waveform.")
        self.query_one("#clip-times", Static).update("")
        self.query_one("#clip-status", Static).update("")

    def _update_detail(self, index: int) -> None:
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
        self._show_waveform(candidate)

    @staticmethod
    def _waveform_cache_key(candidate: ClipCandidate) -> tuple[int, str, str]:
        return (candidate.index, candidate.start, candidate.duration)

    def _show_waveform(self, candidate: ClipCandidate) -> None:
        cached = self._waveform_cache.get(self._waveform_cache_key(candidate))
        if cached is not None and cached.exists():
            self.query_one("#waveform", WaveformWidget).update_image(cached)
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
        list_index = list_view.index
        candidate.status = status
        if self.hide_skipped and status == "skipped":
            self._persist()
            self._rebuild_list()
            if self.filtered_indices:
                new_index = min(list_index or 0, len(self.filtered_indices) - 1)
                list_view.index = new_index
                self._update_detail(self.filtered_indices[new_index])
            else:
                self._clear_detail()
            return
        self._refresh_list_item(candidate)
        self.query_one("#clip-status", Static).update(f"Status: {candidate.status}")
        self._persist()

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        if list_view.index < len(self.filtered_indices) - 1:
            list_view.index += 1
            self._update_detail(self.filtered_indices[list_view.index])

    def action_cursor_up(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None:
            return
        if list_view.index > 0:
            list_view.index -= 1
            self._update_detail(self.filtered_indices[list_view.index])

    def action_mark_group1(self) -> None:
        self._set_status("group1")

    def action_mark_group2(self) -> None:
        self._set_status("group2")

    def action_mark_skipped(self) -> None:
        self._set_status("skipped")

    def action_bulk_skip_above(self) -> None:
        list_view = self.query_one("#clip-list", ListView)
        if list_view.index is None or not self.filtered_indices:
            return
        indices_to_skip = self.filtered_indices[: list_view.index + 1]
        count = self.session.bulk_skip(indices_to_skip)
        self._persist()
        if self.hide_skipped and count > 0:
            current = self._current_candidate()
            preserve = current.index if current is not None else None
            self._rebuild_list(preserve_index=preserve)
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
        self._update_detail(candidate.index)
        self._persist()

    def _nudge_end(self, delta: float) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.session.nudge_end(candidate.index, delta)
        self._update_detail(candidate.index)
        self._persist()

    def action_play_preview(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.run_play_preview(candidate)

    @work(thread=True, exclusive=True)
    def run_play_preview(self, candidate: ClipCandidate) -> None:
        try:
            ffmpeg.play_preview(self.session.audio, candidate.start, candidate.duration)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"mpv failed: {exc}", severity="error")

    def action_export_clip(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            return
        self.run_export(candidate)

    @work(thread=True, exclusive=True)
    def run_export(self, candidate: ClipCandidate) -> None:
        try:
            output = ffmpeg.export_clip(
                self.session.audio,
                candidate,
                self.session.clip_dir,
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
        self.run_play_exported(output)

    @work(thread=True, exclusive=True)
    def run_play_exported(self, output: Path) -> None:
        try:
            ffmpeg.play_file(output)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"mpv failed: {exc}", severity="error")

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
                self.query_one("#waveform", WaveformWidget).update_image,
                tmp_png,
            )
        except Exception as exc:
            if generation != self._waveform_generation:
                return
            self.app.call_from_thread(
                self.query_one("#waveform", WaveformWidget).show_placeholder,
                f"Waveform failed: {exc}",
            )
