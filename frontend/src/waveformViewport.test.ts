import { describe, expect, it } from "vitest";
import { boundedRange, initialRange, snapTabAt, waveformPanDelta } from "./WaveformEditor";

describe("shared waveform panning", () => {
  it("pads the clip with a little recording context and stops at real audio bounds", () => {
    expect(initialRange({ start_ms: 2000, end_ms: 4000 }, 10000)).toEqual({ start: 1700, end: 4300 });
    expect(initialRange({ start_ms: 2000, end_ms: 2500 }, 10000)).toEqual({ start: 1800, end: 2700 });
    expect(boundedRange(5000, 4000, 10000)).toEqual({ start: 5000, end: 9000 });
    expect(boundedRange(9000, 4000, 10000)).toEqual({ start: 6000, end: 10000 });
    expect(boundedRange(-1000, 4000, 10000)).toEqual({ start: 0, end: 4000 });
  });
  it("pans a zoomed render without allowing artificial space outside it", () => {
    expect(boundedRange(400, 1000, 2500)).toEqual({ start: 400, end: 1400 });
    expect(boundedRange(2400, 1000, 2500)).toEqual({ start: 1500, end: 2500 });
    expect(boundedRange(400, 2500, 2500)).toEqual({ start: 0, end: 2500 });
  });
  it("accepts diagonal trackpad swipes without consuming ordinary page scroll", () => {
    expect(waveformPanDelta({ deltaX: 20, deltaY: 30, shiftKey: false })).toBe(20);
    expect(waveformPanDelta({ deltaX: 0, deltaY: 30, shiftKey: false })).toBe(0);
    expect(waveformPanDelta({ deltaX: 0, deltaY: 30, shiftKey: true })).toBe(30);
  });
});

describe("snap point tabs", () => {
  const range = { start: 1000, end: 2000 };
  const snaps = { start: [1200, 1250, 1800], end: [1500] };

  it("finds the nearest start tab along the bottom and the end tab along the top", () => {
    expect(snapTabAt(snaps, range, { x: 245, y: 155 }, 10)).toEqual({ edge: "start", time: 1250 });
    expect(snapTabAt(snaps, range, { x: 503, y: 4 }, 10)).toEqual({ edge: "end", time: 1500 });
  });

  it("reaches a tab from further into the plot than it is drawn", () => {
    expect(snapTabAt(snaps, range, { x: 245, y: 130 }, 10)).toEqual({ edge: "start", time: 1250 });
    expect(snapTabAt(snaps, range, { x: 503, y: 30 }, 10)).toEqual({ edge: "end", time: 1500 });
  });

  it("leaves clicks away from the tabs to the waveform", () => {
    expect(snapTabAt(snaps, range, { x: 200, y: 80 }, 10)).toBeNull();
    expect(snapTabAt(snaps, range, { x: 500, y: 155 }, 10)).toBeNull();
    expect(snapTabAt(snaps, range, { x: 200, y: 4 }, 10)).toBeNull();
    expect(snapTabAt(undefined, range, { x: 200, y: 155 }, 10)).toBeNull();
  });
});
