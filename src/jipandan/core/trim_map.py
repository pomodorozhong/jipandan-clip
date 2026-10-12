"""Locate the PCM samples retained by FFmpeg on the original clip timeline."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def retained_ranges(source_path: Path, retained_path: Path) -> dict:
    """Match unchanged PCM runs, before the lossy export encode.

    Silence removal copies samples. Comparing its input and output avoids a
    second silence detector disagreeing with FFmpeg's windows and hold times.
    Identical repeated samples (especially digital silence) have equivalent
    positions; prefer the earliest forward match, anchored on audible samples.
    """
    with wave.open(str(source_path), "rb") as original, wave.open(str(retained_path), "rb") as rendered:
        if original.getparams()[:3] != rendered.getparams()[:3] or original.getsampwidth() != 4:
            raise ValueError("Trim mapping requires matching 32-bit PCM formats")
        channels, _, rate = original.getparams()[:3]
        source = original.readframes(original.getnframes())
        kept = rendered.readframes(rendered.getnframes())
    width = channels * 4
    source_samples = np.frombuffer(source, dtype="<i4").reshape(-1, channels)
    kept_samples = np.frombuffer(kept, dtype="<i4").reshape(-1, channels)
    source_count, kept_count = len(source_samples), len(kept_samples)
    source_cursor = kept_cursor = 0
    spans: list[tuple[int, int]] = []
    while kept_cursor < kept_count:
        # A run of zero samples alone is ambiguous. Include the first nonzero
        # sample in the search so retained leading silence stays by its speech.
        nonzero = np.flatnonzero(np.any(kept_samples[kept_cursor:kept_cursor + rate] != 0, axis=1))
        offset = int(nonzero[0]) if nonzero.size else 0
        anchor = kept_cursor + offset
        length = min(256, kept_count - anchor)
        found = -1
        while length:
            pattern = kept[anchor * width:(anchor + length) * width]
            position = source.find(pattern, (source_cursor + offset) * width)
            while position >= 0:
                start = position // width - offset
                if position % width == 0 and source[start * width:position] == kept[kept_cursor * width:anchor * width]:
                    found = start
                    break
                position = source.find(pattern, position + 1)
            if found >= 0:
                break
            length //= 2
        if found < 0:
            # Some FFmpeg builds insert a zero and repeat the previous sample
            # when flushing the start-silence buffer. These have no new source
            # position; keep the overlay on the original samples they surround.
            if source_cursor > 0:
                previous = source_samples[source_cursor - 1]
                if np.array_equal(kept_samples[kept_cursor], previous):
                    kept_cursor += 1
                    continue
                if (kept_cursor + 1 < kept_count and not np.any(kept_samples[kept_cursor])
                        and np.array_equal(kept_samples[kept_cursor + 1], previous)):
                    kept_cursor += 2
                    continue
            raise ValueError("Could not locate retained audio in the original PCM")
        count = min(source_count - found, kept_count - kept_cursor)
        # Bound comparison memory for long clips; advance until the first cut.
        matched = 0
        while matched < count:
            size = min(65_536, count - matched)
            different = np.flatnonzero(np.any(
                source_samples[found + matched:found + matched + size] !=
                kept_samples[kept_cursor + matched:kept_cursor + matched + size], axis=1,
            ))
            matched += int(different[0]) if different.size else size
            if different.size:
                break
        if matched == 0:
            raise ValueError("Invalid retained PCM match")
        if spans and spans[-1][1] == found:
            spans[-1] = (spans[-1][0], found + matched)
        else:
            spans.append((found, found + matched))
        source_cursor, kept_cursor = found + matched, kept_cursor + matched
    return {
        "source_duration_ms": source_count * 1000 / rate,
        "duration_ms": sum(end - start for start, end in spans) * 1000 / rate,
        "rendered_duration_ms": kept_count * 1000 / rate,
        "kept_ranges_ms": [[start * 1000 / rate, end * 1000 / rate] for start, end in spans],
    }
