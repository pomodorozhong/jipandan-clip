import { describe, expect, it } from "vitest";
import { formatDuration, formatPerClip, formatShare, type StageRow } from "./stageTimes";

const row = (ms: number, clips: number): StageRow => ({ stage: "triage", ms, views: clips, clips, changes: 0 });

describe("stage times", () => {
  it("formats durations at the scale they need", () => {
    expect(formatDuration(12_400)).toBe("12 s");
    expect(formatDuration(250_000)).toBe("4 min 10 s");
    expect(formatDuration(3_900_000)).toBe("1 h 05 min");
  });

  it("averages time per clip viewed", () => {
    expect(formatPerClip(row(7000, 2))).toBe("3.5 s");
    expect(formatPerClip(row(90_000, 3))).toBe("30 s");
    expect(formatPerClip(row(0, 0))).toBe("—");
  });

  it("shows each stage's share of the total", () => {
    expect(formatShare(row(25, 1), 100)).toBe("25%");
    expect(formatShare(row(0, 0), 0)).toBe("—");
  });
});
