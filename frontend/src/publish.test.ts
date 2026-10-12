import { describe, expect, it } from "vitest";
import { exportMatchesSettings, publishClips } from "./publish";
import type { Clip } from "./api";
import { isActionAvailable } from "./inputActions";
import { defaultGamepadBindingConfig, publishGamepadBindings } from "./gamepad";

const saved = { clip_id: "1", index: 1, suffix: 0, title: "Reaction", status: "exported", start_ms: 1000, end_ms: 2500,
  last_export_path: "/exports/clip.mp3", last_export_snapshot: { title: "Reaction", start_ms: 1000, end_ms: 2500,
    mode: "trim_edges", start_threshold_db: -40, stop_threshold_db: -50 } } as Clip;

describe("Publish", () => {
  it("keeps edited exports in the exported list even after they return to Group 1", () => {
    const clips = [{ ...saved, index: 2, clip_id: "2", status: "group1" as const },
      { ...saved, last_export_path: null, status: "group2" as const }];
    expect(publishClips(clips, "exported").map((clip) => clip.clip_id)).toEqual(["2"]);
    expect(publishClips(clips, "ready").map((clip) => clip.clip_id)).toEqual(["1"]);
  });
  it("checks published title, timing, mode, and thresholds, with explicit unknown history", () => {
    expect(exportMatchesSettings(saved, "Reaction", "trim_edges", -40, -50)).toBe(true);
    expect(exportMatchesSettings(saved, "Changed", "trim_edges", -40, -50)).toBe(false);
    expect(exportMatchesSettings({ ...saved, start_ms: 1010 }, "Reaction", "trim_edges", -40, -50)).toBe(false);
    expect(exportMatchesSettings(saved, "Reaction", "trim_all", -40, -50)).toBe(false);
    expect(exportMatchesSettings(saved, "Reaction", "trim_edges", -30, -50)).toBe(false);
    expect(exportMatchesSettings({ ...saved, last_export_snapshot: null }, "Reaction", "trim_edges", -40, -50)).toBe(false);
    const asIs = { ...saved, last_export_snapshot: { ...saved.last_export_snapshot!, mode: "as_is" as const,
      start_threshold_db: null, stop_threshold_db: null } };
    expect(exportMatchesSettings(asIs, "Reaction", "as_is", -20, -80)).toBe(true);
  });
  it("routes explicit export controls ahead of shared review controls in Publish", () => {
    const config = { ...defaultGamepadBindingConfig(), export: 2, "export-mode-trim-all": 1 };
    const bindings = publishGamepadBindings(config);
    expect(bindings.find((b) => b.index === 2)?.action).toEqual({ type: "export", advance: false });
    expect(bindings.find((b) => b.index === 1)?.action).toEqual({ type: "export-mode", mode: "trim_all" });
    expect(bindings.find((b) => b.index === 0)?.action).toEqual({ type: "playback", target: "candidate", mode: "replay" });
    expect(bindings.find((b) => b.index === 13)?.action).toEqual({ type: "navigate", direction: "next" });
    expect(bindings.every((b) => b.contexts.includes("publish"))).toBe(true);
    expect(new Set(bindings.map((b) => b.index)).size).toBe(bindings.length);
    expect(isActionAvailable({ type: "export", advance: false }, { context: "publish", candidateReady: true })).toBe(true);
    expect(isActionAvailable({ type: "export", advance: false }, { context: "publish", candidateReady: false })).toBe(false);
    expect(isActionAvailable({ type: "dialog-close" }, { context: "publish" })).toBe(false);
  });
});
