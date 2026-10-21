import { describe, expect, it } from "vitest";
import type { Clip } from "./api";
import { countStatuses, isProcessed, isReviewSetOpen, normalizeReviewSetSize, scopeClips } from "./reviewSet";

const clip = (id: string, status: Clip["status"], role: Clip["review_set"]) => ({ clip_id: id, status, review_set: role }) as Clip;

describe("review sets", () => {
  const clips = [clip("1", "pending", "top"), clip("2", "rejected", "random"), clip("3", "pending", null)];

  it("shows only the set's clips while it is open", () => {
    expect(scopeClips(clips, true).map((item) => item.clip_id)).toEqual(["1", "2"]);
    expect(scopeClips(clips, false)).toHaveLength(3);
    expect(countStatuses(scopeClips(clips, true))).toEqual({ pending: 1, group1: 0, group2: 0, exported: 0, rejected: 1 });
  });

  it("is processed once every clip is exported or rejected", () => {
    expect(isProcessed([clip("1", "exported", "top"), clip("2", "rejected", "random")])).toBe(true);
    expect(isProcessed([clip("1", "group2", "top")])).toBe(false);
    expect(isProcessed([])).toBe(false);
  });

  it("is open until completed", () => {
    const set = { size: 300, total: 1000, random_share: 0.2, unprocessed: 3, completed: null };
    expect(isReviewSetOpen(set)).toBe(true);
    expect(isReviewSetOpen({ ...set, completed: { t: "2026-10-21T10:00:00Z", unprocessed: 0 } })).toBe(false);
    expect(isReviewSetOpen(null)).toBe(false);
  });

  it("keeps the set size in range", () => {
    expect(normalizeReviewSetSize(250.4)).toBe(250);
    expect(normalizeReviewSetSize(3)).toBe(10);
    expect(normalizeReviewSetSize("x")).toBe(300);
  });
});
