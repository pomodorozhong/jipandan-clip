from collections.abc import Callable
from dataclasses import dataclass

from textual.containers import Horizontal
from textual.widgets import Label, ListItem, ListView, Tabs

from jipandan.core.models import ClipCandidate, ClipStatus, Session
from jipandan.tui.screens.filter_selection import FILTER_ORDER

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


@dataclass(frozen=True)
class FilterModeChange:
    """Result of changing the clip filter mode."""

    preserve_clip_id: str | None
    select_first: bool


class ClipListController:
    """Filter, visibility, selection, and DOM sync for the review clip list."""

    def __init__(
        self,
        session: Session,
        *,
        on_selection_changed: Callable[[str | None], None],
        on_list_state_changed: Callable[[], None] | None = None,
    ) -> None:
        self.session = session
        self._on_selection_changed = on_selection_changed
        self._on_list_state_changed = on_list_state_changed
        self.filter_mode = "unsorted"
        self.hide_processed = False
        self._pinned_processed_visible: set[str] = set()
        self._processed_hidden: set[str] = set()
        self.filtered_clip_ids: list[str] = []

    def _notify_list_state_changed(self) -> None:
        if self._on_list_state_changed is not None:
            self._on_list_state_changed()

    def prepare_filter_mode_change(
        self, mode: str, current_clip_id: str | None
    ) -> FilterModeChange | None:
        if mode == self.filter_mode:
            return None
        previous_mode = self.filter_mode
        preserve_clip_id: str | None = None
        if mode == "all" and previous_mode != "all" and current_clip_id is not None:
            preserve_clip_id = current_clip_id
        self.filter_mode = mode
        self._reset_processed_visibility_state()
        if preserve_clip_id is not None:
            return FilterModeChange(
                preserve_clip_id=preserve_clip_id,
                select_first=False,
            )
        return FilterModeChange(preserve_clip_id=None, select_first=True)

    def cycle_filter(self, *, direction: int) -> FilterModeChange | None:
        current_idx = FILTER_ORDER.index(self.filter_mode)
        next_mode = FILTER_ORDER[(current_idx + direction) % len(FILTER_ORDER)]
        return self.prepare_filter_mode_change(next_mode, current_clip_id=None)

    def toggle_hide_processed(self, current_clip_id: str | None) -> str | None:
        self.hide_processed = not self.hide_processed
        if self.hide_processed:
            self._pinned_processed_visible.clear()
        else:
            self._processed_hidden.clear()
        return current_clip_id

    def _reset_processed_visibility_state(self) -> None:
        self._pinned_processed_visible.clear()
        self._processed_hidden.clear()

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

    def visible_candidates(self) -> list[ClipCandidate]:
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
    def is_visible_item(item: ListItem) -> bool:
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
            if self.is_visible_item(item):
                return index
        return None

    def apply_filter_to_items(
        self,
        list_view: ListView,
        *,
        select_first: bool = False,
        preserve_clip_id: str | None = None,
    ) -> None:
        for item in list_view.children:
            if isinstance(item, ClipListItem):
                self._sync_item_visibility(item)
        self._sync_filtered_clip_ids(list_view)
        self._notify_list_state_changed()

        if preserve_clip_id is not None:
            for index, item in enumerate(list_view.children):
                if (
                    isinstance(item, ClipListItem)
                    and item.candidate_id == preserve_clip_id
                    and self.is_visible_item(item)
                ):
                    list_view.index = index
                    self._on_selection_changed(preserve_clip_id)
                    return
            if self.filtered_clip_ids:
                first_dom = self._first_visible_dom_index(list_view)
                if first_dom is not None:
                    list_view.index = first_dom
                    first_item = list_view.children[first_dom]
                    if isinstance(first_item, ClipListItem):
                        self._on_selection_changed(first_item.candidate_id)
                return

        if select_first:
            first_dom = self._first_visible_dom_index(list_view)
            if first_dom is not None:
                list_view.index = first_dom
                first_item = list_view.children[first_dom]
                if isinstance(first_item, ClipListItem):
                    self._on_selection_changed(first_item.candidate_id)
            else:
                list_view.index = None
                self._on_selection_changed(None)

    def visible_position(self, list_view: ListView, dom_index: int) -> int:
        visible = 0
        for index, item in enumerate(list_view.children):
            if index == dom_index:
                return visible
            if self.is_visible_item(item):
                visible += 1
        raise IndexError(dom_index)

    def next_visible_dom_index(
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
            if self.is_visible_item(list_view.children[index]):
                return index
        return None

    def _sync_filtered_clip_ids(self, list_view: ListView) -> None:
        self.filtered_clip_ids = [
            item.candidate_id
            for item in list_view.children
            if self.is_visible_item(item)
        ]

    def _select_after_hide(
        self,
        list_view: ListView,
        hidden_dom_index: int,
        next_clip_id: str | None,
    ) -> None:
        next_dom = self.next_visible_dom_index(list_view, hidden_dom_index)
        if next_dom is None:
            next_dom = self.next_visible_dom_index(
                list_view, hidden_dom_index, forward=False
            )
        if next_dom is not None:
            list_view.index = next_dom
        else:
            list_view.index = None
        self._notify_list_state_changed()
        self._on_selection_changed(next_clip_id)

    def select_after_hide(
        self,
        list_view: ListView,
        hidden_dom_index: int,
        next_clip_id: str | None,
    ) -> None:
        self._select_after_hide(list_view, hidden_dom_index, next_clip_id)

    def find_list_item(
        self, list_view: ListView, clip_id: str
    ) -> ClipListItem | None:
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_id == clip_id:
                return item
        return None

    def restore_item_visibility(self, list_view: ListView, clip_id: str) -> None:
        item = self.find_list_item(list_view, clip_id)
        if item is None:
            return
        candidate = self.session.get_candidate(clip_id)
        if candidate is None:
            return
        item.remove_class(PROCESSED_HIDDEN_CLASS)
        self._pinned_processed_visible.discard(clip_id)
        self._processed_hidden.discard(clip_id)
        item.refresh_candidate(candidate)
        self._sync_item_visibility(item)
        self._sync_filtered_clip_ids(list_view)
        list_view.index = list_view.children.index(item)
        self._on_selection_changed(clip_id)

    def hide_processed_bulk(
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
                self.refresh_list_item(list_view, candidate)
        self._select_after_hide(list_view, hidden_dom_index, next_clip_id)

    def preserve_after_status_change(
        self,
        list_view: ListView,
        dom_index: int | None,
    ) -> str | None:
        if dom_index is None:
            return None
        try:
            visible_index = self.visible_position(list_view, dom_index)
        except IndexError:
            return None
        return self._clip_id_after_removing(visible_index)

    def apply_status_change_visibility(
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
            preserve_clip_id = self.preserve_after_status_change(
                list_view, dom_index
            )

        if self.hide_processed:
            self._pinned_processed_visible.discard(clip_id)
            self._processed_hidden.add(clip_id)
        else:
            self._pinned_processed_visible.add(clip_id)
            self._processed_hidden.discard(clip_id)

        self.refresh_list_item(list_view, candidate)

        if not move_selection:
            return

        if dom_index is None:
            item = self.find_list_item(list_view, clip_id)
            if item is None:
                return
            dom_index = list_view.children.index(item)

        if preserve_clip_id is None:
            preserve_clip_id = self.preserve_after_status_change(
                list_view, dom_index
            )

        self._select_after_hide(list_view, dom_index, preserve_clip_id)

    def needs_rebuild(self, list_view: ListView) -> bool:
        expected_ids = {candidate.clip_id for candidate in self.session.candidates}
        existing_ids = {
            item.candidate_id
            for item in list_view.children
            if isinstance(item, ClipListItem)
        }
        return expected_ids != existing_ids

    def build_items(self) -> list[ClipListItem]:
        return [ClipListItem(candidate) for candidate in self.session.candidates]

    def find_insert_after(
        self,
        list_view: ListView,
        *,
        source_clip_id: str,
        duplicate: ClipCandidate,
    ) -> ClipListItem | None:
        insert_after: ClipListItem | None = None
        for item in list_view.children:
            if not isinstance(item, ClipListItem):
                continue
            candidate = self.session.get_candidate(item.candidate_id)
            if candidate is not None and candidate.index == duplicate.index:
                insert_after = item
        if insert_after is None:
            insert_after = self.find_list_item(list_view, source_clip_id)
        return insert_after

    def prepare_duplicate_item(self, duplicate: ClipCandidate) -> ClipListItem:
        new_item = ClipListItem(duplicate)
        self._sync_item_visibility(new_item)
        return new_item

    def after_duplicate_mounted(self, list_view: ListView) -> None:
        self._sync_filtered_clip_ids(list_view)
        self._notify_list_state_changed()

    def highlighted_item(self, list_view: ListView) -> ClipListItem | None:
        if list_view.index is None:
            return None
        try:
            item = list_view.children[list_view.index]
        except IndexError:
            return None
        if self.is_visible_item(item):
            return item
        return None

    def current_candidate(self, list_view: ListView) -> ClipCandidate | None:
        item = self.highlighted_item(list_view)
        if item is None:
            return None
        return self.session.get_candidate(item.candidate_id)

    def refresh_list_item(
        self, list_view: ListView, candidate: ClipCandidate
    ) -> None:
        for item in list_view.children:
            if isinstance(item, ClipListItem) and item.candidate_id == candidate.clip_id:
                item.refresh_candidate(candidate)
                self._sync_item_visibility(item)
                self._sync_filtered_clip_ids(list_view)
                self._notify_list_state_changed()
                break

    def restore_list_index_if_drifted(
        self, list_view: ListView, pinned_index: int | None
    ) -> None:
        if pinned_index is None:
            return
        if list_view.index != pinned_index:
            list_view.index = pinned_index

    def move_cursor(
        self,
        list_view: ListView,
        *,
        forward: bool,
    ) -> str | None:
        if list_view.index is None:
            return None
        next_dom = self.next_visible_dom_index(
            list_view, list_view.index, forward=forward
        )
        if next_dom is None:
            if forward:
                indices = range(len(list_view.children))
            else:
                indices = range(len(list_view.children) - 1, -1, -1)
            for index in indices:
                if self.is_visible_item(list_view.children[index]):
                    next_dom = index
                    break
        if next_dom is None:
            return None
        list_view.index = next_dom
        item = list_view.children[next_dom]
        if isinstance(item, ClipListItem):
            return item.candidate_id
        return None

    def pin_processed_visible(self, clip_ids: list[str]) -> None:
        for clip_id in clip_ids:
            self._pinned_processed_visible.add(clip_id)

    @staticmethod
    def _parse_clip_index(clip_id: str) -> int | None:
        try:
            return int(clip_id)
        except ValueError:
            return None

    def find_target_clip_id(self, requested_index: int) -> tuple[str, bool] | None:
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

    def jump_to_clip_id(self, list_view: ListView, clip_id: str) -> bool:
        for index, item in enumerate(list_view.children):
            if (
                isinstance(item, ClipListItem)
                and item.candidate_id == clip_id
                and self.is_visible_item(item)
            ):
                list_view.index = index
                self._on_selection_changed(clip_id)
                return True
        return False
