// Review time per stage for the open session, from GET /api/session/stage-times.
export type Stage = "triage" | "polish" | "publish" | "unknown";

export interface StageRow {
  stage: Stage;
  ms: number;
  views: number;
  clips: number;
  changes: number;
}

export interface StageTimes {
  stages: StageRow[];
  total_ms: number;
  first_view: string | null;
  last_view: string | null;
}

export const stageLabels: Record<Stage, string> = {
  triage: "Triage", polish: "Polish", publish: "Publish", unknown: "No stage recorded",
};

/** Format a duration as "1 h 05 min", "4 min 10 s", or "12 s". */
export function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours} h ${String(minutes).padStart(2, "0")} min`;
  if (minutes) return `${minutes} min ${String(seconds % 60).padStart(2, "0")} s`;
  return `${seconds} s`;
}

/** Average time per clip viewed, with one decimal under ten seconds. */
export function formatPerClip(row: StageRow): string {
  if (!row.clips) return "—";
  const seconds = row.ms / row.clips / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)} s` : formatDuration(seconds * 1000);
}

export function formatShare(row: StageRow, totalMs: number): string {
  return totalMs ? `${Math.round((row.ms / totalMs) * 100)}%` : "—";
}
