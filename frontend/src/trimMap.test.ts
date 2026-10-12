import { describe, expect, it } from "vitest";
import { removedRanges, renderedTimeToSource, renderedRangeToSource, sourceTimeToRendered } from "./trimMap";

describe("original waveform trim overlay", () => {
  it("shows both removed edges and removed pauses on the original timeline", () => {
    expect(removedRanges({ source_duration_ms: 5000, duration_ms: 2000,
      kept_ranges_ms: [[800, 1800], [3000, 4000]] })).toEqual([[0, 800], [1800, 3000], [4000, 5000]]);
  });
  it("does not shade an unchanged clip or invent gaps between adjacent spans", () => {
    expect(removedRanges({ source_duration_ms: 2000, duration_ms: 2000,
      kept_ranges_ms: [[0, 1000], [1000, 2000]] })).toEqual([]);
  });
  it("maps preview selection through removed pauses and treats seam edges correctly", () => {
    const trim = { source_duration_ms: 5000, duration_ms: 2000, kept_ranges_ms: [[800, 1800], [3000, 4000]] as [number, number][] };
    expect(renderedTimeToSource(trim, 500, "start", 2000)).toBe(1300);
    expect(renderedTimeToSource(trim, 1500, "end", 2000)).toBe(3500);
    expect(renderedTimeToSource(trim, 1000, "start", 2000)).toBe(3000);
    expect(renderedTimeToSource(trim, 1000, "end", 2000)).toBe(1800);
    expect(renderedTimeToSource(trim, 2010, "end", 2010)).toBe(4000);
    expect(renderedRangeToSource(trim, 500, 2000, 2000, "start")).toEqual([1300, 5000]);
    expect(renderedRangeToSource(trim, 0, 1500, 2000, "end")).toEqual([0, 3500]);
  });
  it("maps original-timeline playback to the filtered audio while skipping removed gaps", () => {
    const trim = { source_duration_ms: 5000, duration_ms: 2000, kept_ranges_ms: [[800, 1800], [3000, 4000]] as [number, number][] };
    expect(sourceTimeToRendered(trim, 500, 2000)).toBe(0);
    expect(sourceTimeToRendered(trim, 1300, 2000)).toBe(500);
    expect(sourceTimeToRendered(trim, 2500, 2000)).toBe(1000);
    expect(sourceTimeToRendered(trim, 3500, 2000)).toBe(1500);
    expect(sourceTimeToRendered(trim, 5000, 2000)).toBe(2000);
  });
});
