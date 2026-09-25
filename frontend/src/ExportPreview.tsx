import { useCallback, useEffect, useRef, useState } from "react";
import { api, previewUrl, type Clip, type ExportMode, type PreviewJob, type Session, type WaveformWindow } from "./api";
import PreviewPlayer, { type PreviewPlayerHandle } from "./PreviewPlayer";

const descriptions: Record<ExportMode, string> = {
  as_is: "Keep the selected clip exactly as it is.",
  trim_edges: "Remove silence at the start and end; keep pauses in the middle.",
  trim_all: "Also shorten pauses in the middle. This can change speech rhythm.",
};

const modes: { value: ExportMode; label: string; key: string }[] = [
  { value: "as_is", label: "As is", key: "A" },
  { value: "trim_edges", label: "Trim edges", key: "E" },
  { value: "trim_all", label: "Trim all", key: "T" },
];

function duration(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`;
}

function peak(waveform: WaveformWindow | null): number {
  if (!waveform) return 0;
  let result = 0;
  for (const value of waveform.mins) result = Math.max(result, Math.abs(value));
  for (const value of waveform.maxs) result = Math.max(result, Math.abs(value));
  return result;
}

export default function ExportPreview({ clip, revision, open, nextClipId, onClose, onPublished }: {
  clip: Clip; revision: number; open: boolean; onClose: () => void;
  nextClipId: string | null;
  onPublished: (session: Session, advance: boolean) => void;
}) {
  const [mode, setMode] = useState<ExportMode>("trim_edges");
  const [startDb, setStartDb] = useState("-40");
  const [stopDb, setStopDb] = useState("-50");
  const [title, setTitle] = useState(clip.title);
  const [job, setJob] = useState<PreviewJob | null>(null);
  const [referenceJob, setReferenceJob] = useState<PreviewJob | null>(null);
  const [error, setError] = useState("");
  const [referenceError, setReferenceError] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [referenceRequesting, setReferenceRequesting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const referenceStartedFor = useRef("");
  const candidateWasOpen = useRef(false);
  const exportInFlight = useRef(false);
  const referenceRequestId = useRef(0);
  const referencePlayer = useRef<PreviewPlayerHandle>(null);
  const candidatePlayer = useRef<PreviewPlayerHandle>(null);

  useEffect(() => { setTitle(clip.title); }, [clip.clip_id, clip.title]);

  useEffect(() => {
    if (!open || !job || (job.state !== "queued" && job.state !== "running")) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api<PreviewJob>(`/previews/${job.id}`).then((next) => {
        if (alive) setJob(next);
      }).catch((cause) => {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      });
    }, 700);
    return () => { alive = false; window.clearInterval(timer); };
  }, [open, job?.id, job?.state]);

  useEffect(() => {
    if (!open || !referenceJob || (referenceJob.state !== "queued" && referenceJob.state !== "running")) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api<PreviewJob>(`/previews/${referenceJob.id}`).then((next) => {
        if (alive) setReferenceJob(next);
      }).catch((cause) => {
        if (alive) setReferenceError(cause instanceof Error ? cause.message : String(cause));
      });
    }, 700);
    return () => { alive = false; window.clearInterval(timer); };
  }, [open, referenceJob?.id, referenceJob?.state]);

  const start = Number(startDb);
  const stop = Number(stopDb);
  const validThresholds = mode === "as_is" || (
    startDb.trim() !== "" && stopDb.trim() !== "" &&
    Number.isFinite(start) && Number.isFinite(stop) &&
    start >= -90 && start <= -5 && stop >= -90 && stop <= -5
  );
  const stale = Boolean(job && (
    job.stale || job.start_ms !== clip.start_ms || job.end_ms !== clip.end_ms ||
    job.clip_title !== clip.title || job.mode !== mode ||
    job.start_threshold_db !== (mode === "as_is" ? -40 : start) ||
    job.stop_threshold_db !== (mode === "as_is" ? -50 : stop) ||
    job.title !== title.trim()
  ));
  const referenceStale = Boolean(referenceJob && (
    referenceJob.stale || referenceJob.start_ms !== clip.start_ms ||
    referenceJob.end_ms !== clip.end_ms || referenceJob.clip_title !== clip.title
  ));
  const candidateReady = Boolean(job?.state === "completed" && !stale && job.duration_ms);
  const referenceReady = Boolean(referenceJob?.state === "completed" && !referenceStale && referenceJob.duration_ms);
  const selectedDuration = clip.end_ms - clip.start_ms;
  const referenceDuration = referenceReady ? referenceJob?.duration_ms ?? selectedDuration : selectedDuration;
  const candidateDuration = candidateReady ? job?.duration_ms ?? 0 : 0;
  const sharedPeak = Math.max(peak(referenceReady ? referenceJob?.waveform ?? null : null),
    peak(candidateReady ? job?.waveform ?? null : null));

  function chooseMode(next: ExportMode) {
    setMode(next);
    if (next === "trim_all") { setStartDb("-30"); setStopDb("-30"); }
    if (next === "trim_edges") { setStartDb("-40"); setStopDb("-50"); }
  }

  const publish = useCallback(async (advance: boolean) => {
    if (!candidateReady || !job || exporting || requesting || exportInFlight.current ||
        (advance && !nextClipId)) return;
    exportInFlight.current = true;
    setExporting(true);
    setExportError("");
    try {
      const result = await api<Session>("/exports", "POST", {
        preview_id: job.id, expected_revision: revision,
      });
      setOutputPath(result.output_path ?? "");
      onPublished(result, advance);
    } catch (cause) {
      setExportError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      exportInFlight.current = false;
      setExporting(false);
    }
  }, [candidateReady, job, exporting, requesting, nextClipId, revision, onPublished]);

  async function reveal() {
    setExportError("");
    try {
      await api(`/clips/${encodeURIComponent(clip.clip_id)}/reveal-export`, "POST");
    } catch (cause) {
      setExportError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  useEffect(() => {
    if (!open) {
      candidateWasOpen.current = false;
      setRequesting(false);
      return;
    }
    const delay = candidateWasOpen.current ? 450 : 0;
    candidateWasOpen.current = true;
    candidatePlayer.current?.pause();
    setError("");
    if (!validThresholds || !title.trim()) {
      setRequesting(false);
      return;
    }
    setRequesting(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void api<PreviewJob>("/previews", "POST", {
        clip_id: clip.clip_id, expected_revision: revision, mode,
        start_threshold_db: mode === "as_is" ? -40 : start,
        stop_threshold_db: mode === "as_is" ? -50 : stop,
        title: title.trim(),
      }, controller.signal).then((next) => {
        if (!controller.signal.aborted) setJob(next);
      }).catch((cause) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
      }).finally(() => {
        if (!controller.signal.aborted) setRequesting(false);
      });
    }, delay);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, clip.clip_id, clip.start_ms, clip.end_ms, clip.title, revision,
    mode, startDb, stopDb, title, validThresholds, start, stop]);

  const renderReference = useCallback(async () => {
    const requestId = ++referenceRequestId.current;
    referencePlayer.current?.pause();
    setReferenceRequesting(true);
    setReferenceError("");
    setReferenceJob(null);
    try {
      const next = await api<PreviewJob>("/previews", "POST", {
        clip_id: clip.clip_id, expected_revision: revision, mode: "as_is",
        start_threshold_db: -40, stop_threshold_db: -50, title: clip.title,
      });
      if (requestId === referenceRequestId.current) setReferenceJob(next);
    } catch (cause) {
      if (requestId === referenceRequestId.current) setReferenceError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (requestId === referenceRequestId.current) setReferenceRequesting(false);
    }
  }, [clip.clip_id, clip.title, revision]);

  useEffect(() => {
    if (!open) { referenceStartedFor.current = ""; return; }
    const requestKey = `${clip.clip_id}:${clip.start_ms}:${clip.end_ms}:${clip.title}:${revision}`;
    if (referenceStartedFor.current === requestKey) return;
    referenceStartedFor.current = requestKey;
    void renderReference();
  }, [open, clip.clip_id, clip.start_ms, clip.end_ms, clip.title, revision, renderReference]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.isComposing || event.key === "Process") return;
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey && event.key === "Enter") {
        event.preventDefault();
        if (!event.repeat) void publish(true);
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (event.key === "Enter" && !event.shiftKey && !target?.closest("button, a, [role='button']")) {
        event.preventDefault();
        if (!event.repeat) void publish(false);
        return;
      }
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.code === "Space") {
        event.preventDefault();
        if (!event.repeat) event.shiftKey ? candidatePlayer.current?.replay() : candidatePlayer.current?.toggle();
        return;
      }
      if (event.code === "KeyQ") {
        event.preventDefault();
        if (!event.repeat) event.shiftKey ? referencePlayer.current?.replay() : referencePlayer.current?.toggle();
        return;
      }
      if (event.shiftKey) return;
      const key = event.key.toLowerCase();
      if (key === "a") { event.preventDefault(); chooseMode("as_is"); }
      else if (key === "e") { event.preventDefault(); chooseMode("trim_edges"); }
      else if (key === "t") { event.preventDefault(); chooseMode("trim_all"); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, publish]);

  if (!open) return null;

  const candidatePlaceholder = error ? "Could not update the candidate. Change a setting to try again."
    : !title.trim() ? "Enter an export title to update the candidate."
      : !validThresholds ? "Enter valid thresholds to update the candidate."
        : stale ? "Settings changed. Updating the candidate automatically…"
    : job?.state === "failed" ? "The candidate render failed. Adjust the settings to retry."
      : job?.state === "completed" ? "Waveform unavailable. Audio can still be played."
        : job?.state === "running" ? "Rendering the export candidate…"
          : requesting ? "Updating the export candidate…" : "Preparing the export candidate…";
  const referencePlaceholder = referenceJob?.state === "failed" ? "The As is render failed. Retry the reference."
    : referenceJob?.state === "completed" ? "Waveform unavailable. Audio can still be played."
      : referenceJob?.state === "running" ? "Rendering the As is reference…"
        : "Preparing the As is reference…";
  const difference = candidateDuration - referenceDuration;

  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-[#07100be0] p-2 sm:p-5"
    role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label={`Export preview for clip ${clip.clip_id}`}
      className="surface panel-scroll flex max-h-[95dvh] w-full max-w-[1100px] flex-col overflow-y-auto rounded-2xl shadow-2xl">
      <header className="flex items-center justify-between gap-4 border-b line px-4 py-4 sm:px-7">
        <div className="min-w-0">
          <p className="accent mono text-[11px] font-bold uppercase tracking-[.16em]">Export preview · Clip #{clip.clip_id}</p>
          <h2 className="mt-1 break-words text-xl font-semibold">{clip.title}</h2>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <span className="subtle hidden text-xs sm:block">Compare the original clip with your export</span>
          <button type="button" onClick={onClose} aria-label="Close export preview (Esc)"
            className="subtle inline-flex items-center gap-1.5 rounded-lg px-1 py-1 text-xl hover:bg-[#283b30]">
            <span aria-hidden="true">×</span><kbd aria-hidden="true" className="shortcut-key text-xs">Esc</kbd>
          </button>
        </div>
      </header>

      <div className="border-b line bg-[#1b2821] px-4 py-4 sm:px-7">
        <h3 className="subtle text-[11px] font-bold uppercase tracking-[.15em]">Export settings</h3>
        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2">
          <div role="group" aria-label="Export mode" className="inline-flex flex-wrap gap-1 rounded-lg border line bg-[#101b16] p-1">
            {modes.map((item) => <button key={item.value} type="button" onClick={() => chooseMode(item.value)}
              aria-pressed={mode === item.value}
              className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-semibold ${mode === item.value
                ? "bg-[#c5dda9] text-[#1f3021]" : "subtle hover:bg-[#304538] hover:text-white"}`}>
              <span>{item.label}</span><kbd aria-hidden="true" className="shortcut-key">{item.key}</kbd>
            </button>)}
          </div>
          <p className="subtle text-xs">{descriptions[mode]}</p>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          {mode !== "as_is" && <>
            <label className="w-28 shrink-0 text-xs font-medium">Start threshold
              <span className="relative mt-1 block"><input type="number" min="-90" max="-5" step="1" value={startDb}
                onChange={(event) => setStartDb(event.target.value)} aria-label="Start threshold in dB"
                className="w-full rounded-lg border line bg-[#101816] px-3 py-2 pr-9" /><span className="subtle pointer-events-none absolute right-3 top-2">dB</span></span>
            </label>
            <label className="w-28 shrink-0 text-xs font-medium">Stop threshold
              <span className="relative mt-1 block"><input type="number" min="-90" max="-5" step="1" value={stopDb}
                onChange={(event) => setStopDb(event.target.value)} aria-label="Stop threshold in dB"
                className="w-full rounded-lg border line bg-[#101816] px-3 py-2 pr-9" /><span className="subtle pointer-events-none absolute right-3 top-2">dB</span></span>
            </label>
          </>}
          <label className="min-w-44 flex-1 text-xs font-medium">Export title
            <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={180}
              className="mt-1 block w-full rounded-lg border line bg-[#101816] px-3 py-2" />
          </label>
          <p role="status" className="subtle flex shrink-0 items-center gap-2 pb-2 text-xs">
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${error || job?.state === "failed" && !stale
              ? "bg-[#ffb3a8]" : candidateReady ? "bg-[#b7d69d]" : "bg-[#ead49b]"}`} />
            {!title.trim() || !validThresholds ? "Waiting for valid settings"
              : error || job?.state === "failed" && !stale ? "Preview update failed"
                : requesting || stale || job?.state === "queued" || job?.state === "running" ? "Updating preview…"
                  : candidateReady ? "Preview up to date" : "Preview updates automatically"}
          </p>
        </div>
        {!validThresholds && <p role="alert" className="mt-2 text-xs text-[#ffb3a8]">Enter thresholds from −90 to −5 dB.</p>}
        {error && <p role="alert" className="mt-2 text-xs text-[#ffb3a8]">{error}</p>}
      </div>

      <div className="px-4 py-4 sm:px-7">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="subtle text-[11px] font-bold uppercase tracking-[.15em]">Compare audio</h3>
          <p className="subtle text-[11px]">Play either version or click its waveform to seek</p>
        </div>
        <div className="space-y-3">
          <PreviewPlayer ref={referencePlayer} variant="reference" eyebrow="Reference · unchanged" title="As is"
            durationLabel="Selected clip" durationText={duration(selectedDuration)}
            note="Includes the original edges and pauses" startMs={0} endMs={referenceDuration}
            waveform={referenceReady ? referenceJob?.waveform ?? null : null} sharedPeak={sharedPeak}
            src={referenceReady ? previewUrl(referenceJob!.id) : undefined} placeholder={referencePlaceholder}
            playShortcut="Q" replayShortcut="⇧Q" onActivate={() => candidatePlayer.current?.pause()} />
          {(referenceError || referenceJob?.state === "failed") && <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-[#ffb3a8]">
            <span>{referenceError || `Reference render failed: ${referenceJob?.error ?? "Unknown error"}`}</span>
            <button type="button" onClick={() => void renderReference()} disabled={referenceRequesting}
              className="rounded-md border line px-2 py-1 text-white disabled:opacity-50">Retry reference</button>
          </div>}
          <PreviewPlayer ref={candidatePlayer} variant="candidate" eyebrow={`Export candidate · ${modes.find((item) => item.value === mode)?.label}`}
            title="Rendered preview" durationLabel="Rendered result"
            durationText={candidateReady ? duration(candidateDuration) : "—"}
            note={candidateReady ? difference === 0 ? "Same length as the reference"
              : `${duration(Math.abs(difference))} ${difference < 0 ? "shorter" : "longer"} than the reference`
              : "Updates automatically when settings change"}
            startMs={0} endMs={candidateDuration} waveform={candidateReady ? job?.waveform ?? null : null}
            sharedPeak={sharedPeak} src={candidateReady ? previewUrl(job!.id) : undefined}
            placeholder={candidatePlaceholder} playShortcut="Space" replayShortcut="⇧Space"
            onActivate={() => referencePlayer.current?.pause()} />
          {job?.state === "failed" && !stale && <p role="alert" className="text-xs text-[#ffb3a8]">Render failed: {job.error}. Adjust the settings to retry.</p>}
        </div>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t line bg-[#17211d] px-4 py-4 sm:px-7">
        <div className="min-w-0 flex-1"><p className="subtle text-[10px] font-bold uppercase tracking-[.12em]">{outputPath ? "Exported file" : "Proposed filename"}</p>
          <p className="mt-1 break-all text-xs font-semibold">{outputPath || (job && !stale ? job.proposed_filename : "Filename updates with the preview")}</p>
          <p className="subtle mt-1 break-all text-[11px]">{outputPath
            ? `Next export: ${job && !stale ? job.proposed_filename : "filename updates with the preview"}`
            : "Saved in the session’s export directory"}</p>
          {exportError && <p role="alert" className="mt-2 text-xs text-[#ffb3a8]">{exportError}</p>}
        </div>
        <div className="subtle flex flex-wrap items-center gap-2 text-xs">
          <span>As is <strong className="text-[#d3ecf3]">{duration(referenceDuration)}</strong></span>
          <span aria-hidden="true">→</span>
          <span>{modes.find((item) => item.value === mode)?.label} <strong className="text-[#d8edb6]">{candidateReady ? duration(candidateDuration) : "—"}</strong></span>
          {candidateReady && <span>· {difference < 0 ? "Shorter" : difference > 0 ? "Longer" : "Difference"} <strong className="text-[#d8edb6]">{duration(Math.abs(difference))}</strong></span>}
        </div>
        <div className="flex gap-2">
          {outputPath && <button type="button" onClick={() => void reveal()}
            className="rounded-lg border line px-4 py-2 text-sm font-semibold">Reveal file</button>}
          <button type="button" onClick={() => void publish(false)} disabled={!candidateReady || exporting || requesting}
            className="rounded-lg border line px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50">
            Export <kbd aria-hidden="true" className="shortcut-key ml-2">Enter</kbd></button>
          <button type="button" onClick={() => void publish(true)} disabled={!candidateReady || exporting || requesting || !nextClipId}
            title={nextClipId ? "Export and open the next clip (Command+Enter)" : "No next clip in this view"}
            className="rounded-lg bg-[#b7d69d] px-4 py-2 text-sm font-semibold text-[#1d2d20] disabled:cursor-not-allowed disabled:opacity-50">
            {exporting ? "Exporting…" : "Export & Next"}
            <kbd aria-hidden="true" className="shortcut-key ml-2">⌘ Enter</kbd>
          </button>
        </div>
      </footer>
    </section>
  </div>;
}
