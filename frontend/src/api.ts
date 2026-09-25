export type Status = "pending" | "group1" | "group2" | "exported" | "skipped";

export interface Clip {
  clip_id: string;
  index: number;
  suffix: number;
  title: string;
  status: Status;
  start_ms: number;
  end_ms: number;
  original_start_ms: number;
  original_end_ms: number;
  duration: string;
  last_export_path: string | null;
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
  clip_dir: string;
  needs_transcription: boolean;
  transcription: TranscriptionJob | null;
  revision: number | null;
  candidates: Clip[];
  counts: Record<Status, number>;
  can_undo: boolean;
  merge_preview: MergePreview | null;
  created_clip_id?: string;
  changed_clip_ids?: string[];
  output_path?: string;
}

export interface TranscriptionJob {
  id: string;
  audio: string;
  settings: {
    model_name: string;
    language: string | null;
    temperature: number;
    max_context: number;
    entropy_thold: number;
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
