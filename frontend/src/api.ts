export type Status = "pending" | "group1" | "group2" | "exported" | "rejected";

/** A session's fixed review set; see doc/app-rebuild-plan.md, "Review sets". */
export interface ReviewSet {
  size: number;
  /** Candidates in the session when the set was picked. */
  total: number;
  random_share: number;
  /** Seeds the set's random part and the order its clips are shown in. */
  seed: string;
  /** Set clips not yet exported or rejected. */
  unprocessed: number;
  completed: { t: string; unprocessed: number } | null;
}

export interface Clip {
  clip_id: string;
  index: number;
  /** Role in the open review set; null outside it or once the set is completed. */
  review_set: "top" | "random" | null;
  suffix: number;
  title: string;
  status: Status;
  start_ms: number;
  end_ms: number;
  original_start_ms: number;
  original_end_ms: number;
  duration: string;
  last_export_path: string | null;
  last_export_title?: string | null;
  last_export_mode?: ExportMode | null;
  last_export_start_threshold_db?: number | null;
  last_export_stop_threshold_db?: number | null;
  last_export_snapshot?: ExportSnapshot | null;
  export_state?: "none" | "unknown" | "matching" | "changed";
  /** 0–100 review-order score; null until the clip has been measured. */
  likely_keep: number | null;
  /** Title from re-transcribing this clip's audio, awaiting review. */
  suggested_title: string | null;
}

/** Clip edge snap points by kind, in milliseconds; empty for sessions made before snapping existed. */
export interface SnapPoints {
  word_start: number[];
  speech_end: number[];
}

export interface MergePreview {
  added: number[];
  removed: number[];
  timing_changed: number[];
  text_changed: number[];
  affected_clip_ids: string[];
  unknown_original_text_clip_ids: string[];
  srt_fingerprint: string;
  file_changed: boolean;
  text_change_unverified: boolean;
}

export interface Session {
  audio: string | null;
  audio_name: string | null;
  duration_ms: number | null;
  srt: string | null;
  srt_exists: boolean;
  session_path: string | null;
  srt_fingerprint: string | null;
  leading_silence_detection_complete: boolean;
  clip_features_complete: boolean;
  /** Identifies the likely-keep formula, recorded with each logged decision. */
  likely_keep_version: string;
  clip_dir: string;
  needs_transcription: boolean;
  transcription: TranscriptionJob | null;
  revision: number | null;
  candidates: Clip[];
  counts: Record<Status, number>;
  can_undo: boolean;
  merge_preview: MergePreview | null;
  /** Saved SRTs a fresh session can start from. */
  clip_sources: ClipSource[];
  review_set: ReviewSet | null;
  /** Where Start over saved the previous session. */
  start_over_backup?: string;
  created_clip_id?: string;
  changed_clip_ids?: string[];
  output_path?: string;
}

/** The part of a session one edit changed, returned by edits made with `?delta=true`. */
export interface SessionDelta {
  delta: true;
  revision: number;
  counts: Record<Status, number>;
  can_undo: boolean;
  clips: Clip[];
  removed: string[];
  created_clip_id?: string;
  changed_clip_ids?: string[];
}

/** Merge an edit's delta into the loaded session without refetching every clip. */
export function applySessionDelta(session: Session, delta: SessionDelta): Session {
  const removed = new Set(delta.removed);
  const updates = new Map(delta.clips.map((clip) => [clip.clip_id, clip]));
  const candidates = session.candidates
    .filter((clip) => !removed.has(clip.clip_id))
    .map((clip) => {
      const updated = updates.get(clip.clip_id);
      if (updated) updates.delete(clip.clip_id);
      return updated ?? clip;
    });
  if (updates.size) {
    candidates.push(...updates.values());
    candidates.sort((a, b) => a.index - b.index || a.suffix - b.suffix);
  }
  return {
    ...session, candidates, revision: delta.revision, counts: delta.counts, can_undo: delta.can_undo,
    created_clip_id: delta.created_clip_id, changed_clip_ids: delta.changed_clip_ids,
  };
}

export interface LeadingSilenceJob {
  id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  total: number;
  adjusted: number;
  error: string | null;
}

export interface ClipFeaturesJob {
  id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  total: number;
  error: string | null;
}

export interface ClipTranscriptionJob {
  id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  total: number;
  clip_ids: string[];
  error: string | null;
}

export type ClipSource = "lines" | "generated";
export const clipSourceLabels: Record<ClipSource, string> = {
  lines: "Transcript lines", generated: "Voice activity (generated)",
};

export interface TranscriptionJob {
  id: string;
  audio: string;
  settings: {
    model_name: string;
    language: string | null;
    temperature: number;
    max_context: number;
    entropy_thold: number;
    // Missing on jobs saved before generated clips existed, which used transcript lines.
    clip_source?: ClipSource;
  };
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  phase: string;
  error: string | null;
  entry_count: number | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  log_tail: string[];
  log_file: string;
}

export interface WaveformWindow {
  start_ms: number;
  end_ms: number;
  mins: number[];
  maxs: number[];
}

export type ExportMode = "as_is" | "trim_edges" | "trim_all";

export interface ExportSnapshot {
  title: string;
  start_ms: number;
  end_ms: number;
  mode: ExportMode;
  start_threshold_db: number | null;
  stop_threshold_db: number | null;
}

export interface TrimMap {
  source_duration_ms: number;
  duration_ms: number;
  /** Retained spans on the original clip's timeline, before MP3 encoding. */
  kept_ranges_ms: [number, number][];
}

export interface PreviewJob {
  id: string;
  clip_id: string;
  session_revision: number;
  start_ms: number;
  end_ms: number;
  mode: ExportMode;
  start_threshold_db: number;
  stop_threshold_db: number;
  title: string;
  clip_title: string;
  proposed_filename: string;
  state: "queued" | "running" | "completed" | "failed";
  duration_ms: number | null;
  waveform: WaveformWindow | null;
  trim_map: TrimMap | null;
  error: string | null;
  stale: boolean;
}

let token = "";

export async function bootstrap(): Promise<void> {
  const response = await fetch("/api/bootstrap");
  if (!response.ok) throw new Error("Could not connect to the local server");
  token = (await response.json()).token;
}

export function audioUrl(): string {
  return `/api/audio?token=${encodeURIComponent(token)}`;
}

export function previewUrl(jobId: string): string {
  return `/api/previews/${encodeURIComponent(jobId)}/audio?token=${encodeURIComponent(token)}`;
}

export function eventsUrl(): string {
  return `/api/events?token=${encodeURIComponent(token)}`;
}

export async function api<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    signal,
    headers: {
      "content-type": "application/json",
      ...(method !== "GET" ? { "x-jipandan-token": token } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) {
    const message = typeof result.detail === "string" ? result.detail : "Request failed";
    throw Object.assign(new Error(message), { status: response.status, session: result.session });
  }
  return result as T;
}

/** Best-effort delivery of review-log events; failures are ignored so reviewing never stalls. */
export function sendReviewEvents(events: unknown[], keepalive = false): Promise<void> {
  return fetch("/api/review-log", {
    method: "POST", keepalive,
    headers: { "content-type": "application/json", "x-jipandan-token": token },
    body: JSON.stringify({ events }),
  }).then(() => undefined, () => undefined);
}

export async function uploadAudio(file: File): Promise<Session> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/session/upload", {
    method: "POST", headers: { "x-jipandan-token": token }, body,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail ?? "Upload failed");
  return result as Session;
}
