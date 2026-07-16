"""Tests for ranked filter list ordering."""

from __future__ import annotations

import unittest
from pathlib import Path

from jipandan.core.models import ClipCandidate, Session
from jipandan.tui.clip_list import ClipListController


def _session(candidates: list[ClipCandidate]) -> Session:
    return Session(
        audio=Path("raw.mp3"),
        srt=Path("raw.srt"),
        clip_dir=Path("clip"),
        candidates=candidates,
    )


def _candidate(
    index: int,
    *,
    duration: str,
    status: str = "pending",
) -> ClipCandidate:
    return ClipCandidate(
        index=index,
        title=f"clip {index}",
        original_start="00:00:00.000",
        original_end="00:00:01.000",
        start="00:00:00.000",
        duration=duration,
        status=status,  # type: ignore[arg-type]
    )


class RankedFilterTests(unittest.TestCase):
    def test_ranked_matches_pending_like_unsorted(self) -> None:
        session = _session(
            [
                _candidate(1, duration="3.000", status="pending"),
                _candidate(2, duration="3.000", status="group1"),
                _candidate(3, duration="3.000", status="skipped"),
            ]
        )
        controller = ClipListController(
            session,
            on_selection_changed=lambda _clip_id: None,
        )
        controller.filter_mode = "ranked"
        visible = controller.visible_candidates()
        self.assertEqual([c.clip_id for c in visible], ["1"])

    def test_ranked_orders_by_duration_when_no_amplitude(self) -> None:
        session = _session(
            [
                _candidate(1, duration="25.000"),
                _candidate(2, duration="4.000"),
                _candidate(3, duration="15.000"),
            ]
        )
        controller = ClipListController(
            session,
            on_selection_changed=lambda _clip_id: None,
        )
        controller.filter_mode = "ranked"
        ordered = controller.display_candidates()
        self.assertEqual([c.clip_id for c in ordered], ["2", "3", "1"])

    def test_ranked_uses_amplitude_when_provided(self) -> None:
        session = _session(
            [
                _candidate(1, duration="4.000"),
                _candidate(2, duration="4.000"),
            ]
        )
        amplitudes = {"1": 0.0, "2": 0.2}
        controller = ClipListController(
            session,
            on_selection_changed=lambda _clip_id: None,
            amplitude_for_candidate=lambda c: amplitudes.get(c.clip_id),
        )
        controller.filter_mode = "ranked"
        ordered = controller.display_candidates()
        self.assertEqual([c.clip_id for c in ordered], ["2", "1"])

    def test_filter_mode_change_flags_rebuild_for_ranked(self) -> None:
        session = _session([_candidate(1, duration="3.000")])
        controller = ClipListController(
            session,
            on_selection_changed=lambda _clip_id: None,
        )
        change = controller.prepare_filter_mode_change("ranked", "1")
        assert change is not None
        self.assertTrue(change.requires_rebuild)
        change_back = controller.prepare_filter_mode_change("unsorted", "1")
        assert change_back is not None
        self.assertTrue(change_back.requires_rebuild)


if __name__ == "__main__":
    unittest.main()
