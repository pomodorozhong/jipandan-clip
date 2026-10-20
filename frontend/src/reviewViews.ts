// A clip counts as viewed for the review log after this long on screen.
export const VIEW_MIN_MS = 1000;
// With no input or playback for this long, the viewer is assumed to have stepped away.
export const VIEW_IDLE_MS = 60_000;

// Why a view ended: another clip was selected, the page was hidden or lost focus, or input stopped.
export type ViewEndReason = "clip_change" | "hidden" | "blur" | "idle";

export interface OpenView {
  audio: string;
  clipId: string;
  started: number;
  // The last input or playback during this view.
  lastActive: number;
  plays: number;
  context: object;
}

export function isIdle(view: OpenView, now: number): boolean {
  return now - view.lastActive >= VIEW_IDLE_MS;
}

/** Return the review-log event for a view ending at ``now``, or null when it was too short to count.
 * An idle view ends at its last input, so the time spent away is left out. */
export function viewEvent(view: OpenView, now: number, reason: ViewEndReason, autoplay: boolean): object | null {
  const ended = reason === "idle" ? Math.min(now, Math.max(view.started, view.lastActive)) : now;
  const dwell = ended - view.started;
  if (dwell < VIEW_MIN_MS) return null;
  return {
    type: "view", audio: view.audio, clip: view.clipId, started_at: view.started, dwell_ms: dwell,
    plays: view.plays, autoplay, context: view.context, ended_by: reason,
  };
}
