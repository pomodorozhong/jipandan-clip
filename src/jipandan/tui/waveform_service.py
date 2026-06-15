import hashlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.srt import seconds_to_ffmpeg_timestamp, srt_time_to_seconds

WAVEFORM_DEBOUNCE_SECONDS = 0.4
WAVEFORM_DEBOUNCE_MAX_SECONDS = 1.0
WAVEFORM_PADDING_SECONDS = 1.0
WAVEFORM_MIN_PADDING_SECONDS = 0.2
MIN_SCHEDULE_DELAY_SECONDS = 0.001
FINE_CLIP_SECONDS = 0.5
FINE_PADDING_SECONDS = 0.3
FINE_REGEN_PADDING_SECONDS = 0.1
FINE_EXTRACT_SECONDS = FINE_PADDING_SECONDS + FINE_CLIP_SECONDS
FINE_EXTRACT_DURATION = f"{FINE_EXTRACT_SECONDS:.3f}"
FINE_PREGEN_DELAY_SECONDS = 1.0
FINE_NUDGE_FINE = 0.01
FINE_NUDGE_COARSE = 0.1
FINE_START_CACHE_SUFFIX = "_fine"
FINE_END_CACHE_SUFFIX = "_fine-end"

ScheduleFunc = Callable[[float, Callable[[], None], str], Callable[[], None]]


@dataclass(frozen=True)
class BasicWaveformState:
    path: Path
    viewport_start: str
    viewport_duration: str
    media_duration: float | None


@dataclass(frozen=True)
class FineWaveformState:
    path: Path
    extract_start: float
    media_duration: float | None


class WaveformService:
    """Cache paths, file generation, in-memory cache, and debounce scheduling."""

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
        self._fine_start_generation = 0
        self._fine_end_generation = 0
        self._fine_pregen_generation = 0

        self._displayed_basic_viewport: tuple[str, str] | None = None
        self._displayed_fine_start_extract: float | None = None
        self._displayed_fine_end_extract: float | None = None
        self._clip_basic_states: dict[str, BasicWaveformState] = {}
        self._clip_fine_start_states: dict[str, FineWaveformState] = {}
        self._clip_fine_end_states: dict[str, FineWaveformState] = {}

        self._basic_debounce_cancel: Callable[[], None] | None = None
        self._basic_debounce_started_at: float | None = None
        self._pending_basic_clip_id: str | None = None
        self._pending_basic_force_regen = False

        self._fine_start_debounce_cancel: Callable[[], None] | None = None
        self._pending_fine_start_clip_id: str | None = None

        self._fine_end_debounce_cancel: Callable[[], None] | None = None
        self._pending_fine_end_clip_id: str | None = None

        self._fine_pregen_cancel: Callable[[], None] | None = None
        self._pending_fine_pregen_clip_id: str | None = None

    # --- generation tokens ---

    def begin_basic_generation(self) -> int:
        self._basic_generation += 1
        return self._basic_generation

    def is_basic_generation_current(self, generation: int) -> bool:
        return generation == self._basic_generation

    def begin_fine_start_generation(self) -> int:
        self._fine_start_generation += 1
        return self._fine_start_generation

    def is_fine_start_generation_current(self, generation: int) -> bool:
        return generation == self._fine_start_generation

    def begin_fine_end_generation(self) -> int:
        self._fine_end_generation += 1
        return self._fine_end_generation

    def is_fine_end_generation_current(self, generation: int) -> bool:
        return generation == self._fine_end_generation

    def begin_fine_pregen(self) -> int:
        self._fine_pregen_generation += 1
        return self._fine_pregen_generation

    def is_fine_pregen_current(self, generation: int) -> bool:
        return generation == self._fine_pregen_generation

    def has_displayed_basic_viewport(self) -> bool:
        return self._displayed_basic_viewport is not None

    # --- cache paths ---

    @staticmethod
    def _basic_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.start}|{candidate.duration}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def basic_cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._basic_key_digest(candidate)
        return self._cache_dir / f"{candidate.filename_token}_{digest}{suffix}"

    @staticmethod
    def _fine_start_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.start}|{FINE_EXTRACT_DURATION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def fine_start_cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._fine_start_key_digest(candidate)
        return (
            self._cache_dir
            / f"{candidate.filename_token}_{digest}{FINE_START_CACHE_SUFFIX}{suffix}"
        )

    @staticmethod
    def _fine_end_key_digest(candidate: ClipCandidate) -> str:
        key = f"{candidate.end}|{FINE_EXTRACT_DURATION}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

    def fine_end_cache_path(self, candidate: ClipCandidate, *, suffix: str) -> Path:
        digest = self._fine_end_key_digest(candidate)
        return (
            self._cache_dir
            / f"{candidate.filename_token}_{digest}{FINE_END_CACHE_SUFFIX}{suffix}"
        )

    # --- file generation (thread-safe) ---

    @staticmethod
    def media_duration(png_path: Path) -> float | None:
        mp3_path = png_path.with_name(png_path.stem + ".mp3")
        if not mp3_path.exists():
            return None
        try:
            return ffmpeg.probe_duration_seconds(mp3_path)
        except (OSError, subprocess.CalledProcessError, ValueError):
            return None

    def generate_basic(self, candidate: ClipCandidate) -> tuple[Path, float]:
        target_png = self.basic_cache_path(candidate, suffix=".png")
        target_mp3 = self.basic_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        target_png.parent.mkdir(parents=True, exist_ok=True)
        extract_start, extract_duration = self.basic_extract_range(candidate)
        ffmpeg.extract_preview_fast(
            self.session.audio,
            extract_start,
            extract_duration,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

    def generate_fine_start(self, candidate: ClipCandidate) -> tuple[Path, float]:
        target_png = self.fine_start_cache_path(candidate, suffix=".png")
        target_mp3 = self.fine_start_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        target_png.parent.mkdir(parents=True, exist_ok=True)
        extract_start = self.fine_start_extract_start(candidate)
        ffmpeg.extract_preview_fast(
            self.session.audio,
            seconds_to_ffmpeg_timestamp(extract_start),
            FINE_EXTRACT_DURATION,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

    def generate_fine_end(self, candidate: ClipCandidate) -> tuple[Path, float]:
        target_png = self.fine_end_cache_path(candidate, suffix=".png")
        target_mp3 = self.fine_end_cache_path(candidate, suffix=".mp3")
        if target_png.exists() and target_mp3.exists():
            return target_png, ffmpeg.probe_duration_seconds(target_mp3)
        extract_start = self.fine_end_extract_start(candidate)
        target_png.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.extract_preview_fast(
            self.session.audio,
            seconds_to_ffmpeg_timestamp(extract_start),
            FINE_EXTRACT_DURATION,
            target_mp3,
        )
        media_duration = ffmpeg.probe_duration_seconds(target_mp3)
        ffmpeg.render_waveform(target_mp3, target_png)
        return target_png, media_duration

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
    def _fine_marker_padding_insufficient(marker_position: float) -> bool:
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

    def fine_start_extract_start(self, candidate: ClipCandidate) -> float:
        return max(
            0.0,
            self.clip_start_seconds(candidate) - FINE_PADDING_SECONDS,
        )

    def fine_end_extract_start(self, candidate: ClipCandidate) -> float:
        return max(
            0.0,
            self.clip_end_seconds(candidate) - FINE_CLIP_SECONDS,
        )

    def fine_marker_times(
        self, extract_start: float, candidate: ClipCandidate
    ) -> tuple[float, float]:
        clip_start = self.clip_start_seconds(candidate)
        clip_end = self.clip_end_seconds(candidate)
        rel_start = clip_start - extract_start
        rel_end = clip_end - extract_start
        return rel_start, rel_end

    def displayed_fine_start_extract(self) -> float | None:
        return self._displayed_fine_start_extract

    def displayed_fine_end_extract(self) -> float | None:
        return self._displayed_fine_end_extract

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

    def _fine_start_padding_insufficient(
        self, candidate: ClipCandidate, extract_start: float
    ) -> bool:
        rel_start, _rel_end = self.fine_marker_times(extract_start, candidate)
        return self._fine_marker_padding_insufficient(rel_start)

    def _fine_end_padding_insufficient(
        self, candidate: ClipCandidate, extract_start: float
    ) -> bool:
        _rel_start, rel_end = self.fine_marker_times(extract_start, candidate)
        return self._fine_marker_padding_insufficient(rel_end)

    def needs_basic_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_basic_viewport is None:
            return True
        viewport_start, viewport_duration = self._displayed_basic_viewport
        return self._viewport_padding_insufficient(
            candidate, viewport_start, viewport_duration
        )

    def needs_fine_start_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_fine_start_extract is None:
            return True
        return self._fine_start_padding_insufficient(
            candidate, self._displayed_fine_start_extract
        )

    def needs_fine_end_regen(self, candidate: ClipCandidate) -> bool:
        if self._displayed_fine_end_extract is None:
            return True
        return self._fine_end_padding_insufficient(
            candidate, self._displayed_fine_end_extract
        )

    # --- in-memory cache ---

    def clear_cache(self) -> None:
        self._displayed_basic_viewport = None
        self._displayed_fine_start_extract = None
        self._displayed_fine_end_extract = None
        self._clip_basic_states.clear()
        self._clip_fine_start_states.clear()
        self._clip_fine_end_states.clear()
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

    def try_reuse_fine_start(self, candidate: ClipCandidate) -> FineWaveformState | None:
        stored = self._clip_fine_start_states.get(candidate.clip_id)
        if stored is None or not stored.path.exists():
            return None
        if self._fine_start_padding_insufficient(candidate, stored.extract_start):
            return None
        return stored

    def try_reuse_fine_end(self, candidate: ClipCandidate) -> FineWaveformState | None:
        stored = self._clip_fine_end_states.get(candidate.clip_id)
        if stored is None or not stored.path.exists():
            return None
        if self._fine_end_padding_insufficient(candidate, stored.extract_start):
            return None
        return stored

    def fine_pair_ready(self, candidate: ClipCandidate) -> bool:
        start = self._clip_fine_start_states.get(candidate.clip_id)
        end = self._clip_fine_end_states.get(candidate.clip_id)
        if start is None or end is None:
            return False
        if not start.path.exists() or not end.path.exists():
            return False
        if self._fine_start_padding_insufficient(candidate, start.extract_start):
            return False
        if self._fine_end_padding_insufficient(candidate, end.extract_start):
            return False
        return True

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

    def record_fine_start_display(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> FineWaveformState:
        if extract_start is None:
            extract_start = self.fine_start_extract_start(candidate)
        self._displayed_fine_start_extract = extract_start
        state = FineWaveformState(
            path=path,
            extract_start=extract_start,
            media_duration=media_duration,
        )
        self._clip_fine_start_states[candidate.clip_id] = state
        return state

    def record_fine_end_display(
        self,
        candidate: ClipCandidate,
        path: Path,
        *,
        media_duration: float | None = None,
        extract_start: float | None = None,
    ) -> FineWaveformState:
        if extract_start is None:
            extract_start = self.fine_end_extract_start(candidate)
        self._displayed_fine_end_extract = extract_start
        state = FineWaveformState(
            path=path,
            extract_start=extract_start,
            media_duration=media_duration,
        )
        self._clip_fine_end_states[candidate.clip_id] = state
        return state

    def store_fine_pregen(
        self,
        clip_id: str,
        *,
        generation: int,
        start_state: FineWaveformState,
        end_state: FineWaveformState,
    ) -> None:
        if not self.is_fine_pregen_current(generation):
            return
        self._clip_fine_start_states[clip_id] = start_state
        self._clip_fine_end_states[clip_id] = end_state

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

    def cancel_fine_start_debounce(self) -> None:
        self._cancel_timer(self._fine_start_debounce_cancel)
        self._fine_start_debounce_cancel = None
        self._pending_fine_start_clip_id = None

    def cancel_fine_end_debounce(self) -> None:
        self._cancel_timer(self._fine_end_debounce_cancel)
        self._fine_end_debounce_cancel = None
        self._pending_fine_end_clip_id = None

    def cancel_fine_debounce(self) -> None:
        self.cancel_fine_start_debounce()
        self.cancel_fine_end_debounce()

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

    def schedule_fine_start_feedback(
        self,
        clip_id: str,
        on_fire: Callable[[str], None],
    ) -> None:
        self._pending_fine_start_clip_id = clip_id
        self._cancel_timer(self._fine_start_debounce_cancel)
        self._fine_start_debounce_cancel = None

        def fire() -> None:
            self._fine_start_debounce_cancel = None
            pending_id = self._pending_fine_start_clip_id
            self._pending_fine_start_clip_id = None
            if pending_id is None:
                return
            on_fire(pending_id)

        self._fine_start_debounce_cancel = self._schedule(
            WAVEFORM_DEBOUNCE_SECONDS,
            fire,
            "fine-debounce",
        )

    def schedule_fine_end_feedback(
        self,
        clip_id: str,
        on_fire: Callable[[str], None],
    ) -> None:
        self._pending_fine_end_clip_id = clip_id
        self._cancel_timer(self._fine_end_debounce_cancel)
        self._fine_end_debounce_cancel = None

        def fire() -> None:
            self._fine_end_debounce_cancel = None
            pending_id = self._pending_fine_end_clip_id
            self._pending_fine_end_clip_id = None
            if pending_id is None:
                return
            on_fire(pending_id)

        self._fine_end_debounce_cancel = self._schedule(
            WAVEFORM_DEBOUNCE_SECONDS,
            fire,
            "fine-end-debounce",
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
