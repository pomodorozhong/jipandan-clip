import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl, bootstrap, uploadAudio, type Clip, type LeadingSilenceJob, type Session, type Status } from "./api";
import WaveformEditor from "./WaveformEditor";
import ExportPreview from "./ExportPreview";
import TranscriptionScreen from "./TranscriptionScreen";
import SettingsScreen from "./SettingsScreen";

type Filter = "unsorted" | "group1" | "group2" | "exported" | "all";
type AllStatusFilter = "all" | Status;
type AllOrder = "clip-asc" | "clip-desc" | "start-asc" | "start-desc" | "title-asc";
type SaveState = "saved" | "saving" | "failed";
type AppSettings = { detectLeadingSilence: boolean; showOriginalStart: boolean };

const SETTINGS_STORAGE_KEY = "jipandan-settings";

function loadSettings(): AppSettings {
  try {
    const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<AppSettings>;
      return {
        detectLeadingSilence: typeof parsed.detectLeadingSilence === "boolean" ? parsed.detectLeadingSilence : true,
        showOriginalStart: typeof parsed.showOriginalStart === "boolean" ? parsed.showOriginalStart : false,
      };
    }
  } catch { /* Use defaults when browser storage is unavailable or invalid. */ }
  return { detectLeadingSilence: true, showOriginalStart: false };
}

const filters: { key: Filter; label: string }[] = [
  { key: "unsorted", label: "Unsorted" },
  { key: "group1", label: "Group 1" },
  { key: "group2", label: "Group 2" },
  { key: "exported", label: "Exported" },
  { key: "all", label: "All" },
];

const labels: Record<Status, string> = {
  pending: "Unsorted", group1: "Group 1", group2: "Group 2",
  exported: "Exported", skipped: "Skipped",
};

const allOrders: { key: AllOrder; label: string }[] = [
  { key: "clip-asc", label: "Clip number ↑" },
  { key: "clip-desc", label: "Clip number ↓" },
  { key: "start-asc", label: "Start time ↑" },
  { key: "start-desc", label: "Start time ↓" },
  { key: "title-asc", label: "Title A–Z" },
];

function formatDuration(ms: number): string {
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
}

function visibleClips(
  clips: Clip[], filter: Filter, query: string,
  allStatusFilter: AllStatusFilter = "all",
): Clip[] {
  const needle = query.trim().normalize("NFKC").toLocaleLowerCase();
  return clips.filter((clip) => {
    if (filter === "unsorted" && clip.status !== "pending") return false;
    if (filter !== "unsorted" && filter !== "all" && clip.status !== filter) return false;
    if (filter === "all" && allStatusFilter !== "all" && clip.status !== allStatusFilter) return false;
    if (needle && !clip.title.normalize("NFKC").toLocaleLowerCase().includes(needle)) return false;
    return true;
  });
}

function ActionButton({ children, onClick, disabled, tone = "normal", title, shortcut }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean;
  tone?: "normal" | "accent" | "danger"; title?: string; shortcut?: string;
}) {
  const toneClass = tone === "accent"
    ? "bg-[#b7d69d] text-[#1d2d20] hover:bg-[#d4ecbe]"
    : tone === "danger"
      ? "bg-[#5d3938] text-[#ffe2db] hover:bg-[#754542]"
      : "soft-surface text-[#e7eee7] hover:bg-[#354b3b]";
  return <button type="button" title={title} disabled={disabled} onClick={onClick}
    className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${toneClass}`}>
    <span>{children}</span>{shortcut && <kbd aria-hidden="true" className="shortcut-key">{shortcut}</kbd>}
  </button>;
}

function Dialog({ title, children, onClose }: {
  title: string; children: React.ReactNode; onClose: () => void;
}) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return <div className="fixed inset-0 z-30 flex items-center justify-center bg-[#07100bcf] p-4"
    role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label={title}
      className="surface max-h-[85vh] w-full max-w-lg overflow-auto rounded-2xl p-5 shadow-2xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Close dialog (Esc)"
          className="subtle inline-flex items-center gap-2 text-xl">
          <span aria-hidden="true">×</span><kbd className="shortcut-key text-xs">Esc</kbd>
        </button>
      </div>
      {children}
    </section>
  </div>;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [openPath, setOpenPath] = useState("");
  const [filter, setFilter] = useState<Filter>("unsorted");
  const [allStatusFilter, setAllStatusFilter] = useState<AllStatusFilter>("all");
  const [allOrder, setAllOrder] = useState<AllOrder>("clip-asc");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [showClipMenu, setShowClipMenu] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  const [showJump, setShowJump] = useState(false);
  const [jumpDraft, setJumpDraft] = useState("");
  const [showMerge, setShowMerge] = useState(false);
  const [removeIndexes, setRemoveIndexes] = useState<number[]>([]);
  const [showDetailMobile, setShowDetailMobile] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<AppSettings>(loadSettings);
  const [leadingSilenceJob, setLeadingSilenceJob] = useState<LeadingSilenceJob | null>(null);
  const [dismissedDetectionJobId, setDismissedDetectionJobId] = useState<string | null>(null);
  const autoDetectionRequest = useRef<string | null>(null);
  const loadedDetectionJob = useRef<string | null>(null);
  const loadedDetectionAdjustment = useRef<{ id: string; adjusted: number } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const clipMenuRef = useRef<HTMLDivElement>(null);
  const detailScrollRef = useRef<HTMLDivElement>(null);
  const clipListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings)); }
    catch { /* Settings still apply for this browser session. */ }
  }, [settings]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await bootstrap();
        const data = await api<Session>("/session");
        if (alive) setSession(data);
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (alive) setInitializing(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!session?.audio) return;
    const saved = localStorage.getItem(`jipandan-review:${session.audio}`);
    if (saved) {
      try {
        const preferences = JSON.parse(saved) as {
          filter?: Filter; selectedId?: string;
          allStatusFilter?: AllStatusFilter; allOrder?: AllOrder;
        };
        if (preferences.filter && filters.some((item) => item.key === preferences.filter)) {
          setFilter(preferences.filter);
        } else if (session.counts.pending === 0) setFilter("all");
        setSelectedId(preferences.selectedId ?? null);
        if (preferences.allStatusFilter === "all" || Object.hasOwn(labels, preferences.allStatusFilter ?? "")) {
          setAllStatusFilter(preferences.allStatusFilter!);
        }
        if (allOrders.some((item) => item.key === preferences.allOrder)) {
          setAllOrder(preferences.allOrder!);
        }
      } catch {
        if (session.counts.pending === 0) setFilter("all");
      }
    } else if (session.counts.pending === 0) setFilter("all");
  }, [session?.audio]);

  useEffect(() => {
    if (!session?.audio) return;
    localStorage.setItem(`jipandan-review:${session.audio}`, JSON.stringify({
      filter, selectedId, allStatusFilter, allOrder,
    }));
  }, [session?.audio, filter, selectedId, allStatusFilter, allOrder]);

  useEffect(() => {
    if (!settings.detectLeadingSilence || !session?.audio || session.needs_transcription ||
        session.revision === null || session.leading_silence_detection_complete ||
        leadingSilenceJob?.state === "queued" || leadingSilenceJob?.state === "running") return;
    const requestKey = `${session.audio}:${session.revision}`;
    if (autoDetectionRequest.current === requestKey) return;
    autoDetectionRequest.current = requestKey;
    let active = true;
    void api<LeadingSilenceJob>("/session/leading-silence-detection", "POST")
      .then((job) => { if (active) setLeadingSilenceJob(job); })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => { active = false; };
  }, [settings.detectLeadingSilence, session?.audio, session?.needs_transcription,
    session?.revision, session?.leading_silence_detection_complete, leadingSilenceJob?.state]);

  useEffect(() => {
    if (!session?.audio || session.needs_transcription) {
      setLeadingSilenceJob(null);
      return;
    }
    let active = true;
    let timer: number | null = null;
    async function poll() {
      try {
        const job = await api<LeadingSilenceJob | null>("/session/leading-silence-detection");
        if (!active) return;
        setLeadingSilenceJob(job);
        if (job?.state === "running" && job.adjusted > 0 &&
            (loadedDetectionAdjustment.current?.id !== job.id ||
             loadedDetectionAdjustment.current.adjusted < job.adjusted)) {
          const latest = await api<Session>("/session");
          if (active) {
            setSession(latest);
            loadedDetectionAdjustment.current = { id: job.id, adjusted: job.adjusted };
          }
        }
        if (job?.state === "completed" && loadedDetectionJob.current !== job.id) {
          const latest = await api<Session>("/session");
          if (active) {
            setSession(latest);
            loadedDetectionJob.current = job.id;
          }
        }
        if (job?.state === "queued" || job?.state === "running") {
          timer = window.setTimeout(() => { void poll(); }, 750);
        }
      } catch {
        if (active) timer = window.setTimeout(() => { void poll(); }, 1500);
      }
    }
    void poll();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session?.audio, session?.needs_transcription, leadingSilenceJob?.id, leadingSilenceJob?.state]);

  const visible = useMemo(() => {
    const clips = visibleClips(session?.candidates ?? [], filter, query, allStatusFilter);
    if (filter !== "all") return clips;
    const compareClipId = (a: Clip, b: Clip) => a.index - b.index || a.suffix - b.suffix;
    return clips.sort((a, b) => {
      if (allOrder === "clip-desc") return compareClipId(b, a);
      if (allOrder === "start-asc") return a.start_ms - b.start_ms || compareClipId(a, b);
      if (allOrder === "start-desc") return b.start_ms - a.start_ms || compareClipId(a, b);
      if (allOrder === "title-asc") return a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" }) || compareClipId(a, b);
      return compareClipId(a, b);
    });
  }, [session?.candidates, filter, query, allStatusFilter, allOrder]);
  const effectiveSelectedId = visible.some((clip) => clip.clip_id === selectedId)
    ? selectedId : (visible[0]?.clip_id ?? null);
  const selected = session?.candidates.find((clip) => clip.clip_id === effectiveSelectedId) ?? null;
  const selectedPosition = visible.findIndex((clip) => clip.clip_id === effectiveSelectedId);
  const nextVisibleClipId = visible[selectedPosition + 1]?.clip_id ?? null;
  const hasMergeChanges = Boolean(session?.merge_preview && (
    session.merge_preview.added.length || session.merge_preview.removed.length ||
    session.merge_preview.timing_changed.length || session.merge_preview.text_changed.length ||
    session.merge_preview.file_changed
  ));

  useEffect(() => {
    detailScrollRef.current?.scrollTo(0, 0);
  }, [effectiveSelectedId]);

  useEffect(() => { setShowExportModal(false); }, [session?.audio]);

  const mutate = useCallback(async (work: () => Promise<Session>) => {
    setBusy(true);
    setSaveState("saving");
    setError("");
    try {
      const next = await work();
      setSession(next);
      setSaveState("saved");
      return next;
    } catch (cause) {
      const failure = cause as Error & { status?: number; session?: Session };
      if (failure.status === 409 && failure.session) setSession(failure.session);
      setError(failure.message);
      setSaveState("failed");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const patchSelected = useCallback((change: Record<string, unknown>) => {
    if (!session || session.revision === null || !effectiveSelectedId) return;
    let nextSelection = effectiveSelectedId;
    if (selected && typeof change.status === "string") {
      const changed = { ...selected, status: change.status as Status };
      if (visibleClips([changed], filter, query, allStatusFilter).length === 0) {
        nextSelection = visible[selectedPosition + 1]?.clip_id ??
          visible[selectedPosition - 1]?.clip_id ?? effectiveSelectedId;
      }
    }
    void mutate(() => api<Session>(`/clips/${encodeURIComponent(effectiveSelectedId)}`, "PATCH", {
      expected_revision: session.revision, ...change,
    })).then((next) => { if (next) setSelectedId(nextSelection); });
  }, [session, effectiveSelectedId, selected, filter, query, allStatusFilter,
    visible, selectedPosition, mutate]);

  const moveSelection = useCallback((delta: number) => {
    if (!visible.length) return;
    const position = Math.max(0, Math.min(visible.length - 1, selectedPosition + delta));
    setSelectedId(visible[position].clip_id);
    setShowDetailMobile(false);
  }, [visible, selectedPosition]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (showSettings || showHelp || showJump || showMerge || showExportModal || editingTitle) return;
      if (event.isComposing || event.key === "Process") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable='true']"))) return;
      const key = event.key.toLowerCase();
      if (key === "e" && selected) { event.preventDefault(); setShowExportModal(true); }
      else if (key === "j" || key === "arrowdown") { event.preventDefault(); moveSelection(1); }
      else if (key === "k" || key === "arrowup") { event.preventDefault(); moveSelection(-1); }
      else if (key === "1") { event.preventDefault(); patchSelected({ status: "group1" }); }
      else if (key === "2") { event.preventDefault(); patchSelected({ status: "group2" }); }
      else if (key === "x") { event.preventDefault(); patchSelected({ status: "skipped" }); }
      else if (key === "u" && session?.can_undo && session.revision !== null) {
        event.preventDefault();
        void mutate(() => api<Session>("/session/undo", "POST", { expected_revision: session.revision }));
      }
      else if (key === "d" && effectiveSelectedId && session && session.revision !== null) {
        event.preventDefault();
        void mutate(() => api<Session>(`/clips/${encodeURIComponent(effectiveSelectedId)}/duplicate`,
          "POST", { expected_revision: session.revision })).then((next) => {
          if (next?.created_clip_id) setSelectedId(next.created_clip_id);
        });
      }
      else if (key === "r" && selected) {
        event.preventDefault(); setTitleDraft(selected.title); setEditingTitle(true);
      }
      else if (key === "g") { event.preventDefault(); setShowJump(true); }
      else if (key === "/") { event.preventDefault(); searchRef.current?.focus(); }
      else if (key === "?") { event.preventDefault(); setShowHelp(true); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showHelp, showJump, showMerge, showExportModal, editingTitle, moveSelection, patchSelected,
    session, selected, effectiveSelectedId, mutate, showSettings]);

  useEffect(() => { if (editingTitle) titleRef.current?.focus(); }, [editingTitle]);

  useEffect(() => {
    if (!showClipMenu) return;
    function closeMenu(event: MouseEvent) {
      if (!clipMenuRef.current?.contains(event.target as Node)) setShowClipMenu(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); setShowClipMenu(false); }
    }
    document.addEventListener("mousedown", closeMenu);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeMenu);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [showClipMenu]);

  useEffect(() => { setShowClipMenu(false); }, [effectiveSelectedId]);

  async function openAudio(event: React.FormEvent) {
    event.preventDefault();
    if (!openPath.trim()) return;
    const next = await mutate(() => api<Session>("/session/open", "POST", { path: openPath.trim() }));
    if (next) {
      setLeadingSilenceJob(null); setDismissedDetectionJobId(null); loadedDetectionAdjustment.current = null;
      autoDetectionRequest.current = null; loadedDetectionJob.current = null;
      setQuery(""); setSelectedId(null); setFilter(next.counts.pending > 0 ? "unsorted" : "all");
    }
  }

  async function openPickedAudio(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const next = await mutate(() => uploadAudio(file));
    if (next) {
      setLeadingSilenceJob(null); setDismissedDetectionJobId(null); loadedDetectionAdjustment.current = null;
      autoDetectionRequest.current = null; loadedDetectionJob.current = null;
      setQuery(""); setSelectedId(null); setFilter("unsorted");
    }
    event.target.value = "";
  }

  async function saveTitle() {
    if (!selected || !titleDraft.trim()) return;
    if (titleDraft.trim() !== selected.title && session?.revision !== null) {
      const next = await mutate(() => api<Session>(`/clips/${encodeURIComponent(selected.clip_id)}`, "PATCH", {
        expected_revision: session!.revision, title: titleDraft.trim(),
      }));
      if (!next) return;
    }
    setEditingTitle(false);
  }

  function jumpToIndex() {
    const requested = Number(jumpDraft.trim());
    if (!Number.isInteger(requested) || requested < 1) return;
    const target = visible.find((clip) => clip.index === requested) ??
      visible.reduce<Clip | null>((closest, clip) =>
        !closest || Math.abs(clip.index - requested) < Math.abs(closest.index - requested) ? clip : closest, null);
    if (target) {
      setSelectedId(target.clip_id);
      requestAnimationFrame(() => {
        clipListRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
          ?.scrollIntoView({ block: "nearest" });
      });
    }
    setShowJump(false);
    setJumpDraft("");
  }

  async function applyMerge() {
    const preview = session?.merge_preview;
    if (!preview || session?.revision === null) return;
    const next = await mutate(() => api<Session>("/session/merge", "POST", {
      expected_revision: session!.revision,
      srt_fingerprint: preview.srt_fingerprint,
      remove_indexes: removeIndexes,
    }));
    if (next) { setShowMerge(false); setRemoveIndexes([]); }
  }

  async function retryLeadingSilenceDetection() {
    try {
      const job = await api<LeadingSilenceJob>("/session/leading-silence-detection", "POST");
      setLeadingSilenceJob(job);
      setDismissedDetectionJobId(null);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  if (initializing) return <main className="flex min-h-screen items-center justify-center subtle">Opening Jipandan…</main>;

  return <div className={`flex flex-col ${session?.audio ? "h-dvh min-h-0 overflow-hidden" : "min-h-screen"}`}>
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b line px-4 py-3 md:px-7">
      <div className="flex items-center gap-3">
        <div aria-hidden="true" className="flex size-9 items-center justify-center rounded-xl bg-[#b7d69d] text-xl font-bold text-[#263c2b]">J</div>
        <div>
          <div className="font-semibold tracking-wide">Jipandan <span className="subtle font-normal">/ clip review</span></div>
          <div className="subtle text-xs">Local workspace · {session?.audio_name ?? "No audio open"}</div>
        </div>
      </div>
      <div className="flex items-center gap-3 text-sm">
        {session?.audio && !session.needs_transcription && <span aria-live="polite" className={saveState === "failed" ? "text-[#ffb3a8]" : saveState === "saving" ? "text-[#ead49b]" : "accent"}>
          {saveState === "saving" ? "Saving…" : saveState === "failed" ? "Save failed" : "Saved"}
        </span>}
        {session?.audio && !session.needs_transcription && <ActionButton onClick={() => {
          if (session.revision === null) return;
          void mutate(() => api<Session>("/session/undo", "POST", { expected_revision: session.revision }));
        }} disabled={!session.can_undo || busy} title="Undo recent change (U)" shortcut="U">Undo</ActionButton>}
        {!session?.needs_transcription && <ActionButton onClick={() => setShowHelp(true)} title="Keyboard shortcuts" shortcut="?">Shortcuts</ActionButton>}
        <ActionButton onClick={() => {
          setShowSettings(true);
          setShowHelp(false); setShowJump(false); setShowMerge(false); setShowExportModal(false);
        }}>Settings</ActionButton>
      </div>
    </header>

    {error && <div role="alert" className="shrink-0 border-b border-[#a96053] bg-[#482d2a] px-5 py-3 text-sm text-[#ffe3dc]">
      {error} <button className="ml-3 underline" onClick={() => setError("")}>Dismiss</button>
    </div>}

    {leadingSilenceJob && leadingSilenceJob.id !== dismissedDetectionJobId && <div
      role="status" aria-live="polite"
      className={`shrink-0 border-b px-4 py-2 text-sm md:px-7 ${leadingSilenceJob.state === "failed" ? "border-[#a96053] bg-[#482d2a] text-[#ffe3dc]" : leadingSilenceJob.state === "completed" ? "border-[#55744b] bg-[#24372b]" : "border-[#7c6845] bg-[#3c3525]"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span>
          {leadingSilenceJob.state === "queued" || leadingSilenceJob.state === "running"
            ? <>Detecting leading silence · {leadingSilenceJob.progress} of {leadingSilenceJob.total} clips checked · {leadingSilenceJob.adjusted} adjusted so far</>
            : leadingSilenceJob.state === "completed"
              ? <>Leading silence detection complete · adjusted {leadingSilenceJob.adjusted} {leadingSilenceJob.adjusted === 1 ? "clip start" : "clip starts"}</>
              : leadingSilenceJob.state === "failed"
                ? `Leading silence detection failed: ${leadingSilenceJob.error ?? "Unknown error"}`
                : "Leading silence detection stopped because the session changed."}
        </span>
        <div className="flex items-center gap-3">
          {leadingSilenceJob.state === "failed" && <button type="button" onClick={() => void retryLeadingSilenceDetection()} className="underline">Retry</button>}
          {(leadingSilenceJob.state === "completed" || leadingSilenceJob.state === "failed" || leadingSilenceJob.state === "cancelled") &&
            <button type="button" onClick={() => setDismissedDetectionJobId(leadingSilenceJob.id)} aria-label="Dismiss detection status" className="text-lg leading-none">×</button>}
        </div>
      </div>
      {(leadingSilenceJob.state === "queued" || leadingSilenceJob.state === "running") && <div
        role="progressbar" aria-label="Leading silence detection progress"
        aria-valuemin={0} aria-valuemax={leadingSilenceJob.total} aria-valuenow={leadingSilenceJob.progress}
        className="mt-2 h-1 overflow-hidden rounded-full bg-[#17241c]">
        <div className="h-full bg-[#b7d69d] transition-[width]" style={{ width: `${leadingSilenceJob.total ? leadingSilenceJob.progress / leadingSilenceJob.total * 100 : 100}%` }} />
      </div>}
    </div>}

    {!session?.audio ? <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-5 py-12">
      <p className="accent mb-3 text-sm font-semibold uppercase tracking-[.2em]">Start a session</p>
      <h1 className="mb-3 text-4xl font-semibold tracking-tight">Open your recording</h1>
      <p className="subtle mb-8 max-w-xl">Enter a local audio path to review its SRT and saved session. The audio stays on this computer.</p>
      <form onSubmit={openAudio} className="surface rounded-2xl p-5">
        <label htmlFor="audio-path" className="mb-2 block text-sm font-medium">Local audio path</label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input id="audio-path" value={openPath} onChange={(event) => setOpenPath(event.target.value)}
            placeholder="/path/to/recording.mp3" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2 text-sm" />
          <button disabled={busy} className="rounded-lg bg-[#b7d69d] px-5 py-2 font-semibold text-[#1d2d20]">Open audio</button>
        </div>
      </form>
      <label className="surface mt-3 flex cursor-pointer items-center justify-between gap-3 rounded-xl px-5 py-4 text-sm hover:bg-[#283b30]">
        <span><strong>Choose an audio file</strong><span className="subtle mt-1 block text-xs">Copies the recording into Jipandan’s local storage.</span></span>
        <span className="accent">Browse…</span>
        <input type="file" accept=".mp3,.m4a,.wav,.flac,.ogg,.aac,audio/*" onChange={(event) => void openPickedAudio(event)} className="sr-only" disabled={busy} />
      </label>
      <p className="subtle mt-4 text-sm">You can also launch directly with <code className="accent">uv run jipandan-web /path/to/audio.mp3</code>.</p>
    </main> : <>
      <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-b line px-4 py-2 text-xs md:px-7">
        <span><span className="subtle">Duration</span> <span className="mono">{formatDuration(session.duration_ms ?? 0)}</span></span>
        <span><span className="subtle">SRT</span> {session.srt_exists ? "Found" : "Missing"}</span>
        <span className="hidden min-w-0 truncate lg:inline"><span className="subtle">Session</span> {session.session_path ?? "Not created"}</span>
        <span className="hidden min-w-0 truncate xl:inline"><span className="subtle">Exports</span> {session.clip_dir}</span>
      </div>
      {hasMergeChanges && <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[#7c6845] bg-[#3c3525] px-4 py-2 text-sm md:px-7">
        <span>The SRT changed since this session was saved. Your reviewed clips are still here.</span>
        <ActionButton onClick={() => setShowMerge(true)}>Review SRT changes</ActionButton>
      </div>}
      {session.needs_transcription ? <TranscriptionScreen key={session.audio} session={session}
        onReady={(next) => { setSession(next); setFilter("unsorted"); setSelectedId(null); }} /> : <>
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(310px,38%)_1fr]">
        <section className={`${showDetailMobile ? "hidden md:flex" : "flex"} min-h-0 flex-col overflow-hidden border-r line`} aria-label="Clip list">
          <div className="shrink-0 border-b line p-4 md:p-5">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h1 className="text-xl font-semibold">Clips</h1>
              <span className="subtle text-sm mono">{visible.length} visible / {session.candidates.length} total</span>
            </div>
            <div className="mb-3 grid grid-cols-5 overflow-hidden rounded-lg border line bg-[#22312a] p-1" role="group" aria-label="Status filter">
              {filters.map((item) => <button key={item.key} type="button" onClick={() => setFilter(item.key)}
                aria-pressed={filter === item.key}
                aria-label={`${item.label}, ${item.key === "all" ? session.candidates.length : session.counts[item.key === "unsorted" ? "pending" : item.key]} ${
                  (item.key === "all" ? session.candidates.length : session.counts[item.key === "unsorted" ? "pending" : item.key]) === 1 ? "clip" : "clips"}`}
                className={`flex min-w-0 flex-col items-center justify-center gap-1 rounded-md px-0.5 py-2 text-[10px] leading-tight sm:text-xs ${filter === item.key ? "bg-[#b7d69d] text-[#1b291f] shadow-sm" : "hover:bg-[#304439] hover:text-white"}`}>
                <span className="whitespace-nowrap font-semibold">{item.label}</span><span aria-hidden="true" className={`mono text-[11px] font-normal leading-none sm:text-xs ${filter === item.key ? "text-[#435d46]" : "text-[#9eafa3]"}`}>
                  {item.key === "all" ? session.candidates.length : session.counts[item.key === "unsorted" ? "pending" : item.key]}
                </span>
              </button>)}
            </div>
            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <input ref={searchRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)}
                  aria-label="Search clip titles" placeholder={`Search within ${filters.find((item) => item.key === filter)?.label}…`}
                  className="w-full rounded-lg border line bg-[#101816] px-3 py-2 pr-10 text-sm" />
                <kbd aria-hidden="true" className="shortcut-key pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">/</kbd>
              </div>
              <ActionButton onClick={() => setShowJump(true)} title="Jump to clip index (G)" shortcut="G">Go to #</ActionButton>
            </div>
            {filter === "all" && <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="subtle min-w-0 text-xs">Filter status
                <select value={allStatusFilter} onChange={(event) => setAllStatusFilter(event.target.value as AllStatusFilter)}
                  aria-label="Filter clips by status" className="mt-1 block w-full rounded-lg border line bg-[#101816] px-2.5 py-2 text-sm text-[#e7eee7]">
                  <option value="all">All statuses</option>
                  {Object.entries(labels).map(([status, label]) => <option key={status} value={status}>{label}</option>)}
                </select>
              </label>
              <label className="subtle min-w-0 text-xs">Order by
                <select value={allOrder} onChange={(event) => setAllOrder(event.target.value as AllOrder)}
                  aria-label="Order clips" className="mt-1 block w-full rounded-lg border line bg-[#101816] px-2.5 py-2 text-sm text-[#e7eee7]">
                  {allOrders.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                </select>
              </label>
            </div>}
          </div>
          <div ref={clipListRef} className="panel-scroll min-h-0 flex-1 overflow-auto" role="listbox" aria-label="Clips">
            {visible.length === 0 ? <p className="subtle px-5 py-8 text-sm">No clips match this view.</p> : visible.map((clip) => {
              const changed = clip.start_ms !== clip.original_start_ms || clip.end_ms !== clip.original_end_ms;
              return <button key={clip.clip_id} type="button" role="option" aria-selected={clip.clip_id === effectiveSelectedId}
                data-selected={clip.clip_id === effectiveSelectedId} onClick={() => { setSelectedId(clip.clip_id); setShowDetailMobile(true); }}
                className="clip-row flex w-full items-start gap-3 border-b border-[#29362f] px-4 py-3 text-left transition-colors md:px-5">
                {filter === "all" && <span className={`status-dot status-${clip.status} mt-2`} aria-hidden="true" />}
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2"><span className="subtle mono shrink-0 text-xs">#{clip.clip_id}</span>
                    <span className="truncate text-sm font-medium" title={clip.title}>{clip.title}</span></span>
                  {filter === "all" && <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className={`clip-tag clip-tag-${clip.status}`}>{labels[clip.status]}</span>
                    {changed && <span className="clip-tag clip-tag-trimmed">Trimmed</span>}
                  </span>}
                </span>
                {filter !== "all" && changed && <span className="clip-tag clip-tag-trimmed shrink-0">Trimmed</span>}
                <span className="subtle mono shrink-0 text-xs">{formatDuration(clip.end_ms - clip.start_ms)}</span>
              </button>;
            })}
          </div>
        </section>

        <section className={`${showDetailMobile ? "flex" : "hidden md:flex"} min-h-0 flex-col overflow-hidden`} aria-label="Clip details">
          {selected ? <>
            <div className="shrink-0 border-b line px-4 py-2 md:px-7 md:py-3">
              <button type="button" onClick={() => setShowDetailMobile(false)} className="accent mb-2 text-sm md:hidden">← Back to clips</button>
              <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
                <span className="accent mono text-sm font-semibold tracking-wider">CLIP #{selected.clip_id}</span>
                <span className="subtle text-sm mono">{selectedPosition + 1} of {visible.length} in view</span>
              </div>
              {editingTitle ? <div className="flex gap-2">
                <input ref={titleRef} value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); void saveTitle(); }
                    if (event.key === "Escape") { setEditingTitle(false); }
                  }} aria-label="Clip title" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2" />
                <ActionButton onClick={() => void saveTitle()} disabled={busy || !titleDraft.trim()} tone="accent">Save</ActionButton>
                <ActionButton onClick={() => setEditingTitle(false)}>Cancel</ActionButton>
              </div> : <div className="flex flex-wrap items-start gap-3">
                <h2 className="min-w-0 flex-1 break-words text-2xl font-semibold leading-snug">{selected.title}</h2>
                <div className="ml-auto flex shrink-0 items-center gap-1.5">
                  <button type="button" onClick={() => moveSelection(-1)} disabled={selectedPosition <= 0}
                    aria-label="Previous clip (K)" title="Previous clip (K)"
                    className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">
                    <span aria-hidden="true">←</span><kbd aria-hidden="true" className="shortcut-key">K</kbd>
                  </button>
                  <button type="button" onClick={() => moveSelection(1)} disabled={selectedPosition >= visible.length - 1}
                    aria-label="Next clip (J)" title="Next clip (J)"
                    className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">
                    <span aria-hidden="true">→</span><kbd aria-hidden="true" className="shortcut-key">J</kbd>
                  </button>
                  <ActionButton onClick={() => setShowExportModal(true)} title="Open export preview (E)" shortcut="E" tone="accent">Export</ActionButton>
                  <div ref={clipMenuRef} className="relative">
                    <button type="button" onClick={() => setShowClipMenu((open) => !open)}
                      aria-label="More clip actions" aria-expanded={showClipMenu} aria-haspopup="menu" title="More clip actions"
                      className="soft-surface rounded-lg px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">…</button>
                    {showClipMenu && <div role="menu" aria-label="More clip actions"
                      className="surface absolute right-0 top-full z-20 mt-1 min-w-40 rounded-lg p-1 shadow-xl">
                      <button type="button" role="menuitem" onClick={() => {
                        setShowClipMenu(false); setTitleDraft(selected.title); setEditingTitle(true);
                      }} className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm hover:bg-[#304439]">
                        Rename <kbd aria-hidden="true" className="shortcut-key">R</kbd>
                      </button>
                      <button type="button" role="menuitem" disabled={busy} onClick={() => {
                        setShowClipMenu(false);
                        if (session.revision === null) return;
                        void mutate(() => api<Session>(`/clips/${encodeURIComponent(selected.clip_id)}/duplicate`, "POST", {
                          expected_revision: session.revision,
                        })).then((next) => { if (next?.created_clip_id) setSelectedId(next.created_clip_id); });
                      }} className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm hover:bg-[#304439]">
                        Duplicate <kbd aria-hidden="true" className="shortcut-key">D</kbd>
                      </button>
                    </div>}
                  </div>
                </div>
              </div>}
            </div>
            <div ref={detailScrollRef} className="panel-scroll min-h-0 flex-1 overflow-auto px-4 py-5 md:px-7">
              <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                <label htmlFor="clip-status" className="font-medium">Status</label>
                <span className="relative inline-flex">
                  <select id="clip-status" value={selected.status} disabled={busy}
                    onChange={(event) => patchSelected({ status: event.target.value as Status })}
                    className="appearance-none rounded-lg border line bg-[#22312a] py-2 pl-3 pr-9 text-[#e7eee7] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b4e2b6]">
                    {(["group1", "group2", "skipped", "pending"] as Status[]).map((status) =>
                      <option key={status} value={status}>{labels[status]}</option>)}
                    {selected.status === "exported" && <option value="exported">Exported</option>}
                  </select>
                  <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
                    className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-[#9eafa3]">
                    <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className="subtle inline-flex flex-wrap items-center gap-1.5 text-xs">
                  Choose Group 1 <kbd className="shortcut-key">1</kbd>, Group 2 <kbd className="shortcut-key">2</kbd>, or Skipped <kbd className="shortcut-key">X</kbd>
                </span>
              </div>
              <WaveformEditor key={selected.clip_id} clip={selected}
                durationMs={session.duration_ms ?? selected.end_ms} audioSrc={audioUrl()} busy={busy}
                shortcutsPaused={showHelp || showJump || showMerge || showExportModal || showSettings || editingTitle}
                detectLeadingSilence={settings.detectLeadingSilence}
                showOriginalStart={settings.showOriginalStart}
                active={!showExportModal && !showSettings}
                onSave={async (startMs, endMs) => {
                  if (session.revision === null) return false;
                  const next = await mutate(() => api<Session>(`/clips/${encodeURIComponent(selected.clip_id)}`, "PATCH", {
                    expected_revision: session.revision, start_ms: startMs, end_ms: endMs,
                  }));
                  return Boolean(next);
                }} />
            </div>
          </> : <div className="subtle flex flex-1 items-center justify-center p-6 text-center">Select a clip to review its details.</div>}
        </section>
      </main>
      </>}
      {selected && session.revision !== null && <ExportPreview key={selected.clip_id} clip={selected}
        revision={session.revision} open={showExportModal} nextClipId={nextVisibleClipId}
        onClose={() => setShowExportModal(false)} onPublished={(next, advance) => {
          setSession(next);
          setSaveState("saved");
          if (advance && nextVisibleClipId) {
            setSelectedId(nextVisibleClipId);
          } else if (!advance) {
            setSelectedId(selected.clip_id);
            const exportedClip = next.candidates.find((clip) => clip.clip_id === selected.clip_id);
            if (exportedClip && !visibleClips([exportedClip], filter, query, allStatusFilter).length) {
              setFilter("all");
              setAllStatusFilter("all");
              if (!visibleClips([exportedClip], "all", query, "all").length) setQuery("");
            }
          }
        }} />}
    </>}

    {showSettings && <Dialog title="Settings" onClose={() => setShowSettings(false)}>
      <SettingsScreen detectLeadingSilence={settings.detectLeadingSilence}
        showOriginalStart={settings.showOriginalStart}
        onDetectLeadingSilenceChange={(enabled) => setSettings((current) => ({ ...current, detectLeadingSilence: enabled }))}
        onShowOriginalStartChange={(enabled) => setSettings((current) => ({ ...current, showOriginalStart: enabled }))} />
    </Dialog>}

    {showJump && <Dialog title="Jump to clip index" onClose={() => setShowJump(false)}>
      <p className="subtle mb-3 text-sm">Find the requested index in the current view, or the nearest visible clip.</p>
      <form onSubmit={(event) => { event.preventDefault(); jumpToIndex(); }} className="flex gap-2">
        <input autoFocus type="number" min="1" value={jumpDraft} onChange={(event) => setJumpDraft(event.target.value)}
          aria-label="Clip index" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2" />
        <button className="rounded-lg bg-[#b7d69d] px-4 py-2 font-semibold text-[#1d2d20]">Go</button>
      </form>
    </Dialog>}

    {showMerge && session?.merge_preview && <Dialog title="Review SRT changes" onClose={() => setShowMerge(false)}>
      <p className="subtle mb-4 text-sm">Nothing changes until you apply this merge. Saved titles, groups, and trims are kept. A backup is made before any selected removal.</p>
      <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
        <span>Added entries: {session.merge_preview.added.length}</span>
        <span>Timing changes: {session.merge_preview.timing_changed.length}</span>
        <span>Text changes: {session.merge_preview.text_changed.length}</span>
        <span>Missing entries: {session.merge_preview.removed.length}</span>
      </div>
      {session.merge_preview.removed.length > 0 && <div className="mb-5">
        <h3 className="mb-2 text-sm font-medium">Missing SRT entries · kept unless selected</h3>
        <div className="panel-scroll max-h-44 overflow-auto rounded-lg border line p-2">
          {session.merge_preview.removed.map((index) => <label key={index} className="flex items-center gap-2 px-2 py-1 text-sm">
            <input type="checkbox" checked={removeIndexes.includes(index)} onChange={(event) =>
              setRemoveIndexes((current) => event.target.checked ? [...current, index] : current.filter((item) => item !== index))} />
            Remove #{index} and its duplicates
          </label>)}
        </div>
      </div>}
      {session.merge_preview.text_change_unverified && <p className="mb-4 text-sm text-[#ead49b]">The SRT file is newer than this older session. Text may have changed, but the original text was not saved for comparison.</p>}
      {session.merge_preview.unknown_original_text_clip_ids.length > 0 && !session.merge_preview.text_change_unverified && <p className="subtle mb-4 text-xs">This older session did not store original SRT text, so text changes cannot be detected for every saved clip.</p>}
      <div className="flex justify-end gap-2"><ActionButton onClick={() => setShowMerge(false)}>Cancel</ActionButton>
        <ActionButton tone="accent" onClick={() => void applyMerge()} disabled={busy}>Apply selected changes</ActionButton></div>
    </Dialog>}

    {showHelp && <Dialog title="Keyboard shortcuts" onClose={() => setShowHelp(false)}>
      <div className="grid grid-cols-[6rem_1fr] gap-y-2 text-sm">
        {[["Space", "Play from start"], ["Shift+Space", "Play / pause clip"], ["J / K", "Next / previous clip"], ["1 / 2", "Mark Group 1 / Group 2"],
          ["X", "Skip clip"], ["U", "Undo recent change"], ["D", "Duplicate clip"],
          ["R", "Rename title"], ["G", "Jump to index"], ["E", "Open export preview"],
          ["Enter", "Export (in preview)"], ["⌘ Enter", "Export & Next (in preview)"], ["/", "Search titles"],
          [", / .", "Nudge start − / + 10 ms (Shift: 100 ms)"],
          ["[ / ]", "Nudge end − / + 10 ms (Shift: 100 ms)"],
          ["?", "Show this help"]].map(([key, action]) => <div key={key} className="contents">
            <kbd className="accent mono">{key}</kbd><span>{action}</span>
          </div>)}
      </div>
      <p className="subtle mt-5 text-xs">Review shortcuts pause while you type. Enter and ⌘ Enter work in the export title field.</p>
    </Dialog>}
  </div>;
}
