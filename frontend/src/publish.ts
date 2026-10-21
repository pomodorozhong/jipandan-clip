import type { Clip, ExportMode } from "./api";

export type PublishView = "ready" | "exported";

export type ExportSettings = { mode: ExportMode; startDb: string; stopDb: string };

/** What every clip opens with in Publish, and what Export all uses. */
export const DEFAULT_EXPORT_SETTINGS: ExportSettings = { mode: "trim_edges", startDb: "-40", stopDb: "-50" };

/** An exported clip reopens with the settings it was exported with; any other clip starts from the defaults. */
export function initialExportSettings(clip: Clip): ExportSettings {
  if (!clip.last_export_path) return DEFAULT_EXPORT_SETTINGS;
  return {
    mode: clip.last_export_mode ?? DEFAULT_EXPORT_SETTINGS.mode,
    startDb: String(clip.last_export_start_threshold_db ?? DEFAULT_EXPORT_SETTINGS.startDb),
    stopDb: String(clip.last_export_stop_threshold_db ?? DEFAULT_EXPORT_SETTINGS.stopDb),
  };
}

export function publishClips(clips: Clip[], view: PublishView): Clip[] {
  return clips.filter((clip) => view === "ready" ? clip.status === "group2" : Boolean(clip.last_export_path))
    .sort((a, b) => a.index - b.index || a.suffix - b.suffix);
}

export function exportMatchesSettings(clip: Clip, title: string, mode: ExportMode, start: number, stop: number): boolean {
  const saved = clip.last_export_snapshot;
  return Boolean(saved && saved.title === title.trim() && saved.start_ms === clip.start_ms &&
    saved.end_ms === clip.end_ms && saved.mode === mode && (mode === "as_is" ||
      saved.start_threshold_db === start && saved.stop_threshold_db === stop));
}
