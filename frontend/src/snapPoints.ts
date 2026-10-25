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

/** How far past the pointer an edge may still snap: a start to a slightly later point, an end to a slightly earlier one. */
export const SNAP_SLACK_MS = 50;

/**
 * The target an edge dragged to `time` snaps to, within `tolerance` ms, else null. A start only snaps
 * to a point at or before the pointer and an end to one at or after it (give or take `SNAP_SLACK_MS`),
 * so snapping never cuts into speech: a late start or an early end clips the voice, while an early
 * start or a late end only adds silence, which the export's edge trim removes.
 */
export function edgeSnap(targets: readonly number[], time: number, tolerance: number, edge: SnapEdge): number | null {
  const slack = Math.min(SNAP_SLACK_MS, tolerance);
  if (edge === "start") {
    const candidate = targets[lowerBound(targets, time + slack + 1) - 1];
    return candidate !== undefined && time - candidate <= tolerance ? candidate : null;
  }
  const candidate = targets[lowerBound(targets, time - slack)];
  return candidate !== undefined && candidate - time <= tolerance ? candidate : null;
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
