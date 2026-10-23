import type { Clip, ReviewRound, Status } from "./api";
import { unitHash } from "./reviewOrder";

// While a review round is open, the whole app works on its clips only; see doc/app-rebuild-plan.md, "Review rounds".
export const ROUND_DEFAULT_SIZE = 300;
export const ROUND_MIN_SIZE = 10;
export const ROUND_MAX_SIZE = 5000;
export const ROUND_SIZES = [100, 200, 300, 500];
// Every round starts at 20% random; a share picked for one round is not carried to the next.
export const ROUND_RANDOM_SHARE = 0.2;

export function isRoundOpen(round: ReviewRound | null | undefined): round is ReviewRound {
  return Boolean(round);
}

/** The clips the app shows: only the round's while one is open, otherwise all of them. */
export function scopeClips(clips: Clip[], open: boolean): Clip[] {
  return open ? clips.filter((clip) => clip.round_role) : clips;
}

/**
 * Order a round's clips the same way on every screen: shuffled by the round's seed, not by score, so a
 * random pick's place in the list doesn't give it away. Clips split off one clip stay together.
 */
export function orderRound<T extends Pick<Clip, "index" | "suffix">>(clips: T[], seed: string): T[] {
  const keys = new Map(clips.map((clip) => [clip.index, unitHash(`${seed}:order:${clip.index}`)]));
  return [...clips].sort((a, b) => keys.get(a.index)! - keys.get(b.index)! || a.index - b.index || a.suffix - b.suffix);
}

export function countStatuses(clips: Clip[]): Record<Status, number> {
  const counts: Record<Status, number> = { pending: 0, group1: 0, group2: 0, exported: 0, rejected: 0 };
  for (const clip of clips) counts[clip.status] += 1;
  return counts;
}

/** A round clip is done once it is exported or rejected. */
export function countDone(clips: Clip[]): number {
  return clips.filter((clip) => clip.status === "exported" || clip.status === "rejected").length;
}

export function isProcessed(clips: Clip[]): boolean {
  return clips.length > 0 && countDone(clips) === clips.length;
}

export function normalizeRoundSize(value: unknown): number {
  const size = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : ROUND_DEFAULT_SIZE;
  return Math.min(ROUND_MAX_SIZE, Math.max(ROUND_MIN_SIZE, size));
}

/** How closely `labels` random decisions pin a keep rate: the 95% interval at 50%, in points. */
export function marginPoints(labels: number): number | null {
  return labels > 0 ? Math.round(98 / Math.sqrt(labels)) : null;
}

export interface ShareWarning {
  tone: "danger" | "caution" | "info";
  title: string;
  text: string;
}

/** Warn when a round's random share would hurt the data, or cost review time. */
export function randomShareWarning(share: number, randomCount: number): ShareWarning | null {
  if (randomCount === 0) return {
    tone: "danger", title: "No random clips.",
    text: "Nothing in this round can check or improve Likely keep, and the estimate of the stream's keepers stops getting more precise.",
  };
  if (share < 0.1 || randomCount < 30) return {
    tone: "caution", title: "Too few random clips.",
    text: `${randomCount} random clips pin the stream's keep rate only to about ±${marginPoints(randomCount)} points; 60 (20% of 300) give ±13.`,
  };
  if (share > 0.5) return {
    tone: "info", title: "Mostly random.",
    text: "The data stays fair, but more of your time goes to clips Likely keep ranks low, so fewer keepers per hour.",
  };
  return null;
}

/** A share of the stream's keepers as a whole percentage, or null while it is unknown. */
export function formatPercent(share: number | null): string | null {
  return share === null ? null : `${Math.round(share * 100)}%`;
}

/** The clock time `ms` from `now`, as 24-hour "HH:MM". */
export function finishClock(now: Date, ms: number): string {
  const end = new Date(now.getTime() + ms);
  return `${String(end.getHours()).padStart(2, "0")}:${String(end.getMinutes()).padStart(2, "0")}`;
}
