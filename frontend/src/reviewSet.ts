import type { Clip, ReviewSet, Status } from "./api";
import { unitHash } from "./reviewOrder";

// While a review set is open, the whole app works on its clips only; see doc/app-rebuild-plan.md, "Review sets".
export const REVIEW_SET_DEFAULT_SIZE = 300;
export const REVIEW_SET_MIN_SIZE = 10;
export const REVIEW_SET_MAX_SIZE = 5000;

export function isReviewSetOpen(reviewSet: ReviewSet | null | undefined): reviewSet is ReviewSet {
  return Boolean(reviewSet && !reviewSet.completed);
}

/** The clips the app shows: only the set's while a set is open, otherwise all of them. */
export function scopeClips(clips: Clip[], open: boolean): Clip[] {
  return open ? clips.filter((clip) => clip.review_set) : clips;
}

/**
 * Order a set's clips the same way on every screen: shuffled by the set's seed, not by score, so a
 * random pick's place in the list doesn't give it away. Clips split off one clip stay together.
 */
export function orderReviewSet<T extends Pick<Clip, "index" | "suffix">>(clips: T[], seed: string): T[] {
  const keys = new Map(clips.map((clip) => [clip.index, unitHash(`${seed}:order:${clip.index}`)]));
  return [...clips].sort((a, b) => keys.get(a.index)! - keys.get(b.index)! || a.index - b.index || a.suffix - b.suffix);
}

export function countStatuses(clips: Clip[]): Record<Status, number> {
  const counts: Record<Status, number> = { pending: 0, group1: 0, group2: 0, exported: 0, rejected: 0 };
  for (const clip of clips) counts[clip.status] += 1;
  return counts;
}

/** A set is processed once every clip in it is exported or rejected. */
export function isProcessed(clips: Clip[]): boolean {
  return clips.length > 0 && clips.every((clip) => clip.status === "exported" || clip.status === "rejected");
}

export function normalizeReviewSetSize(value: unknown): number {
  const size = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : REVIEW_SET_DEFAULT_SIZE;
  return Math.min(REVIEW_SET_MAX_SIZE, Math.max(REVIEW_SET_MIN_SIZE, size));
}
