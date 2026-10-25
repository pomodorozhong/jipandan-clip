// A clip counts as viewed for the review log after this long on screen.
export const VIEW_MIN_MS = 1000;
// With no input or playback for this long, the viewer is assumed to have stepped away.
export const VIEW_IDLE_MS = 60_000;

// Events sent in one request; keepalive requests (sent as the page closes) are limited to 64 KB.
export const MAX_BATCH = 100;

// Why a view ended: another clip was selected, the stage changed, Settings or Help covered the clip,
// the page was hidden or lost focus, input stopped, or the round ended.
export type ViewEndReason = "clip_change" | "stage_change" | "covered" | "hidden" | "blur" | "idle" | "round_end";

/** What a view is of: the clip on screen, the stage it is shown in, and whether a dialog covers it. */
export interface ViewSubject {
  clipId: string | null;
  stage: string;
  covered: boolean;
}

/** Why the view of ``previous`` ends when the screen changes to ``next``, or null when it goes on. */
export function viewChange(previous: ViewSubject, next: ViewSubject): ViewEndReason | null {
  if (next.covered && !previous.covered) return "covered";
  if (next.clipId !== previous.clipId) return "clip_change";
  if (next.stage !== previous.stage) return "stage_change";
  return next.covered === previous.covered ? null : "clip_change";
}

function eventId(): string {
  return crypto.randomUUID();
}

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
    type: "view", id: eventId(), audio: view.audio, clip: view.clipId, started_at: view.started, dwell_ms: dwell,
    plays: view.plays, autoplay, context: view.context, ended_by: reason,
  };
}

export type PreviewWaitOutcome = "ready" | "failed" | "cancelled";

/** How long a Publish preview kept the viewer waiting, from its request until it was ready, failed, or was left. */
export interface PreviewWait {
  preview: "candidate" | "reference";
  started: number;
  waitMs: number;
  outcome: PreviewWaitOutcome;
}

export function previewWaitEvent(audio: string, clipId: string, wait: PreviewWait, context: object): object {
  return {
    type: "preview_wait", id: eventId(), audio, clip: clipId, started_at: wait.started, wait_ms: wait.waitMs,
    preview: wait.preview, outcome: wait.outcome, context,
  };
}

/** Review-log events on their way to the server. Events leave the queue only once the server has
 * confirmed them; a failed send keeps them for the next flush, and the server stores each event ID
 * once, so sending a batch again never counts it twice. */
export class ReviewEventQueue {
  private pending: object[] = [];
  private last: Promise<boolean> = Promise.resolve(true);

  constructor(private send: (events: object[], keepalive: boolean) => Promise<boolean>) {}

  push(event: object): void {
    this.pending.push(event);
  }

  get size(): number {
    return this.pending.length;
  }

  /** Drop queued events, such as the old session's views when starting over. */
  clear(): void {
    this.pending = [];
  }

  /** Send every queued event, one flush at a time; resolves true once all of them are confirmed. */
  flush(keepalive = false): Promise<boolean> {
    const run = this.last.then(() => this.sendAll(keepalive));
    this.last = run.catch(() => false);
    return run;
  }

  private async sendAll(keepalive: boolean): Promise<boolean> {
    while (this.pending.length) {
      const batch = this.pending.slice(0, MAX_BATCH);
      if (!await this.send(batch, keepalive)) return false;
      // Removed by identity: the queue may have been cleared while the batch was on its way.
      this.pending = this.pending.filter((event) => !batch.includes(event));
    }
    return true;
  }
}
