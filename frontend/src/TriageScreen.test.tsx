// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Clip } from "./api";
import TriageScreen from "./TriageScreen";

vi.mock("./WaveformEditor", () => ({
  initialRange: () => ({ start: 0, end: 60000 }),
  useWaveform: () => ({ window: null, error: null }),
  WaveformPlot: () => null,
}));
const clip = { clip_id: "1", index: 1, title: "First", start_ms: 0, end_ms: 30000,
  status: "pending", likely_keep: 50 } as Clip;
let container: HTMLDivElement;
let root: Root;
let frames: Map<number, FrameRequestCallback>;
let paused: WeakMap<HTMLMediaElement, boolean>;
let nextFrame: number;
let autoplay: boolean;
function render(current: Clip | null) {
  root.render(<TriageScreen clip={current} upNext={current ? [current] : []} durationMs={60000}
    position={1} remaining={current ? 1 : 0} counts={{ pending: current ? 1 : 0, group1: 0, group2: 0, exported: 0, rejected: 0 }}
    audioSrc="/recording.wav" autoplay={autoplay} active busy={false} orderNote={null}
    onPlayback={() => {}} onDecide={() => render(null)} onNavigate={() => {}} onSelect={() => {}} />);
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  paused = new WeakMap();
  frames = new Map();
  nextFrame = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(function (this: HTMLMediaElement) { return paused.get(this) ?? true; });
  vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(1);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    paused.set(this, false);
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    const wasPlaying = paused.get(this) === false;
    paused.set(this, true);
    if (wasPlaying) this.dispatchEvent(new Event("pause"));
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("Triage playback selection", () => {
  it.each([true, false])("pauses after the final playing clip is decided (autoplay=%s)", async (enabled) => {
    autoplay = enabled;
    await act(async () => render(clip));
    const audio = container.querySelector("audio")!;
    if (!enabled) await act(async () => { await audio.play(); });
    expect(audio.paused).toBe(false);
    const ready = Array.from(container.querySelectorAll("button")).find(button => button.textContent?.includes("Ready"))!;
    await act(async () => ready.click());
    expect(container.textContent).toContain("Everything is triaged");
    expect(audio.paused).toBe(true);
    await act(async () => {
      audio.currentTime = 51;
      for (const callback of [...frames.values()]) callback(51000);
      audio.dispatchEvent(new Event("loadedmetadata"));
    });
    expect(audio.paused).toBe(true);
    expect(frames.size).toBe(0);
  });
  it.each([true, false])("moves to another clip according to autoplay=%s", async (enabled) => {
    autoplay = enabled;
    await act(async () => render(clip));
    const audio = container.querySelector("audio")!;
    await act(async () => { await audio.play(); });
    await act(async () => render({ ...clip, clip_id: "2", start_ms: 40000, end_ms: 45000 }));
    expect(audio.paused).toBe(!enabled);
    if (enabled) expect(audio.currentTime).toBe(40);
  });
});
