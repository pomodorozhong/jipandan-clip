import type { TrimMap } from "./api";

/** A cut at a retained-span seam starts in the next span and ends in the previous one. */
export function renderedTimeToSource(trim: TrimMap, time: number, edge: "start" | "end", renderedDuration: number): number {
  const retainedDuration = trim.kept_ranges_ms.reduce((sum, [start, end]) => sum + end - start, 0);
  const target = Math.max(0, Math.min(retainedDuration, time / Math.max(1, renderedDuration) * retainedDuration));
  let cursor = 0;
  for (const [start, end] of trim.kept_ranges_ms) {
    const next = cursor + end - start;
    if (target < next || (target === next && edge === "end")) return start + target - cursor;
    cursor = next;
  }
  return trim.kept_ranges_ms.at(-1)?.[1] ?? 0;
}

export function renderedRangeToSource(trim: TrimMap, start: number, end: number, duration: number, edge?: "start" | "end"): [number, number] {
  return [edge === "end" ? 0 : renderedTimeToSource(trim, start, "start", duration),
    edge === "start" ? trim.source_duration_ms : renderedTimeToSource(trim, end, "end", duration)];
}

/** Seek on the original timeline, skipping a removed pause to the next retained sample. */
export function sourceTimeToRendered(trim: TrimMap, time: number, renderedDuration: number): number {
  const retainedDuration = trim.kept_ranges_ms.reduce((sum, [start, end]) => sum + end - start, 0);
  let cursor = 0;
  for (const [start, end] of trim.kept_ranges_ms) {
    if (time <= start) break;
    if (time < end) { cursor += time - start; break; }
    cursor += end - start;
  }
  return retainedDuration ? cursor / retainedDuration * renderedDuration : 0;
}

/** Complement of retained PCM spans, on the uncompressed original timeline. */
export function removedRanges(trim: TrimMap): [number, number][] {
  const removed: [number, number][] = [];
  let cursor = 0;
  for (const [start, end] of trim.kept_ranges_ms) {
    if (start > cursor) removed.push([cursor, start]);
    cursor = end;
  }
  if (cursor < trim.source_duration_ms) removed.push([cursor, trim.source_duration_ms]);
  return removed;
}
