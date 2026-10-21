import { describe, expect, it } from "vitest";
import type { Clip } from "./api";
import { countStatuses, isProcessed, isReviewSetOpen, normalizeReviewSetSize, orderReviewSet, scopeClips } from "./reviewSet";

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
    const set = { size: 300, total: 1000, random_share: 0.2, seed: "abc", unprocessed: 3, completed: null };
    expect(isReviewSetOpen(set)).toBe(true);
    expect(isReviewSetOpen({ ...set, completed: { t: "2026-10-21T10:00:00Z", unprocessed: 0 } })).toBe(false);
    expect(isReviewSetOpen(null)).toBe(false);
  });

  it("keeps the set size in range", () => {
    expect(normalizeReviewSetSize(250.4)).toBe(250);
    expect(normalizeReviewSetSize(3)).toBe(10);
    expect(normalizeReviewSetSize("x")).toBe(300);
  });

  describe("order", () => {
    // Scores rise with the index, so a score order would be the reverse of clip order.
    const set = Array.from({ length: 300 }, (_, index) => ({ index: index + 1, suffix: 0, likely_keep: index }));
    const indexes = (clips: { index: number; suffix: number }[]) => clips.map((item) => `${item.index}-${item.suffix}`);

    it("shuffles the set by its seed, not by score", () => {
      const ordered = orderReviewSet(set, "seed-a");
      expect([...indexes(ordered)].sort()).toEqual([...indexes(set)].sort());
      expect(indexes(orderReviewSet([...set].reverse(), "seed-a"))).toEqual(indexes(ordered));
      expect(indexes(orderReviewSet(set, "seed-b"))).not.toEqual(indexes(ordered));
      expect(indexes(ordered)).not.toEqual(indexes(set));
      expect(indexes(ordered)).not.toEqual(indexes([...set].reverse()));
    });

    it("keeps the same relative order on every screen", () => {
      const all = orderReviewSet(set, "seed-a");
      const someLeft = orderReviewSet(set.filter((item) => item.index % 3 === 0), "seed-a");
      expect(indexes(someLeft)).toEqual(indexes(all.filter((item) => item.index % 3 === 0)));
    });

    it("keeps clips split off one clip together", () => {
      const withSplits = [...set, { index: 10, suffix: 2, likely_keep: 0 }, { index: 10, suffix: 1, likely_keep: 0 }];
      const ordered = indexes(orderReviewSet(withSplits, "seed-a"));
      const at = ordered.indexOf("10-0");
      expect(ordered.slice(at, at + 3)).toEqual(["10-0", "10-1", "10-2"]);
    });
  });
});
