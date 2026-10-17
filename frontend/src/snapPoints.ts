import type { SnapPoints } from "./api";

export type SnapEdge = "start" | "end";

/** Start edges snap to Whisper word starts, end edges to voice-activity speech ends. */
export function snapTargets(points: SnapPoints | null, edge: SnapEdge): readonly number[] {
  if (!points) return [];
  return edge === "start" ? points.word_start : points.speech_end;
}

/** Index of the first target at or after `time` in sorted `targets`. */
function lowerBound(targets: readonly number[], time: number): number {
  let low = 0;
  let high = targets.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (targets[middle] < time) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** The target nearest to `time` when it is within `tolerance` ms, else null. */
export function nearestSnap(targets: readonly number[], time: number, tolerance: number): number | null {
  const index = lowerBound(targets, time);
  let best: number | null = null;
  for (const candidate of [targets[index - 1], targets[index]]) {
    if (candidate === undefined || Math.abs(candidate - time) > tolerance) continue;
    if (best === null || Math.abs(candidate - time) < Math.abs(best - time)) best = candidate;
  }
  return best;
}

/** The closest target strictly before (`direction` -1) or after (+1) `time`, else null. */
export function adjacentSnap(targets: readonly number[], time: number, direction: -1 | 1): number | null {
  if (direction > 0) return targets[lowerBound(targets, time + 1)] ?? null;
  return targets[lowerBound(targets, time) - 1] ?? null;
}

/** The targets inside [start, end]. */
export function snapsInRange(targets: readonly number[], start: number, end: number): readonly number[] {
  return targets.slice(lowerBound(targets, start), lowerBound(targets, end + 1));
}
