import type { Clip, ExportMode } from "./api";

export type PublishView = "ready" | "exported";

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
