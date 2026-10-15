import { describe, expect, it } from "vitest";
import { applySessionDelta, type Clip, type Session } from "./api";

const clip = (clip_id: string, index: number, suffix = 0, status: Clip["status"] = "pending") => ({
  clip_id, index, suffix, status, title: clip_id,
} as Clip);

const session = {
  revision: 4, can_undo: false, candidates: [clip("1", 1), clip("2", 2), clip("2-2", 2, 2), clip("3", 3)],
  counts: { pending: 4, group1: 0, group2: 0, exported: 0, rejected: 0 },
} as unknown as Session;

describe("applySessionDelta", () => {
  it("replaces changed clips in place and updates counts", () => {
    const next = applySessionDelta(session, {
      delta: true, revision: 5, can_undo: true, removed: [],
      counts: { ...session.counts, pending: 3, rejected: 1 }, clips: [clip("2", 2, 0, "rejected")],
    });
    expect(next.candidates.map((c) => `${c.clip_id}:${c.status}`)).toEqual(["1:pending", "2:rejected", "2-2:pending", "3:pending"]);
    expect([next.revision, next.can_undo, next.counts.rejected]).toEqual([5, true, 1]);
    expect(session.candidates[1].status).toBe("pending");
  });

  it("inserts new clips in clip order and drops removed ones", () => {
    const next = applySessionDelta(session, {
      delta: true, revision: 5, can_undo: true, counts: session.counts, removed: ["2-2"],
      clips: [clip("1-2", 1, 2)], created_clip_id: "1-2",
    });
    expect(next.candidates.map((c) => c.clip_id)).toEqual(["1", "1-2", "2", "3"]);
    expect(next.created_clip_id).toBe("1-2");
  });
});
