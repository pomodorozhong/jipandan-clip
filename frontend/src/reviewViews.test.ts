import { describe, expect, it } from "vitest";
import { MAX_BATCH, ReviewEventQueue, VIEW_IDLE_MS, isIdle, previewWaitEvent, viewChange, viewEvent, type OpenView } from "./reviewViews";

const view: OpenView = { audio: "a.mp3", clipId: "7", started: 10_000, lastActive: 14_000, plays: 2, context: { rank: 3 } };

describe("review views", () => {
  it("records the time on screen and why the view ended", () => {
    expect(viewEvent(view, 16_000, "blur", true)).toEqual({
      type: "view", id: expect.any(String), audio: "a.mp3", clip: "7", started_at: 10_000, dwell_ms: 6000,
      plays: 2, autoplay: true, context: { rank: 3 }, ended_by: "blur",
    });
  });

  it("ends an idle view at its last input, leaving out the time away", () => {
    const now = view.lastActive + VIEW_IDLE_MS;
    expect(isIdle(view, now - 1)).toBe(false);
    expect(isIdle(view, now)).toBe(true);
    expect(viewEvent(view, now, "idle", false)).toMatchObject({ dwell_ms: 4000, ended_by: "idle" });
  });

  it("drops views too short to count", () => {
    expect(viewEvent(view, 10_500, "clip_change", false)).toBeNull();
    // Selected, then left without any input: no time on the clip is recorded.
    expect(viewEvent({ ...view, lastActive: view.started }, 90_000, "idle", false)).toBeNull();
  });

  it("gives every event its own ID", () => {
    const first = viewEvent(view, 16_000, "blur", true) as { id: string };
    const second = viewEvent(view, 16_000, "blur", true) as { id: string };
    expect(first.id).not.toBe(second.id);
    expect(previewWaitEvent("a.mp3", "7", { preview: "candidate", started: 1000, waitMs: 2500, outcome: "ready" }, { stage: "publish" }))
      .toMatchObject({ type: "preview_wait", clip: "7", started_at: 1000, wait_ms: 2500, preview: "candidate", outcome: "ready" });
  });

  it("starts a new view when the stage changes on the same clip, in both directions", () => {
    const polish = { clipId: "7", stage: "polish", covered: false };
    const triage = { ...polish, stage: "triage" };
    expect(viewChange(polish, triage)).toBe("stage_change");
    expect(viewChange(triage, polish)).toBe("stage_change");
    expect(viewChange(polish, polish)).toBeNull();
    expect(viewChange(polish, { ...triage, clipId: "8" })).toBe("clip_change");
  });

  it("ends the view while Settings or Help covers the clip", () => {
    const shown = { clipId: "7", stage: "triage", covered: false };
    const covered = { clipId: null, stage: "triage", covered: true };
    expect(viewChange(shown, covered)).toBe("covered");
    expect(viewChange(covered, shown)).toBe("clip_change");
  });
});

describe("review event queue", () => {
  it("keeps a batch that failed to send and sends it again", async () => {
    const sent: object[][] = [];
    let online = false;
    const queue = new ReviewEventQueue(async (events) => { sent.push(events); return online; });
    queue.push({ id: "a" });
    expect(await queue.flush()).toBe(false);
    expect(queue.size).toBe(1);
    online = true;
    queue.push({ id: "b" });
    expect(await queue.flush()).toBe(true);
    expect(queue.size).toBe(0);
    expect(sent).toEqual([[{ id: "a" }], [{ id: "a" }, { id: "b" }]]);
  });

  it("sends one flush at a time, so overlapping flushes never send an event twice", async () => {
    const sent: object[][] = [];
    let release: (ok: boolean) => void = () => {};
    const queue = new ReviewEventQueue((events) => {
      sent.push(events);
      return sent.length === 1 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(true);
    });
    queue.push({ id: "a" });
    const first = queue.flush();
    queue.push({ id: "b" });
    const second = queue.flush();
    await Promise.resolve();
    release(true);
    expect(await first).toBe(true);
    expect(await second).toBe(true);
    expect(sent).toEqual([[{ id: "a" }, { id: "b" }]]);
  });

  it("splits a long queue into batches the server accepts", async () => {
    const sizes: number[] = [];
    const queue = new ReviewEventQueue(async (events) => { sizes.push(events.length); return true; });
    for (let index = 0; index < MAX_BATCH + 5; index += 1) queue.push({ id: String(index) });
    expect(await queue.flush()).toBe(true);
    expect(sizes).toEqual([MAX_BATCH, 5]);
  });
});
