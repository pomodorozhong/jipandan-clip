import { describe, expect, it } from "vitest";
import { adjacentSnap, edgeSnap, nearestSnap, snapsInRange, snapTargets } from "./snapPoints";

const targets = [1000, 2000, 2600];

describe("clip edge snap points", () => {
  it("uses word starts for the start edge and speech ends for the end edge", () => {
    const points = { word_start: [1], speech_end: [2] };
    expect(snapTargets(points, "start")).toEqual([1]);
    expect(snapTargets(points, "end")).toEqual([2]);
    expect(snapTargets(null, "start")).toEqual([]);
  });
  it("snaps to the nearest point only within the tolerance", () => {
    expect(nearestSnap(targets, 2350, 400)).toBe(2600);
    expect(nearestSnap(targets, 2250, 400)).toBe(2000);
    expect(nearestSnap(targets, 1500, 400)).toBeNull();
    expect(nearestSnap([], 1500, 400)).toBeNull();
  });
  it("snaps a start only to a point at or before it, within a little slack", () => {
    expect(edgeSnap(targets, 2350, 400, "start")).toBe(2000);
    expect(edgeSnap(targets, 2580, 400, "start")).toBe(2600);
    expect(edgeSnap(targets, 2540, 400, "start")).toBeNull();
    expect(edgeSnap(targets, 1950, 400, "start")).toBe(2000);
    expect(edgeSnap(targets, 1300, 400, "start")).toBe(1000);
    expect(edgeSnap([], 1500, 400, "start")).toBeNull();
  });
  it("snaps an end only to a point at or after it, within a little slack", () => {
    expect(edgeSnap(targets, 2250, 400, "end")).toBe(2600);
    expect(edgeSnap(targets, 2040, 400, "end")).toBe(2000);
    expect(edgeSnap(targets, 2060, 400, "end")).toBeNull();
    expect(edgeSnap(targets, 2060, 600, "end")).toBe(2600);
    expect(edgeSnap(targets, 2700, 400, "end")).toBeNull();
  });
  it("never lets the slack reach past the tolerance", () => {
    expect(edgeSnap(targets, 1980, 10, "start")).toBeNull();
    expect(edgeSnap(targets, 1995, 10, "start")).toBe(2000);
    expect(edgeSnap(targets, 2020, 10, "end")).toBeNull();
  });
  it("jumps to the next point in either direction, skipping the current one", () => {
    expect(adjacentSnap(targets, 2000, 1)).toBe(2600);
    expect(adjacentSnap(targets, 2000, -1)).toBe(1000);
    expect(adjacentSnap(targets, 1999, 1)).toBe(2000);
    expect(adjacentSnap(targets, 2600, 1)).toBeNull();
    expect(adjacentSnap(targets, 1000, -1)).toBeNull();
  });
  it("lists the points inside a view, including its edges", () => {
    expect(snapsInRange(targets, 1000, 2000)).toEqual([1000, 2000]);
    expect(snapsInRange(targets, 2001, 2599)).toEqual([]);
  });
});
