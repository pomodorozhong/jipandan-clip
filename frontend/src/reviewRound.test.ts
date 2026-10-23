import { describe, expect, it } from "vitest";
import type { Clip } from "./api";
import {
  countDone, countStatuses, finishClock, isProcessed, isRoundOpen, normalizeRoundSize, orderRound, randomShareWarning,
  scopeClips,
} from "./reviewRound";

const clip = (id: string, status: Clip["status"], role: Clip["round_role"]) => ({ clip_id: id, status, round_role: role }) as Clip;

describe("review rounds", () => {
  const clips = [clip("1", "pending", "top"), clip("2", "rejected", "random"), clip("3", "pending", null)];

  it("shows only the round's clips while it is open", () => {
    expect(scopeClips(clips, true).map((item) => item.clip_id)).toEqual(["1", "2"]);
    expect(scopeClips(clips, false)).toHaveLength(3);
    expect(countStatuses(scopeClips(clips, true))).toEqual({ pending: 1, group1: 0, group2: 0, exported: 0, rejected: 1 });
  });

  it("is done once every clip is exported or rejected", () => {
    expect(isProcessed([clip("1", "exported", "top"), clip("2", "rejected", "random")])).toBe(true);
    expect(isProcessed([clip("1", "group2", "top")])).toBe(false);
    expect(isProcessed([])).toBe(false);
    expect(countDone(clips)).toBe(1);
  });

  it("is open while the session has one", () => {
    expect(isRoundOpen({ number: 1, size: 300, random_share: 0.2, seed: "abc", started: null, unprocessed: 3 })).toBe(true);
    expect(isRoundOpen(null)).toBe(false);
  });

  it("keeps the round size in range", () => {
    expect(normalizeRoundSize(250.4)).toBe(250);
    expect(normalizeRoundSize(3)).toBe(10);
    expect(normalizeRoundSize("x")).toBe(300);
  });

  it("warns when the random share hurts the data or costs time", () => {
    expect(randomShareWarning(0.2, 60)).toBeNull();
    expect(randomShareWarning(0, 0)?.tone).toBe("danger");
    expect(randomShareWarning(0.05, 15)).toMatchObject({ tone: "caution", text: expect.stringContaining("±25 points") });
    // 20% of 100 clips is still too few random clips to estimate from.
    expect(randomShareWarning(0.2, 20)?.tone).toBe("caution");
    expect(randomShareWarning(0.6, 180)?.tone).toBe("info");
  });

  it("gives the finish time as a clock time", () => {
    expect(finishClock(new Date(2026, 9, 23, 14, 0), 2.5 * 3600_000)).toBe("16:30");
  });

  describe("order", () => {
    // Scores rise with the index, so a score order would be the reverse of clip order.
    const round = Array.from({ length: 300 }, (_, index) => ({ index: index + 1, suffix: 0, likely_keep: index }));
    const indexes = (items: { index: number; suffix: number }[]) => items.map((item) => `${item.index}-${item.suffix}`);

    it("shuffles the round by its seed, not by score", () => {
      const ordered = orderRound(round, "seed-a");
      expect([...indexes(ordered)].sort()).toEqual([...indexes(round)].sort());
      expect(indexes(orderRound([...round].reverse(), "seed-a"))).toEqual(indexes(ordered));
      expect(indexes(orderRound(round, "seed-b"))).not.toEqual(indexes(ordered));
      expect(indexes(ordered)).not.toEqual(indexes(round));
      expect(indexes(ordered)).not.toEqual(indexes([...round].reverse()));
    });

    it("keeps the same relative order on every screen", () => {
      const all = orderRound(round, "seed-a");
      const someLeft = orderRound(round.filter((item) => item.index % 3 === 0), "seed-a");
      expect(indexes(someLeft)).toEqual(indexes(all.filter((item) => item.index % 3 === 0)));
    });

    it("keeps clips split off one clip together", () => {
      const withSplits = [...round, { index: 10, suffix: 2, likely_keep: 0 }, { index: 10, suffix: 1, likely_keep: 0 }];
      const ordered = indexes(orderRound(withSplits, "seed-a"));
      const at = ordered.indexOf("10-0");
      expect(ordered.slice(at, at + 3)).toEqual(["10-0", "10-1", "10-2"]);
    });
  });
});
