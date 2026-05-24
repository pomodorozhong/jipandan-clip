from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubtitleEntry:
    index: int
    start: str
    end: str
    text: str


def srt_time_to_seconds(value: str) -> float:
    hhmmss, millis = value.split(",")
    hours, minutes, seconds = hhmmss.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def srt_time_to_ffmpeg(value: str) -> str:
    return value.replace(",", ".")


def seconds_to_ffmpeg_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def compute_duration(start: str, end: str) -> str:
    duration_seconds = max(0.0, srt_time_to_seconds(end) - srt_time_to_seconds(start))
    return f"{duration_seconds:.3f}"


def parse_srt(srt_path: Path) -> list[SubtitleEntry]:
    raw_text = srt_path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in raw_text.split("\n\n") if block.strip()]
    entries: list[SubtitleEntry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        if " --> " not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split(" --> ", maxsplit=1)]
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        entries.append(SubtitleEntry(index=index, start=start, end=end, text=text))
    return entries
