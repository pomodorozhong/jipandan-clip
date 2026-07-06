#!/usr/bin/env python3
"""Benchmark textual-plot waveform envelope generation."""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jipandan.core import ffmpeg
from jipandan.core.models import ClipCandidate, Session
from jipandan.core.srt import srt_time_to_seconds
from jipandan.core.waveform_envelope import (
    _DEFAULT_SAMPLE_RATE,
    decode_mp3_mono_f32,
    downsample_envelope,
    load_waveform_envelope,
)
from jipandan.tui.waveform_service import WAVEFORM_PADDING_SECONDS, WaveformService


@dataclass(frozen=True)
class ClipTiming:
    index: int
    duration: float
    padded_extract: float
    textual_plot_ms: float


@dataclass(frozen=True)
class BreakdownTiming:
    probe_ms: float
    decode_ms: float
    downsample_ms: float


def _noop_schedule(
    _delay: float, _callback: object, _name: str
) -> Callable[[], None]:
    return lambda: None


def stratified_sample(
    candidates: list[ClipCandidate], sample_size: int
) -> list[ClipCandidate]:
    if len(candidates) <= sample_size:
        return list(candidates)
    step = len(candidates) / sample_size
    return [candidates[int(i * step)] for i in range(sample_size)]


def _padded_extract_seconds(candidate: ClipCandidate) -> float:
    start = srt_time_to_seconds(candidate.start.replace(".", ","))
    end = srt_time_to_seconds(candidate.end.replace(".", ","))
    return (end - start) + 2 * WAVEFORM_PADDING_SECONDS


def _median_ms(samples: list[float]) -> float:
    return statistics.median(samples) * 1000.0


def _time_textual_plot(mp3: Path, *, buckets: int) -> tuple[float, BreakdownTiming]:
    total_start = time.perf_counter()

    probe_start = time.perf_counter()
    duration = ffmpeg.probe_duration_seconds(mp3)
    probe_elapsed = time.perf_counter() - probe_start

    decode_start = time.perf_counter()
    samples = decode_mp3_mono_f32(mp3, sample_rate=_DEFAULT_SAMPLE_RATE)
    decode_elapsed = time.perf_counter() - decode_start

    downsample_start = time.perf_counter()
    downsample_envelope(samples, duration, buckets)
    downsample_elapsed = time.perf_counter() - downsample_start

    total_elapsed = time.perf_counter() - total_start
    breakdown = BreakdownTiming(
        probe_ms=probe_elapsed * 1000.0,
        decode_ms=decode_elapsed * 1000.0,
        downsample_ms=downsample_elapsed * 1000.0,
    )
    return total_elapsed, breakdown


def _ensure_mp3(
    service: WaveformService, candidate: ClipCandidate, cache_dir: Path
) -> Path:
    service._cache_dir = cache_dir  # noqa: SLF001 — benchmark-only cache override
    cache_dir.mkdir(parents=True, exist_ok=True)
    mp3 = service.basic_cache_path(candidate, suffix=".mp3")
    if mp3.exists():
        mp3.unlink()
    extract_start, extract_duration = service.basic_extract_range(candidate)
    ffmpeg.extract_preview_fast(
        service.session.audio,
        extract_start,
        extract_duration,
        mp3,
    )
    return mp3


def _benchmark_render_only(
    service: WaveformService,
    candidates: list[ClipCandidate],
    *,
    buckets: int,
    iterations: int,
    cache_dir: Path,
) -> tuple[list[ClipTiming], list[BreakdownTiming]]:
    clip_timings: list[ClipTiming] = []
    breakdowns: list[BreakdownTiming] = []

    for candidate in candidates:
        mp3 = _ensure_mp3(service, candidate, cache_dir)
        plot_samples: list[float] = []
        breakdown_samples: list[BreakdownTiming] = []

        for _ in range(iterations):
            elapsed, breakdown = _time_textual_plot(mp3, buckets=buckets)
            plot_samples.append(elapsed)
            breakdown_samples.append(breakdown)

        clip_timings.append(
            ClipTiming(
                index=candidate.index,
                duration=float(candidate.duration),
                padded_extract=_padded_extract_seconds(candidate),
                textual_plot_ms=_median_ms(plot_samples),
            )
        )
        breakdowns.append(
            BreakdownTiming(
                probe_ms=statistics.median([b.probe_ms for b in breakdown_samples]),
                decode_ms=statistics.median([b.decode_ms for b in breakdown_samples]),
                downsample_ms=statistics.median(
                    [b.downsample_ms for b in breakdown_samples]
                ),
            )
        )

    return clip_timings, breakdowns


def _benchmark_full_pipeline(
    service: WaveformService,
    candidates: list[ClipCandidate],
    *,
    buckets: int,
    iterations: int,
    base_cache_dir: Path,
) -> list[ClipTiming]:
    clip_timings: list[ClipTiming] = []

    for candidate in candidates:
        plot_samples: list[float] = []

        for i in range(iterations):
            plot_dir = base_cache_dir / f"full-plot-{candidate.index}-{i}"
            plot_dir.mkdir(parents=True, exist_ok=True)
            extract_start, extract_duration = service.basic_extract_range(candidate)

            plot_mp3 = plot_dir / "preview.mp3"
            plot_start = time.perf_counter()
            ffmpeg.extract_preview_fast(
                service.session.audio,
                extract_start,
                extract_duration,
                plot_mp3,
            )
            load_waveform_envelope(plot_mp3, buckets=buckets)
            plot_samples.append(time.perf_counter() - plot_start)
            shutil.rmtree(plot_dir, ignore_errors=True)

        clip_timings.append(
            ClipTiming(
                index=candidate.index,
                duration=float(candidate.duration),
                padded_extract=_padded_extract_seconds(candidate),
                textual_plot_ms=_median_ms(plot_samples),
            )
        )

    return clip_timings


def _warmup(
    service: WaveformService,
    candidate: ClipCandidate,
    *,
    buckets: int,
    cache_dir: Path,
) -> None:
    mp3 = _ensure_mp3(service, candidate, cache_dir / "warmup")
    load_waveform_envelope(mp3, buckets=buckets)


def _summarize(label: str, timings: list[ClipTiming]) -> None:
    plot_ms = [t.textual_plot_ms for t in timings]
    print(f"\n{label}:")
    print(
        f"  textual-plot   mean: {statistics.mean(plot_ms):6.1f} ms  "
        f"median: {statistics.median(plot_ms):6.1f} ms"
    )


def _print_clip_table(timings: list[ClipTiming]) -> None:
    print("\nPer-clip timings (median ms):")
    print(f"{'clip':>6}  {'dur':>5}  {'extract':>7}  {'textual-plot':>12}")
    for t in timings:
        print(
            f"{t.index:6d}  {t.duration:5.1f}  {t.padded_extract:7.1f}  "
            f"{t.textual_plot_ms:12.1f}"
        )


def _print_breakdown(breakdowns: list[BreakdownTiming]) -> None:
    probe = statistics.mean([b.probe_ms for b in breakdowns])
    decode = statistics.mean([b.decode_ms for b in breakdowns])
    downsample = statistics.mean([b.downsample_ms for b in breakdowns])
    print("\nTextual-plot breakdown (render-only, mean across clips):")
    print(f"  probe: {probe:.1f} ms | decode: {decode:.1f} ms | downsample: {downsample:.1f} ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Input audio file path")
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Session JSON path (default: {audio}.jipandan.json)",
    )
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--buckets", type=int, default=800)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--mode",
        choices=("render-only", "full", "both"),
        default="both",
    )
    args = parser.parse_args(argv)

    audio = args.audio.resolve()
    session_path = (args.session or audio.with_suffix(".jipandan.json")).resolve()
    if not audio.exists():
        print(f"Audio not found: {audio}", file=sys.stderr)
        return 1
    if not session_path.exists():
        print(f"Session not found: {session_path}", file=sys.stderr)
        return 1

    session = Session.load(session_path)
    session.audio = audio
    candidates = stratified_sample(session.candidates, args.sample_size)

    cache_root = Path("tmp/benchmark-waveform")
    cache_root.mkdir(parents=True, exist_ok=True)

    service = WaveformService(session, cache_root, schedule=_noop_schedule)

    print(
        f"Waveform benchmark — {audio.name} "
        f"({len(candidates)} clips, buckets={args.buckets}, {args.iterations} iterations)"
    )

    _warmup(service, candidates[0], buckets=args.buckets, cache_dir=cache_root)

    if args.mode in ("render-only", "both"):
        render_dir = cache_root / "render-only"
        if render_dir.exists():
            shutil.rmtree(render_dir)
        render_timings, breakdowns = _benchmark_render_only(
            service,
            candidates,
            buckets=args.buckets,
            iterations=args.iterations,
            cache_dir=render_dir,
        )
        _summarize("Render-only (MP3 → envelope)", render_timings)
        _print_clip_table(render_timings)
        if breakdowns:
            _print_breakdown(breakdowns)

    if args.mode in ("full", "both"):
        full_dir = cache_root / "full"
        if full_dir.exists():
            shutil.rmtree(full_dir)
        full_timings = _benchmark_full_pipeline(
            service,
            candidates,
            buckets=args.buckets,
            iterations=args.iterations,
            base_cache_dir=full_dir,
        )
        _summarize("Full pipeline (extract + envelope)", full_timings)
        if args.mode == "full":
            _print_clip_table(full_timings)

    print("\nNote: PlotWidget terminal rendering is not timed (data generation only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
