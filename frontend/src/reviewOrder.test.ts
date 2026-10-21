import { describe, expect, it } from "vitest";
import { EXPLORE_RATE, isExploreClip, orderByLikelyKeep } from "./reviewOrder";

describe("likely keep exploration", () => {
  const ids = Array.from({ length: 4000 }, (_, index) => String(index + 1));

  it("picks a stable share of clips per session", () => {
    const picked = ids.filter((id) => isExploreClip("session-a", id));
    expect(picked.length / ids.length).toBeGreaterThan(EXPLORE_RATE * 0.7);
    expect(picked.length / ids.length).toBeLessThan(EXPLORE_RATE * 1.3);
    expect(ids.filter((id) => isExploreClip("session-a", id))).toEqual(picked);
    expect(ids.filter((id) => isExploreClip("session-b", id))).not.toEqual(picked);
  });

  it("does not pick neighbouring clip IDs together", () => {
    const picked = new Set(ids.filter((id) => isExploreClip("session-a", id)));
    const withPickedNeighbour = [...picked].filter((id) => picked.has(String(Number(id) + 1))).length;
    expect(withPickedNeighbour / picked.size).toBeLessThan(EXPLORE_RATE * 3);
  });

  const clips = ids.map((id, index) => ({ clip_id: id, likely_keep: 100 - (index % 1000) / 10 }));
  const byId = (a: { clip_id: string }, b: { clip_id: string }) => Number(a.clip_id) - Number(b.clip_id);

  it("places picks at about 1 in 20 at every depth of the list", () => {
    const ordered = orderByLikelyKeep(clips, "session-a", true, byId);
    expect(ordered).toHaveLength(clips.length);
    for (let start = 0; start < ordered.length; start += 1000) {
      const window = ordered.slice(start, start + 1000);
      const share = window.filter((clip) => isExploreClip("session-a", clip.clip_id)).length / window.length;
      expect(share).toBeGreaterThan(EXPLORE_RATE * 0.5);
      expect(share).toBeLessThan(EXPLORE_RATE * 1.6);
    }
    const regular = ordered.filter((clip) => !isExploreClip("session-a", clip.clip_id));
    expect(regular.map((clip) => clip.clip_id))
      .toEqual([...regular].sort((a, b) => b.likely_keep - a.likely_keep || byId(a, b)).map((clip) => clip.clip_id));
  });

  it("orders purely by score when exploration is off", () => {
    const ordered = orderByLikelyKeep(clips, "session-a", false, byId);
    expect(ordered.map((clip) => clip.clip_id))
      .toEqual([...clips].sort((a, b) => b.likely_keep - a.likely_keep || byId(a, b)).map((clip) => clip.clip_id));
    expect(orderByLikelyKeep(clips, null, true, byId)).toEqual(ordered);
  });
});
