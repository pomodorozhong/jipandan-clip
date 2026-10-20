import { describe, expect, it } from "vitest";
import { VIEW_IDLE_MS, isIdle, viewEvent, type OpenView } from "./reviewViews";

const view: OpenView = { audio: "a.mp3", clipId: "7", started: 10_000, lastActive: 14_000, plays: 2, context: { rank: 3 } };

describe("review views", () => {
  it("records the time on screen and why the view ended", () => {
    expect(viewEvent(view, 16_000, "blur", true)).toEqual({
      type: "view", audio: "a.mp3", clip: "7", started_at: 10_000, dwell_ms: 6000,
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
});
