import hashlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.waveform_envelope import (
    ENVELOPE_CACHE_VERSION,
    MAX_ENVELOPE_CACHE_BUCKETS,
    WAVEFORM_ENVELOPE_SUFFIX,
    build_envelope_from_audio_slice,
    is_waveform_envelope_cache,
    load_envelope_cache,
    save_envelope_cache,
)
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds
from jipandan.tui.fine_waveform import (
    FINE_CLIP_SECONDS,
    FINE_EXTRACT_DURATION,
    FINE_EXTRACT_SECONDS,
    FINE_MODE_SPECS,
    FINE_NUDGE_COARSE,
    FINE_NUDGE_FINE,
    FINE_NUDGE_MODES,
    FINE_PADDING_SECONDS,
    FINE_REGEN_PADDING_SECONDS,
    FineNudgeMode,
    FineWaveformSlice,
    FineWaveformState,
)

WAVEFORM_DEBOUNCE_SECONDS = 0.4
WAVEFORM_DEBOUNCE_MAX_SECONDS = 1.0
WAVEFORM_PADDING_SECONDS = 1.0
WAVEFORM_MIN_PADDING_SECONDS = 0.2
MIN_SCHEDULE_DELAY_SECONDS = 0.001
FINE_PREGEN_DELAY_SECONDS = 1.0

ScheduleFunc = Callable[[float, Callable[[], None], str], Callable[[], None]]


@dataclass(frozen=True)
class BasicWaveformState:
    path: Path
    viewport_start: str
    viewport_duration: str
    media_duration: float | None


class WaveformService:
    """Basic waveform cache/generation plus a fine slice per trim edge."""

    def __init__(
        self,
        session: Session,
        cache_dir: Path,
        *,
        schedule: ScheduleFunc,
    ) -> None:
        self.session = session
        self._cache_dir = cache_dir
        self._schedule = schedule

        self._basic_generation = 0
        self._fine_pregen_generation = 0
        self._fine_slices: dict[FineNudgeMode, FineWaveformSlice] = {
            mode: FineWaveformSlice(spec, self)
            for mode, spec in FINE_MODE_SPECS.items()
        }

        self._displayed_basic_viewport: tuple[str, str] | None = None
        self._clip_basic_states: dict[str, BasicWaveformState] = {}

        self._basic_debounce_cancel: Callable[[], None] | None = None
        self._basic_debounce_started_at: float | None = None
        self._pending_basic_clip_id: str | None = None
        self._pending_basic_force_regen = False

        self._fine_pregen_cancel: Callable[[], None] | None = None
        self._pending_fine_pregen_clip_id: str | None = None

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def schedule(
        self, delay: float, callback: Callable[[], None], name: str
    ) -> Callable[[], None]:
        return self._schedule(delay, callback, name)

    def fine(self, mode: FineNudgeMode) -> FineWaveformSlice:
        return self._fine_slices[mode]

    # --- generation tokens ---

    def begin_basic_generation(self) -> int:
        self._basic_generation += 1
        return self._basic_generation

    def is_basic_generation_current(self, generation: int) -> bool:
        return generation == self._basic_generation

    def begin_fine_pregen(self) -> int:
        self._fine_pregen_generation += 1
        return self._fine_pregen_generation

    def is_fine_pregen_current(self, generation: int) -> bool:
        return generation == self._fine_pregen_generation

    def has_displayed_basic_viewport(self) -> bool:
        return self._displayed_basic_viewport is not None

    # --- basic cache paths ---

    @staticmethod
    def _basic_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.start}|{candidate.duration}|{ENVELOPE_CACHE_VERSION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def basic_cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._basic_key_digest(candidate)
        return self._cache_dir / f"{candidate.filename_token}_{digest}{suffix}"

    # --- file generation (thread-safe) ---

    @staticmethod
    def media_duration(path: Path) -> float | None:
        if not path.exists():
            return None
        if is_waveform_envelope_cache(path):
            try:
                return load_envelope_cache(path).duration
            except (OSError, ValueError, KeyError):
                return None
        try:
            return ffmpeg.probe_duration_seconds(path)
        except (OSError, subprocess.CalledProcessError, ValueError):
            return None

    def generate_basic(self, candidate: ClipCandidate) -> tuple[Path, float]:
        target = self.ensure_basic_envelope(candidate)
        return target, load_envelope_cache(target).duration

    def ensure_basic_envelope(self, candidate: ClipCandidate) -> Path:
        """Return the basic-tab waveform envelope cache, building it if needed."""
        target = self.basic_cache_path(candidate, suffix=WAVEFORM_ENVELOPE_SUFFIX)
        if target.exists():
            return target
        extract_start, extract_duration = self.basic_extract_range(candidate)
        start_seconds = srt_time_to_seconds(extract_start.replace(".", ","))
        duration_seconds = float(extract_duration)
        envelope = build_envelope_from_audio_slice(
            self.session.audio,
            start_seconds,
            duration_seconds,
            MAX_ENVELOPE_CACHE_BUCKETS,
        )
        save_envelope_cache(
            target,
            times=envelope.times,
            mins=envelope.mins,
            maxs=envelope.maxs,
            duration=envelope.duration,
            buckets=envelope.buckets,
        )
        return target

    # --- viewport / marker geometry ---

    @staticmethod
    def clip_start_seconds(candidate: ClipCandidate) -> float:
        return srt_time_to_seconds(candidate.start.replace(".", ","))

    @staticmethod
    def clip_end_seconds(candidate: ClipCandidate) -> float:
        return srt_time_to_seconds(candidate.end.replace(".", ","))

    @staticmethod
    def _padding_below_minimum(
        before: float, after: float, *, minimum: float = WAVEFORM_MIN_PADDING_SECONDS
    ) -> bool:
        return before < minimum or after < minimum

    @staticmethod
    def fine_marker_padding_insufficient(marker_position: float) -> bool:
        return (
            marker_position < FINE_REGEN_PADDING_SECONDS
            or (FINE_EXTRACT_SECONDS - marker_position) < FINE_REGEN_PADDING_SECONDS
        )

    def basic_padded_start_seconds(self, candidate: ClipCandidate) -> float:
        return max(
            0.0,
            self.clip_start_seconds(candidate) - WAVEFORM_PADDING_SECONDS,
        )

    def basic_padded_end_seconds(self, candidate: ClipCandidate) -> float:
        return self.clip_end_seconds(candidate) + WAVEFORM_PADDING_SECONDS

    def basic_extract_range(self, candidate: ClipCandidate) -> tuple[str, str]:
        padded_start = self.basic_padded_start_seconds(candidate)
        duration = self.basic_padded_end_seconds(candidate) - padded_start
        return (
            seconds_to_ffmpeg_timestamp(padded_start),
            f"{duration:.3f}",
        )

    def basic_viewport(
        self, candidate: ClipCandidate, *, media_duration: float | None = None
    ) -> tuple[str, str]:
        padded_start = self.basic_padded_start_seconds(candidate)
        if media_duration is not None:
            duration = media_duration
        else:
            duration = self.basic_padded_end_seconds(candidate) - padded_start
        return (
            seconds_to_ffmpeg_timestamp(padded_start),
            f"{duration:.3f}",
        )

    def fine_marker_times(
        self, extract_start: float, candidate: ClipCandidate
    ) -> tuple[float, float]:
        clip_start = self.clip_start_seconds(candidate)
        clip_end = self.clip_end_seconds(candidate)
        rel_start = clip_start - extract_start
        rel_end = clip_end - extract_start
        return rel_start, rel_end

    def _viewport_padding_insufficient(
        self,
        candidate: ClipCandidate,
        viewport_start: str,
        viewport_duration: str,
    ) -> bool:
        disp_start = srt_time_to_seconds(viewport_start.replace(".", ","))
        disp_end = disp_start + float(viewport_duration)
        clip_start = self.clip_start_seconds(candidate)
        clip_end = self.clip_end_seconds(candidate)
        return self._padding_below_minimum(
            clip_start - disp_start,
            disp_end - clip_end,
        )

    def needs_basic_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_basic_viewport is None:
            return True
        viewport_start, viewport_duration = self._displayed_basic_viewport
        return self._viewport_padding_insufficient(
            candidate, viewport_start, viewport_duration
        )

    # --- in-memory cache ---

    def clear_cache(self) -> None:
        self._displayed_basic_viewport = None
        self._clip_basic_states.clear()
        for slice_ in self._fine_slices.values():
            slice_.clear()
        self.cancel_fine_pregen()

    def try_reuse_basic(self, candidate: ClipCandidate) -> BasicWaveformState | None:
        stored = self._clip_basic_states.get(candidate.clip_id)
        if stored is None or not stored.path.exists():
            return None
        if self._viewport_padding_insufficient(
            candidate, stored.viewport_start, stored.viewport_duration
        ):
            return None
        return stored

    def fine_pair_ready(self, candidate: ClipCandidate) -> bool:
        return all(
            self.fine(mode).is_ready(candidate) for mode in FINE_NUDGE_MODES
        )

    def record_basic_display(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        viewport_start: str | None = None,
        viewport_duration: str | None = None,
    ) -> BasicWaveformState:
        if viewport_start is None or viewport_duration is None:
            viewport_start, viewport_duration = self.basic_viewport(
                candidate, media_duration=media_duration
            )
        self._displayed_basic_viewport = (viewport_start, viewport_duration)
        state = BasicWaveformState(
            path=path,
            viewport_start=viewport_start,
            viewport_duration=viewport_duration,
            media_duration=media_duration,
        )
        self._clip_basic_states[candidate.clip_id] = state
        return state

    def store_fine_pregen(
        self,
        clip_id: str,
        *,
        generation: int,
        states: dict[FineNudgeMode, FineWaveformState],
    ) -> None:
        if not self.is_fine_pregen_current(generation):
            return
        for mode in FINE_NUDGE_MODES:
            self.fine(mode).store_pregen(clip_id, states[mode])

    # --- debounce scheduling ---

    def _cancel_timer(self, cancel: Callable[[], None] | None) -> None:
        if cancel is not None:
            cancel()

    def cancel_basic_debounce(self) -> None:
        self._cancel_timer(self._basic_debounce_cancel)
        self._basic_debounce_cancel = None
        self._pending_basic_clip_id = None
        self._basic_debounce_started_at = None
        self._pending_basic_force_regen = False

    def cancel_fine_debounce(self, mode: FineNudgeMode | None = None) -> None:
        if mode is None:
            for slice_ in self._fine_slices.values():
                slice_.cancel_debounce()
        else:
            self.fine(mode).cancel_debounce()

    def cancel_fine_pregen(self) -> None:
        self._cancel_timer(self._fine_pregen_cancel)
        self._fine_pregen_cancel = None
        self._pending_fine_pregen_clip_id = None
        self.begin_fine_pregen()

    def cancel_all(self) -> None:
        self.cancel_basic_debounce()
        self.cancel_fine_debounce()

    def cancel_waveform_debounce(self) -> None:
        """Cancel basic and fine debounce timers (matches prior panel behavior)."""
        self.cancel_basic_debounce()
        self.cancel_fine_debounce()

    def schedule_basic_refresh(
        self,
        clip_id: str,
        *,
        force_regen: bool = False,
        on_fire: Callable[[str, bool], None],
    ) -> None:
        self._pending_basic_clip_id = clip_id
        self._pending_basic_force_regen = force_regen
        now = time.monotonic()
        if self._basic_debounce_started_at is None:
            self._basic_debounce_started_at = now

        self._cancel_timer(self._basic_debounce_cancel)
        self._basic_debounce_cancel = None

        elapsed = now - self._basic_debounce_started_at
        if elapsed >= WAVEFORM_DEBOUNCE_MAX_SECONDS:
            delay = 0.0
        else:
            delay = min(
                WAVEFORM_DEBOUNCE_SECONDS,
                WAVEFORM_DEBOUNCE_MAX_SECONDS - elapsed,
            )

        def fire() -> None:
            self._basic_debounce_cancel = None
            self._basic_debounce_started_at = None
            pending_id = self._pending_basic_clip_id
            pending_force = self._pending_basic_force_regen
            self._pending_basic_clip_id = None
            self._pending_basic_force_regen = False
            if pending_id is None:
                return
            on_fire(pending_id, pending_force)

        self._basic_debounce_cancel = self._schedule(
            max(delay, MIN_SCHEDULE_DELAY_SECONDS),
            fire,
            "waveform-debounce",
        )

    def schedule_fine_pregen(
        self,
        clip_id: str,
        on_fire: Callable[[str], None],
    ) -> None:
        self._cancel_timer(self._fine_pregen_cancel)
        self._fine_pregen_cancel = None
        self._pending_fine_pregen_clip_id = clip_id

        def fire() -> None:
            self._fine_pregen_cancel = None
            pending_id = self._pending_fine_pregen_clip_id
            self._pending_fine_pregen_clip_id = None
            if pending_id is None:
                return
            on_fire(pending_id)

        self._fine_pregen_cancel = self._schedule(
            FINE_PREGEN_DELAY_SECONDS,
            fire,
            "fine-pregen",
        )
