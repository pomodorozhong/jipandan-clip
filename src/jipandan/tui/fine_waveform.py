"""Fine nudge waveform: one spec and one slice per trim edge (start / end)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate
from jipandan.core.srt import seconds_to_ffmpeg_timestamp

if TYPE_CHECKING:
    from jipandan.tui.waveform_service import WaveformService

FINE_CLIP_SECONDS = 0.5
FINE_PADDING_SECONDS = 0.3
FINE_REGEN_PADDING_SECONDS = 0.1
FINE_EXTRACT_SECONDS = FINE_PADDING_SECONDS + FINE_CLIP_SECONDS
FINE_EXTRACT_DURATION = f"{FINE_EXTRACT_SECONDS:.3f}"
FINE_NUDGE_FINE = 0.01
FINE_NUDGE_COARSE = 0.1

FineNudgeMode = Literal["start", "end"]
FINE_NUDGE_MODES: tuple[FineNudgeMode, FineNudgeMode] = ("start", "end")

FINE_START_TAB_ID = "fine-start"
FINE_END_TAB_ID = "fine-end"
FINE_START_WIDGET_ID = "waveform-fine"
FINE_END_WIDGET_ID = "waveform-fine-end"

TAB_TO_FINE_MODE: dict[str, FineNudgeMode] = {
    FINE_START_TAB_ID: "start",
    FINE_END_TAB_ID: "end",
}


@dataclass(frozen=True)
class FineWaveformState:
    path: Path
    extract_start: float
    media_duration: float | None


@dataclass(frozen=True)
class FineModeSpec:
    """Immutable per-edge rules: cache keys, extract window, markers, playback, UI ids."""

    mode: FineNudgeMode
    tab_id: str
    widget_id: str
    cache_suffix: str
    debounce_timer_name: str

    @property
    def has_detail_labels(self) -> bool:
        return self.mode == "start"

    def trim_key(self, candidate: ClipCandidate) -> str:
        return candidate.start if self.mode == "start" else candidate.end

    def cache_key_digest(self, candidate: ClipCandidate) -> str:
        key = f"{self.trim_key(candidate)}|{FINE_EXTRACT_DURATION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def extract_start_seconds(self, clip_start: float, clip_end: float) -> float:
        if self.mode == "start":
            return max(0.0, clip_start - FINE_PADDING_SECONDS)
        return max(0.0, clip_end - FINE_CLIP_SECONDS)

    def marker_rel(self, rel_start: float, rel_end: float) -> float:
        return rel_start if self.mode == "start" else rel_end

    def playback_range(
        self, candidate: ClipCandidate, clip_start: float, clip_end: float
    ) -> tuple[str, float]:
        if self.mode == "start":
            duration = min(FINE_CLIP_SECONDS, float(candidate.duration))
            return candidate.start, duration
        duration = min(FINE_CLIP_SECONDS, clip_end - clip_start)
        start = max(clip_start, clip_end - duration)
        return seconds_to_ffmpeg_timestamp(start), duration


FINE_MODE_SPECS: dict[FineNudgeMode, FineModeSpec] = {
    "start": FineModeSpec(
        mode="start",
        tab_id=FINE_START_TAB_ID,
        widget_id=FINE_START_WIDGET_ID,
        cache_suffix="_fine",
        debounce_timer_name="fine-debounce",
    ),
    "end": FineModeSpec(
        mode="end",
        tab_id=FINE_END_TAB_ID,
        widget_id=FINE_END_WIDGET_ID,
        cache_suffix="_fine-end",
        debounce_timer_name="fine-end-debounce",
    ),
}


class FineWaveformSlice:
    """Mutable cache, generation token, debounce, and display state for one fine edge."""

    def __init__(self, spec: FineModeSpec, service: WaveformService) -> None:
        self._spec = spec
        self._service = service
        self._generation = 0
        self._displayed_extract: float | None = None
        self._clip_states: dict[str, FineWaveformState] = {}
        self._debounce_cancel: Callable[[], None] | None = None
        self._pending_clip_id: str | None = None

    @property
    def spec(self) -> FineModeSpec:
        return self._spec

    @property
    def mode(self) -> FineNudgeMode:
        return self._spec.mode

    def begin_generation(self) -> int:
        self._generation += 1
        return self._generation

    def is_generation_current(self, generation: int) -> bool:
        return generation == self._generation

    def cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._spec.cache_key_digest(candidate)
        return (
            self._service.cache_dir
            / f"{candidate.filename_token}_{digest}{self._spec.cache_suffix}{suffix}"
        )

    def extract_start(self, candidate: ClipCandidate) -> float:
        svc = self._service
        return self._spec.extract_start_seconds(
            svc.clip_start_seconds(candidate),
            svc.clip_end_seconds(candidate),
        )

    def displayed_extract(self) -> float | None:
        return self._displayed_extract

    def generate(self, candidate: ClipCandidate) -> tuple[Path, float]:
        target_mp3 = self.cache_path(candidate, suffix=".mp3")
        if target_mp3.exists():
            return target_mp3, ffmpeg.probe_duration_seconds(target_mp3)
        target_mp3.parent.mkdir(parents=True, exist_ok=True)
        extract_start = self.extract_start(candidate)
        ffmpeg.extract_preview_fast(
            self._service.session.audio,
            seconds_to_ffmpeg_timestamp(extract_start),
            FINE_EXTRACT_DURATION,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        return target_mp3, media_duration

    def _padding_insufficient(
        self, candidate: ClipCandidate, extract_start: float
    ) -> bool:
        rel_start, rel_end = self._service.fine_marker_times(extract_start, candidate)
        marker = self._spec.marker_rel(rel_start, rel_end)
        return self._service.fine_marker_padding_insufficient(marker)

    def needs_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_extract is None:
            return True
        return self._padding_insufficient(candidate, self._displayed_extract)

    def try_reuse(self, candidate: ClipCandidate) -> FineWaveformState | None:
        stored = self._clip_states.get(candidate.clip_id)
        if stored is None or not stored.path.exists():
            return None
        if self._padding_insufficient(candidate, stored.extract_start):
            return None
        return stored

    def record_display(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> FineWaveformState:
        if extract_start is None:
            extract_start = self.extract_start(candidate)
        self._displayed_extract = extract_start
        state = FineWaveformState(
            path=path,
            extract_start=extract_start,
            media_duration=media_duration,
        )
        self._clip_states[candidate.clip_id] = state
        return state

    def store_pregen(self, clip_id: str, state: FineWaveformState) -> None:
        self._clip_states[clip_id] = state

    def is_ready(self, candidate: ClipCandidate) -> bool:
        stored = self._clip_states.get(candidate.clip_id)
        if stored is None or not stored.path.exists():
            return False
        return not self._padding_insufficient(candidate, stored.extract_start)

    def clear(self) -> None:
        self._displayed_extract = None
        self._clip_states.clear()
        self.cancel_debounce()

    def _stop_debounce_timer(self) -> None:
        if self._debounce_cancel is not None:
            self._debounce_cancel()
        self._debounce_cancel = None

    def cancel_debounce(self) -> None:
        self._stop_debounce_timer()
        self._pending_clip_id = None

    def schedule_feedback(
        self, clip_id: str, on_fire: Callable[[str], None]
    ) -> None:
        from jipandan.tui.waveform_service import WAVEFORM_DEBOUNCE_SECONDS

        self._pending_clip_id = clip_id
        self._stop_debounce_timer()

        def fire() -> None:
            self._debounce_cancel = None
            pending_id = self._pending_clip_id
            self._pending_clip_id = None
            if pending_id is None:
                return
            on_fire(pending_id)

        self._debounce_cancel = self._service.schedule(
            WAVEFORM_DEBOUNCE_SECONDS,
            fire,
            self._spec.debounce_timer_name,
        )
