import { describe, expect, it } from "vitest";
import { boundedRange, initialRange, waveformPanDelta } from "./WaveformEditor";

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
