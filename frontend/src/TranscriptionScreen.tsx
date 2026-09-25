import { useEffect, useState } from "react";
import { api, eventsUrl, type Session, type TranscriptionJob } from "./api";

function elapsed(start: number | null, end: number | null, now: number): string {
  if (!start) return "—";
  const seconds = Math.max(0, Math.floor((end ?? now) - start));
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

export default function TranscriptionScreen({ session, onReady }: {
  session: Session; onReady: (next: Session) => void;
}) {
  const [job, setJob] = useState<TranscriptionJob | null>(session.transcription);
  const [model, setModel] = useState(job?.settings.model_name ?? "large-v3");
  const [language, setLanguage] = useState(job?.settings.language ?? "");
  const [temperature, setTemperature] = useState(String(job?.settings.temperature ?? 0));
  const [context, setContext] = useState(String(job?.settings.max_context ?? 0));
  const [threshold, setThreshold] = useState(String(job?.settings.entropy_thold ?? 3));
  const [now, setNow] = useState(Date.now() / 1000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [eventsConnected, setEventsConnected] = useState(false);
  const active = job?.state === "queued" || job?.state === "running";

  useEffect(() => {
    if (!job || !active) return;
    const source = new EventSource(eventsUrl());
    source.onopen = () => setEventsConnected(true);
    source.onerror = () => setEventsConnected(false);
    source.onmessage = (event) => {
      try {
        const update = JSON.parse(event.data) as { transcription: TranscriptionJob | null };
        if (update.transcription?.id === job.id) setJob(update.transcription);
      } catch { /* Reconnect and polling remain available. */ }
    };
    return () => { source.close(); setEventsConnected(false); };
  }, [job?.id, active]);

  useEffect(() => {
    if (!job || !active) return;
    let alive = true;
    const timer = window.setInterval(() => {
      setNow(Date.now() / 1000);
      if (eventsConnected) return;
      void api<TranscriptionJob>(`/transcriptions/${job.id}`).then((next) => {
        if (alive) setJob(next);
      }).catch((cause) => {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      });
    }, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, active, eventsConnected]);

  async function start() {
    if (!session.audio || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<TranscriptionJob>("/transcriptions", "POST", {
        audio: session.audio, model_name: model.trim(), language: language.trim() || null,
        temperature: Number(temperature), max_context: Number(context),
        entropy_thold: Number(threshold),
      });
      setJob(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function act(action: "retry" | "cancel") {
    if (!job || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<TranscriptionJob>(`/transcriptions/${job.id}/${action}`, "POST");
      setJob(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function openReview() {
    setBusy(true);
    setError("");
    try {
      onReady(await api<Session>("/session"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return <main className="panel-scroll mx-auto w-full max-w-3xl flex-1 overflow-auto px-5 py-8 md:py-12">
    <p className="accent mb-3 text-xs font-bold uppercase tracking-[.16em]">Transcription</p>
    <h1 className="mb-2 text-3xl font-semibold">Create subtitles for {session.audio_name}</h1>
    <p className="subtle mb-7 text-sm">The transcript is saved beside your recording when the job finishes.</p>

    <section className="surface rounded-xl p-5">
      <h2 className="mb-4 text-lg font-semibold">Settings</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">Model
          <input value={model} onChange={(event) => setModel(event.target.value)} disabled={active}
            className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2" placeholder="large-v3" />
        </label>
        <label className="text-sm">Language code <span className="subtle">(blank for automatic)</span>
          <input value={language} onChange={(event) => setLanguage(event.target.value)} disabled={active}
            className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2" placeholder="en, zh…" />
        </label>
        <label className="text-sm">Temperature
          <input type="number" min="0" step="0.1" value={temperature} onChange={(event) => setTemperature(event.target.value)} disabled={active}
            className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2" />
        </label>
        <label className="text-sm">Previous text context
          <select value={context === "0" ? "0" : "64"} onChange={(event) => setContext(event.target.value)} disabled={active}
            className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2">
            <option value="0">Off</option><option value="64">On</option>
          </select>
        </label>
        <label className="text-sm">Compression ratio threshold
          <input type="number" min="0.1" step="0.1" value={threshold} onChange={(event) => setThreshold(event.target.value)} disabled={active}
            className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2" />
        </label>
      </div>
      {!job && <button type="button" onClick={() => void start()} disabled={busy || !model.trim()}
        className="mt-5 rounded-lg bg-[#b7d69d] px-5 py-2 font-semibold text-[#1d2d20] disabled:opacity-50">Start transcription</button>}
    </section>

    {job && <section className="mt-4 rounded-xl border line bg-[#17211d] p-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{job.phase}</h2>
        <span className="subtle text-sm">Elapsed {elapsed(job.started_at, job.finished_at, now)}</span>
      </div>
      {job.error && <p role="alert" className="mt-3 text-sm text-[#ffb3a8]">{job.error}</p>}
      {job.state === "completed" && <p className="mt-3 text-sm">{job.entry_count} subtitle entries saved.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        {active && <button type="button" onClick={() => void act("cancel")} disabled={busy}
          className="rounded-lg border line px-4 py-2 text-sm disabled:opacity-50">Cancel job</button>}
        {(job.state === "failed" || job.state === "cancelled") && <>
          <button type="button" onClick={() => void act("retry")} disabled={busy}
            className="rounded-lg bg-[#b7d69d] px-4 py-2 text-sm font-semibold text-[#1d2d20] disabled:opacity-50">Retry</button>
          <button type="button" onClick={() => { setJob(null); setError(""); }}
            className="rounded-lg border line px-4 py-2 text-sm">Edit settings</button>
        </>}
        {job.state === "completed" && <button type="button" onClick={() => void openReview()} disabled={busy}
          className="rounded-lg bg-[#b7d69d] px-4 py-2 text-sm font-semibold text-[#1d2d20] disabled:opacity-50">Open review</button>}
      </div>
      {job.log_tail.length > 0 && <details open={active || job.state === "failed"} className="mt-5 text-xs"><summary className="cursor-pointer subtle">Recent log output</summary>
        <pre className="panel-scroll mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-[#101816] p-3">{job.log_tail.join("\n")}</pre>
      </details>}
    </section>}
    {error && <p role="alert" className="mt-4 text-sm text-[#ffb3a8]">{error}</p>}
  </main>;
}
