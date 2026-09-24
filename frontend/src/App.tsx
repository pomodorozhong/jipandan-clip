import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, bootstrap, uploadAudio, type Clip, type Session, type Status } from "./api";

type Filter = "unsorted" | "group1" | "group2" | "exported" | "all";
type SaveState = "saved" | "saving" | "failed";

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

function formatTime(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  const milli = total % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(milli).padStart(3, "0")}`;
}

function formatDuration(ms: number): string {
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
}

function visibleClips(clips: Clip[], filter: Filter, query: string, hideProcessed: boolean): Clip[] {
  const needle = query.trim().normalize("NFKC").toLocaleLowerCase();
  return clips.filter((clip) => {
    if (filter === "unsorted" && clip.status !== "pending") return false;
    if (filter !== "unsorted" && filter !== "all" && clip.status !== filter) return false;
    if (hideProcessed && (clip.status === "exported" || clip.status === "skipped")) return false;
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
  return <div className="fixed inset-0 z-30 flex items-center justify-center bg-[#07100bcf] p-4"
    role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label={title}
      className="surface max-h-[85vh] w-full max-w-lg overflow-auto rounded-2xl p-5 shadow-2xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Close dialog" className="subtle text-xl">×</button>
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
  const [query, setQuery] = useState("");
  const [hideProcessed, setHideProcessed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [showJump, setShowJump] = useState(false);
  const [jumpDraft, setJumpDraft] = useState("");
  const [showMerge, setShowMerge] = useState(false);
  const [removeIndexes, setRemoveIndexes] = useState<number[]>([]);
  const [showDetailMobile, setShowDetailMobile] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

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
          filter?: Filter; selectedId?: string; hideProcessed?: boolean;
        };
        if (preferences.filter && filters.some((item) => item.key === preferences.filter)) {
          setFilter(preferences.filter);
        } else if (session.counts.pending === 0) setFilter("all");
        setSelectedId(preferences.selectedId ?? null);
        setHideProcessed(preferences.hideProcessed ?? false);
      } catch {
        if (session.counts.pending === 0) setFilter("all");
      }
    } else if (session.counts.pending === 0) setFilter("all");
  }, [session?.audio]);

  useEffect(() => {
    if (!session?.audio) return;
    localStorage.setItem(`jipandan-review:${session.audio}`, JSON.stringify({
      filter, selectedId, hideProcessed,
    }));
  }, [session?.audio, filter, selectedId, hideProcessed]);

  const visible = useMemo(
    () => visibleClips(session?.candidates ?? [], filter, query, hideProcessed),
    [session?.candidates, filter, query, hideProcessed],
  );
  const effectiveSelectedId = visible.some((clip) => clip.clip_id === selectedId)
    ? selectedId : (visible[0]?.clip_id ?? null);
  const selected = session?.candidates.find((clip) => clip.clip_id === effectiveSelectedId) ?? null;
  const selectedPosition = visible.findIndex((clip) => clip.clip_id === effectiveSelectedId);
  const throughCurrent = selectedPosition < 0 ? [] : visible.slice(0, selectedPosition + 1);
  const bulkPending = throughCurrent.filter((clip) => clip.status === "pending");
  const hasMergeChanges = Boolean(session?.merge_preview && (
    session.merge_preview.added.length || session.merge_preview.removed.length ||
    session.merge_preview.timing_changed.length || session.merge_preview.text_changed.length ||
    session.merge_preview.file_changed
  ));

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
      if (visibleClips([changed], filter, query, hideProcessed).length === 0) {
        nextSelection = visible[selectedPosition + 1]?.clip_id ??
          visible[selectedPosition - 1]?.clip_id ?? effectiveSelectedId;
      }
    }
    void mutate(() => api<Session>(`/clips/${encodeURIComponent(effectiveSelectedId)}`, "PATCH", {
      expected_revision: session.revision, ...change,
    })).then((next) => { if (next) setSelectedId(nextSelection); });
  }, [session, effectiveSelectedId, selected, filter, query, hideProcessed,
    visible, selectedPosition, mutate]);

  const moveSelection = useCallback((delta: number) => {
    if (!visible.length) return;
    const position = Math.max(0, Math.min(visible.length - 1, selectedPosition + delta));
    setSelectedId(visible[position].clip_id);
    setShowDetailMobile(false);
  }, [visible, selectedPosition]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (showHelp || showBulk || showJump || showMerge || editingTitle) return;
      if (event.isComposing || event.key === "Process") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable='true']"))) return;
      const key = event.key.toLowerCase();
      if (key === "j" || key === "arrowdown") { event.preventDefault(); moveSelection(1); }
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
  }, [showHelp, showBulk, showJump, showMerge, editingTitle, moveSelection, patchSelected,
    session, selected, effectiveSelectedId, mutate]);

  useEffect(() => { if (editingTitle) titleRef.current?.focus(); }, [editingTitle]);

  async function openAudio(event: React.FormEvent) {
    event.preventDefault();
    if (!openPath.trim()) return;
    const next = await mutate(() => api<Session>("/session/open", "POST", { path: openPath.trim() }));
    if (next) {
      setQuery(""); setSelectedId(null); setFilter(next.counts.pending > 0 ? "unsorted" : "all");
    }
  }

  async function openPickedAudio(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const next = await mutate(() => uploadAudio(file));
    if (next) { setQuery(""); setSelectedId(null); setFilter("unsorted"); }
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
    if (target) setSelectedId(target.clip_id);
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

  if (initializing) return <main className="flex min-h-screen items-center justify-center subtle">Opening Jipandan…</main>;

  return <div className="flex min-h-screen flex-col">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b line px-4 py-3 md:px-7">
      <div className="flex items-center gap-3">
        <div aria-hidden="true" className="flex size-9 items-center justify-center rounded-xl bg-[#b7d69d] text-xl font-bold text-[#263c2b]">J</div>
        <div>
          <div className="font-semibold tracking-wide">Jipandan <span className="subtle font-normal">/ clip review</span></div>
          <div className="subtle text-xs">Local workspace · {session?.audio_name ?? "No audio open"}</div>
        </div>
      </div>
      <div className="flex items-center gap-3 text-sm">
        {session?.audio && <span aria-live="polite" className={saveState === "failed" ? "text-[#ffb3a8]" : saveState === "saving" ? "text-[#ead49b]" : "accent"}>
          {saveState === "saving" ? "Saving…" : saveState === "failed" ? "Save failed" : "Saved"}
        </span>}
        {session?.audio && <ActionButton onClick={() => {
          if (session.revision === null) return;
          void mutate(() => api<Session>("/session/undo", "POST", { expected_revision: session.revision }));
        }} disabled={!session.can_undo || busy} title="Undo recent change (U)" shortcut="U">Undo</ActionButton>}
        <ActionButton onClick={() => setShowHelp(true)} title="Keyboard shortcuts" shortcut="?">Shortcuts</ActionButton>
      </div>
    </header>

    {error && <div role="alert" className="border-b border-[#a96053] bg-[#482d2a] px-5 py-3 text-sm text-[#ffe3dc]">
      {error} <button className="ml-3 underline" onClick={() => setError("")}>Dismiss</button>
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
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b line px-4 py-2 text-xs md:px-7">
        <span><span className="subtle">Duration</span> <span className="mono">{formatDuration(session.duration_ms ?? 0)}</span></span>
        <span><span className="subtle">SRT</span> {session.srt_exists ? "Found" : "Missing"}</span>
        <span className="hidden min-w-0 truncate lg:inline"><span className="subtle">Session</span> {session.session_path ?? "Not created"}</span>
        <span className="hidden min-w-0 truncate xl:inline"><span className="subtle">Exports</span> {session.clip_dir}</span>
      </div>
      {hasMergeChanges && <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#7c6845] bg-[#3c3525] px-4 py-2 text-sm md:px-7">
        <span>The SRT changed since this session was saved. Your reviewed clips are still here.</span>
        <ActionButton onClick={() => setShowMerge(true)}>Review SRT changes</ActionButton>
      </div>}
      {session.needs_transcription ? <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-5 py-12">
        <h1 className="mb-3 text-3xl font-semibold">No SRT yet</h1>
        <p className="subtle">Transcription will be available in the next build. You can use the existing <code>transcribe</code> command, then reopen this audio.</p>
      </main> : <main className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(310px,38%)_1fr]">
        <section className={`${showDetailMobile ? "hidden md:flex" : "flex"} min-h-0 flex-col border-r line`} aria-label="Clip list">
          <div className="border-b line p-4 md:p-5">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h1 className="text-xl font-semibold">Clips</h1>
              <span className="subtle text-sm mono">{visible.length} visible / {session.candidates.length} total</span>
            </div>
            <div className="mb-3 flex flex-wrap gap-1 md:grid md:grid-cols-2 xl:grid-cols-6 2xl:flex" role="group" aria-label="Status filter">
              {filters.map((item) => <button key={item.key} type="button" onClick={() => setFilter(item.key)}
                aria-pressed={filter === item.key}
                aria-label={`${item.label}, ${item.key === "all" ? session.candidates.length : session.counts[item.key === "unsorted" ? "pending" : item.key]} clips`}
                className={`inline-flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium ${item.key === "exported" || item.key === "all" ? "xl:col-span-3" : "xl:col-span-2"} 2xl:col-auto ${filter === item.key ? "bg-[#b7d69d] text-[#1b291f]" : "soft-surface subtle hover:text-white"}`}>
                <span>{item.label}</span><span aria-hidden="true" className={`mono min-w-6 rounded-full px-1.5 py-0.5 text-center text-[11px] font-semibold leading-none ${filter === item.key ? "bg-[#1b291f]/15" : "bg-[#415447] text-[#edf2ee]"}`}>
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
            <label className="subtle mt-3 flex items-center gap-2 text-xs">
              <input type="checkbox" checked={hideProcessed} onChange={(event) => setHideProcessed(event.target.checked)} />
              Hide exported and skipped
            </label>
          </div>
          <div className="panel-scroll max-h-[calc(100vh-315px)] min-h-32 flex-1 overflow-auto md:max-h-[calc(100vh-265px)]" role="listbox" aria-label="Clips">
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

        <section className={`${showDetailMobile ? "flex" : "hidden md:flex"} min-h-0 flex-col`} aria-label="Clip details">
          {selected ? <>
            <div className="border-b line px-4 py-4 md:px-7 md:py-5">
              <button type="button" onClick={() => setShowDetailMobile(false)} className="accent mb-3 text-sm md:hidden">← Back to clips</button>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
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
              </div> : <div className="flex items-start gap-3">
                <h2 className="min-w-0 flex-1 break-words text-2xl font-semibold leading-snug">{selected.title}</h2>
                <ActionButton onClick={() => { setTitleDraft(selected.title); setEditingTitle(true); }} title="Rename (R)" shortcut="R">Rename</ActionButton>
              </div>}
              <div className="mt-4 flex flex-wrap gap-2">
                <ActionButton onClick={() => moveSelection(-1)} disabled={selectedPosition <= 0} title="Previous clip (K)" shortcut="K">← Previous</ActionButton>
                <ActionButton onClick={() => moveSelection(1)} disabled={selectedPosition >= visible.length - 1} title="Next clip (J)" shortcut="J">Next →</ActionButton>
                <ActionButton onClick={() => {
                  if (session.revision === null) return;
                  void mutate(() => api<Session>(`/clips/${encodeURIComponent(selected.clip_id)}/duplicate`, "POST", {
                    expected_revision: session.revision,
                  })).then((next) => { if (next?.created_clip_id) setSelectedId(next.created_clip_id); });
                }} disabled={busy} title="Duplicate (D)" shortcut="D">Duplicate</ActionButton>
              </div>
            </div>
            <div className="panel-scroll flex-1 overflow-auto px-4 py-5 md:px-7">
              <div className="mb-6">
                <h3 className="subtle mb-3 text-xs font-semibold uppercase tracking-[.15em]">Classification</h3>
                <div className="flex flex-wrap gap-2">
                  {(["group1", "group2", "skipped", "pending"] as Status[]).map((status) =>
                    <ActionButton key={status} tone={selected.status === status ? "accent" : "normal"}
                      onClick={() => patchSelected({ status })} disabled={busy || selected.status === status}
                      title={`${labels[status]}${status === "group1" ? " (1)" : status === "group2" ? " (2)" : status === "skipped" ? " (X)" : ""}`}
                      shortcut={status === "group1" ? "1" : status === "group2" ? "2" : status === "skipped" ? "X" : undefined}>
                      {labels[status]}
                    </ActionButton>)}
                </div>
              </div>
              <div className="surface mb-6 rounded-xl p-4">
                <div className="mb-4 flex items-center justify-between gap-2">
                  <h3 className="font-medium">Source segment</h3>
                  <span className="subtle text-xs">Trim controls arrive in the waveform build</span>
                </div>
                <div className="grid gap-4 text-sm sm:grid-cols-2">
                  <div><span className="subtle block text-xs">Start</span><span className="mono">{formatTime(selected.start_ms)}</span></div>
                  <div><span className="subtle block text-xs">End</span><span className="mono">{formatTime(selected.end_ms)}</span></div>
                  <div><span className="subtle block text-xs">Original start</span><span className="mono">{formatTime(selected.original_start_ms)}</span></div>
                  <div><span className="subtle block text-xs">Original end</span><span className="mono">{formatTime(selected.original_end_ms)}</span></div>
                </div>
                <div className="mt-4 border-t line pt-3 text-sm"><span className="subtle">Current duration</span> <strong className="mono ml-2">{formatDuration(selected.end_ms - selected.start_ms)}</strong></div>
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton onClick={() => {
                  if (session.revision === null) return;
                  void mutate(() => api<Session>("/session/undo", "POST", { expected_revision: session.revision }));
                }} disabled={!session.can_undo || busy} title="Undo last change (U)" shortcut="U">Undo last change</ActionButton>
                <ActionButton onClick={() => setShowBulk(true)} disabled={bulkPending.length === 0 || busy} tone="danger">
                  Skip through current · {bulkPending.length}
                </ActionButton>
              </div>
            </div>
          </> : <div className="subtle flex flex-1 items-center justify-center p-6 text-center">Select a clip to review its details.</div>}
        </section>
      </main>}
    </>}

    {showBulk && <Dialog title="Skip through current clip" onClose={() => setShowBulk(false)}>
      <p className="subtle mb-5 text-sm">This will skip <strong className="text-white">{bulkPending.length} unsorted {bulkPending.length === 1 ? "clip" : "clips"}</strong> in the current filtered view through #{selected?.clip_id}. Grouped and exported clips stay as they are. You can undo this action.</p>
      <div className="flex justify-end gap-2"><ActionButton onClick={() => setShowBulk(false)}>Cancel</ActionButton>
        <ActionButton tone="danger" onClick={() => {
          if (session?.revision === null) return;
          const nextVisible = visible.slice(selectedPosition + 1).find((clip) => clip.status === "pending");
          void mutate(() => api<Session>("/clips/bulk-skip", "POST", {
            expected_revision: session!.revision,
            clip_ids: throughCurrent.map((clip) => clip.clip_id),
          })).then((next) => {
            if (next) {
              setShowBulk(false);
              if (filter === "unsorted" && nextVisible) setSelectedId(nextVisible.clip_id);
            }
          });
        }} disabled={busy}>Skip {bulkPending.length}</ActionButton></div>
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
        {[["J / K", "Next / previous clip"], ["1 / 2", "Mark Group 1 / Group 2"],
          ["X", "Skip clip"], ["U", "Undo recent change"], ["D", "Duplicate clip"],
          ["R", "Rename title"], ["G", "Jump to index"], ["/", "Search titles"],
          ["?", "Show this help"]].map(([key, action]) => <div key={key} className="contents">
            <kbd className="accent mono">{key}</kbd><span>{action}</span>
          </div>)}
      </div>
      <p className="subtle mt-5 text-xs">Shortcuts pause while you type in a search, title, or other input.</p>
    </Dialog>}
  </div>;
}
