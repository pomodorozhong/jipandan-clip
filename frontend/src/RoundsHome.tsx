import { useId, useRef } from "react";
import type { ClipFeaturesJob, RoundImport, RoundSummary, RoundsOverview } from "./api";
import {
  finishClock, formatPercent, randomShareWarning, ROUND_SIZES, ROUND_RANDOM_SHARE, type ShareWarning,
} from "./reviewRound";
import { formatDuration, formatPerClip, formatShare, stageLabels } from "./stageTimes";
import { Button } from "./ui";

const WARNING_TONES: Record<ShareWarning["tone"], string> = {
  danger: "bg-[#4a2b2a] text-[#ffe2db]",
  caution: "bg-[#4a3a22] text-[#ffe3b8]",
  info: "bg-[#22374a] text-[#d6eeff]",
};

function roundRange(rounds: RoundSummary[]): string {
  return rounds.length === 1 ? "Round 1" : `Rounds 1–${rounds.length}`;
}

function finishedLabel(round: RoundSummary): string {
  if (!round.completed) return "Open";
  const date = new Date(round.completed.t);
  const day = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  return round.completed.unprocessed ? `${day} ${time}, ended with ${round.completed.unprocessed} left` : `${day} ${time}`;
}

function perClip(ms: number): string {
  return `${Math.round(ms / 1000)} s per clip`;
}

function Stat({ label, value, children }: { label: string; value: React.ReactNode; children?: React.ReactNode }) {
  return <div className="min-w-0 py-3 sm:px-5 sm:py-0 sm:first:pl-0 sm:last:pr-0">
    <div className="subtle text-xs">{label}</div>
    <div className="mt-1 text-[22px] font-bold">{value}</div>
    {children}
  </div>;
}

function FileIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" className="shrink-0"><path d="M5 2.5h6.5L15 6v11.5H5z" /><path d="M11.5 2.5V6H15" />
    <path d="M7.5 11.5l1.8 1.8 3.4-3.6" /></svg>;
}

/** The finished round's summary, shown on the rounds home until the next round starts. */
function RoundDone({ round, stream, onSaveFile, onRevealFile }: {
  round: RoundSummary; stream: RoundsOverview["stream"]; onSaveFile: (number: number) => void;
  onRevealFile: (number: number) => void;
}) {
  const captured = formatPercent(round.captured);
  return <section aria-labelledby="round-done-title" className="rounded-2xl border border-[#498c61] bg-[#1a2e24] px-5 py-4">
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 id="round-done-title" className="text-lg font-semibold text-[#e2f8e6]">
        Round {round.number} {round.imported ? "imported" : round.completed?.unprocessed ? "ended" : "is done"}
      </h2>
      <span className="subtle text-[13px]">{round.completed?.unprocessed
        ? `Ended with ${round.completed.unprocessed} of ${round.clips} clips not exported or rejected`
        : `All ${round.clips} clips exported or rejected`}</span>
    </div>
    <div className="mt-3 grid grid-cols-1 divide-y divide-[#2f5440] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
      <Stat label="Keepers captured" value={captured ?? `${round.kept} kept`}>
        <div className="subtle text-xs">{captured && stream
          ? `${round.kept} of ~${stream.keepers.toLocaleString()} in the stream` : "Known once random clips are decided"}</div>
      </Stat>
      <Stat label="Time in round" value={formatDuration(round.time_ms)}>
        <div className="subtle text-xs">{round.decided ? perClip(round.time_ms / round.decided) : ""}</div>
      </Stat>
      <Stat label="Clips kept" value={`${round.kept} / ${round.clips}`}>
        <div className="subtle text-xs">exported, Ready, or Needs work</div>
      </Stat>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-[#c1f3cd]">
      <FileIcon />
      {round.imported
        ? <span>From <span className="mono text-[#edf2ee]">{round.imported.file}</span>, round {round.imported.number} of another project{round.imported.unmatched
          ? `; ${round.imported.unmatched} of its ${round.imported.clips} clips matched no clip here` : ""}.</span>
        : round.file
          ? <><span>Saved <span className="mono text-[#edf2ee]">{round.file}</span> beside the recording; it won't change again.</span>
            <button type="button" className="accent ml-auto hover:underline" onClick={() => onRevealFile(round.number)}>Show in Finder</button></>
          : <><span>This round has no round file yet.</span>
            <button type="button" className="accent ml-auto hover:underline" onClick={() => onSaveFile(round.number)}>Save round file</button></>}
    </div>
    <StageTable round={round} />
  </section>;
}

const CELL = "border-b border-[#2f5440] px-2 py-2 text-right tabular-nums first:pl-0 first:text-left last:pr-0";

// Time per stage in the round, so the slowest stage can be worked on first.
function StageTable({ round }: { round: RoundSummary }) {
  if (!round.stages) return null;
  if (!round.time_ms) return <p className="subtle mt-4 text-[13px]">No clip views recorded in this round.</p>;
  return <div className="mt-4 border-t border-[#2f5440] pt-3">
    <h3 className="subtle mb-1 text-xs font-semibold">Time by stage</h3>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] border-collapse text-[13px]">
        <thead className="subtle text-xs">
          <tr>{["Stage", "Time", "Share", "Clips viewed", "Per clip", "Changes"].map((label) =>
            <th key={label} scope="col" className={`${CELL} font-medium`}>{label}</th>)}</tr>
        </thead>
        <tbody className="[&>tr:last-child>*]:border-b-0">
          {round.stages.map((row) => <tr key={row.stage}>
            <th scope="row" className={`${CELL} font-semibold`}>{stageLabels[row.stage]}</th>
            <td className={CELL}>{formatDuration(row.ms)}</td>
            <td className={CELL}>{formatShare(row, round.time_ms)}</td>
            <td className={CELL}>{row.clips}</td>
            <td className={CELL}>{formatPerClip(row)}</td>
            <td className={CELL}>{row.changes}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <p className="subtle mt-2 text-xs">Time counts while a clip is selected and the app is in front, and stops after 60 s without input. Changes count edits such as status, title, and trim, plus exports in Publish.</p>
  </div>;
}

export default function RoundsHome({
  overview, error, size, share, onSizeChange, onShareChange, onStart, starting, waiting, onCancelWaiting, measuring,
  scoresReady, onReviewAll, now, onSaveFile, onRevealFile, onImport, importing, importResult,
}: {
  overview: RoundsOverview | null;
  error: string;
  size: number;
  share: number;
  onSizeChange: (size: number) => void;
  onShareChange: (share: number) => void;
  onStart: () => void;
  starting: boolean;
  // Start was clicked before scores were final; the round opens when measuring finishes.
  waiting: boolean;
  onCancelWaiting: () => void;
  measuring: ClipFeaturesJob | null;
  scoresReady: boolean;
  onReviewAll: () => void;
  now: Date;
  onSaveFile: (number: number) => void;
  onRevealFile: (number: number) => void;
  onImport: (files: File[]) => void;
  importing: boolean;
  importResult: RoundImport | null;
}) {
  const shareId = useId();
  const importRef = useRef<HTMLInputElement>(null);
  const rounds = overview?.rounds ?? [];
  const last = rounds.at(-1);
  const next = overview?.next;
  const number = next?.number ?? rounds.length + 1;
  const randomCount = next?.random_count ?? Math.round(size * share);
  const warning = randomShareWarning(share, randomCount);
  const empty = overview !== null && overview.pool === 0;
  const prior = formatPercent(overview?.captured ?? null);
  const adds = formatPercent(next?.adds ?? null);
  const labelsAfter = (overview?.labels.so_far ?? 0) + randomCount;
  const progress = measuring && measuring.total ? measuring.progress / measuring.total : null;

  return <main className="panel-scroll flex-1 overflow-auto px-4 py-6 md:px-8 md:py-8">
    <div className="mx-auto flex w-full max-w-[920px] flex-col gap-5">
      {last?.completed && <RoundDone round={last} stream={overview?.stream ?? null}
        onSaveFile={onSaveFile} onRevealFile={onRevealFile} />}

      <section aria-labelledby="next-round-title" className="panel overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5 pb-4 sm:px-6">
          <div className="min-w-0">
            <p className="eyebrow mb-1.5">Next</p>
            <h1 id="next-round-title" className="text-[26px] font-bold">Round {number}</h1>
            <p className="mt-1.5 max-w-xl text-sm text-[#b5c4b9]">
              The best-scored clips not yet reviewed, plus a random share, through Triage, Polish, and Publish.
            </p>
          </div>
          {waiting ? <Button onClick={onCancelWaiting}>Cancel start</Button>
            : <Button variant="primary" className="min-h-11 px-5 text-[15px]" disabled={starting || empty || !overview}
              onClick={onStart}>{starting ? "Starting…" : `Start round ${number}`}</Button>}
        </div>

        {!scoresReady && <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 pb-4 text-[13px] text-[#ead49b] sm:px-6">
          <span>{measuring?.state === "failed" ? `Measuring loudness failed: ${measuring.error ?? "unknown error"}`
            : `Measuring loudness${progress !== null ? ` ${Math.round(progress * 100)}%` : "…"}`}</span>
          {progress !== null && <span className="h-1 min-w-24 flex-1 overflow-hidden rounded-full bg-[#101816]">
            <span className="block h-full bg-[#ead49b]" style={{ width: `${progress * 100}%` }} /></span>}
          <span className="subtle">{waiting ? "The round opens once every clip has its score."
            : "You can start now; the round opens once every clip has its score."}</span>
        </div>}

        <div className="grid gap-5 border-t line bg-[#17211d] px-5 py-4 sm:grid-cols-2 sm:px-6">
          <div>
            <div className="mb-2 text-[13px] font-semibold">Clips</div>
            <div className="seg w-full" role="group" aria-label="Clips in this round">
              {ROUND_SIZES.map((option) => <button key={option} type="button" className="seg-btn" aria-pressed={size === option}
                disabled={starting || waiting} onClick={() => onSizeChange(option)}>{option}</button>)}
            </div>
          </div>
          <div>
            <label htmlFor={shareId} className="mb-2 flex justify-between gap-3 text-[13px] font-semibold">
              <span>Random share</span>
              <span className="accent">{Math.round(share * 100)}% · {randomCount} random {randomCount === 1 ? "clip" : "clips"}</span>
            </label>
            <input id={shareId} type="range" min={0} max={100} step={5} value={Math.round(share * 100)}
              disabled={starting || waiting} onChange={(event) => onShareChange(Number(event.target.value) / 100)}
              className="w-full accent-[#b7d69d]" />
            <div className="subtle mt-0.5 flex justify-between text-[11px]">
              <span>0%</span><span>{Math.round(ROUND_RANDOM_SHARE * 100)}% default</span><span>100%</span>
            </div>
          </div>
        </div>

        {warning && <div role="alert" className={`border-t line px-5 py-2.5 text-[13px] leading-normal sm:px-6 ${WARNING_TONES[warning.tone]}`}>
          <strong>{warning.title}</strong> {warning.text}
        </div>}

        <div className="grid grid-cols-1 divide-y divide-[#34423b] border-t line px-5 py-3 sm:grid-cols-3 sm:divide-x sm:divide-y-0 sm:px-6 sm:py-5">
          <Stat label="Keepers captured" value={adds ? <>{prior ?? "0%"} <span className="text-[#b7d69d]">+{adds}</span></>
            : <span className="text-lg">Known after this round</span>}>
            {adds && <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-[#101816]" aria-hidden="true">
              <div className="bg-[#6f8f74]" style={{ width: `${(overview?.captured ?? 0) * 100}%` }} />
              <div className="bg-[#b7d69d]" style={{ width: `${(next?.adds ?? 0) * 100}%` }} />
            </div>}
            <div className="subtle mt-1.5 text-xs leading-normal">{adds
              ? rounds.length
                ? `${roundRange(rounds)} captured about ${prior ?? "0%"} of the stream's keepers; this round is about to add ${adds} (~${next?.expected_keepers} clips).`
                : `After this round, about ${adds} of the stream's keepers will be captured (~${next?.expected_keepers} clips).`
              : "The round's random clips estimate how many keepers the whole stream has."}</div>
          </Stat>
          <Stat label="Finish around" value={next ? finishClock(now, next.ms) : "—"}>
            <div className="subtle mt-1.5 text-xs leading-normal">{next ? `${formatDuration(next.ms)} if you start now · ${
              overview?.pace.source === "rounds" ? `${perClip(overview.pace.ms)} in ${overview.pace.rounds.length === 1
                ? `round ${overview.pace.rounds[0]}` : `rounds ${overview.pace.rounds[0]}–${overview.pace.rounds.at(-1)}`}`
                : "default pace until a round is timed"}` : ""}</div>
          </Stat>
          <Stat label="Training data" value={`${labelsAfter} / ${overview?.labels.target ?? 250}`}>
            <div className="subtle mt-1.5 text-xs leading-normal">
              random labels after this round ({overview?.labels.so_far ?? 0} so far){overview?.labels.margin_after
                ? `; stream keep rate known to ±${Math.round(overview.labels.margin_after)} points` : ""}
            </div>
          </Stat>
        </div>
        <div className="subtle border-t line px-5 py-2.5 text-xs sm:px-6">{overview
          ? empty ? "Every clip is already in a round or decided."
            : `${overview.pool.toLocaleString()} of ${overview.total.toLocaleString()} clips not yet in a round · about ${
              Math.ceil(Math.max(0, overview.pool - next!.size) / Math.max(1, next!.size))} more rounds of this size after this one`
          : "Loading…"}</div>
      </section>
      {error && <p role="alert" className="text-sm text-[#ffb3a8]">{error}</p>}

      <section aria-labelledby="earlier-rounds-title">
        <div className="mb-2.5 flex items-center justify-between gap-3">
          <h2 id="earlier-rounds-title" className="eyebrow">Earlier rounds</h2>
          <button type="button" className="accent text-[13px] hover:underline disabled:opacity-50" disabled={importing}
            onClick={() => importRef.current?.click()}>{importing ? "Importing…" : "Import round files…"}</button>
          <input ref={importRef} type="file" accept=".json,application/json" multiple className="sr-only" tabIndex={-1}
            aria-label="Round files to import" onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length) onImport(files);
            }} />
        </div>
        {importResult && <div role="status" className="mb-2.5 rounded-lg border line bg-[#17211d] px-4 py-2.5 text-[13px]">
          {importResult.imported.map((item) => <p key={item.file}>Imported <span className="mono">{item.file}</span> as round {item.number}: {item.matched} clips matched{item.unmatched ? `, ${item.unmatched} not found here` : ""}.</p>)}
          {importResult.skipped.map((item) => <p key={item.file} className="text-[#ffcfc4]">Skipped <span className="mono">{item.file}</span>: {item.reason}.</p>)}
        </div>}
        {rounds.length ? <div className="overflow-x-auto rounded-xl border line bg-[#192420]">
          <table className="w-full min-w-[620px] border-collapse text-sm">
            <thead><tr className="subtle text-left text-xs">
              <th scope="col" className="px-4 py-2.5 font-semibold">Round</th>
              <th scope="col" className="px-4 py-2.5 font-semibold">Finished</th>
              <th scope="col" className="px-4 py-2.5 text-right font-semibold">Clips</th>
              <th scope="col" className="px-4 py-2.5 text-right font-semibold">Kept</th>
              <th scope="col" className="px-4 py-2.5 text-right font-semibold">Keepers captured</th>
              <th scope="col" className="px-4 py-2.5 text-right font-semibold">Time</th>
              <th scope="col" className="px-4 py-2.5 text-right font-semibold">File</th>
            </tr></thead>
            <tbody className="mono">
              {[...rounds].reverse().map((round) => <tr key={round.number} className="border-t line">
                <td className="px-4 py-3 font-semibold">{round.number}</td>
                <td className="px-4 py-3 text-[#b5c4b9]">{finishedLabel(round)}</td>
                <td className="px-4 py-3 text-right">{round.clips}</td>
                <td className="px-4 py-3 text-right">{round.kept}</td>
                <td className="px-4 py-3 text-right">{round.captured === null ? "—" : `+${formatPercent(round.captured)}`}</td>
                <td className="px-4 py-3 text-right">{formatDuration(round.time_ms)}</td>
                <td className="px-4 py-3 text-right font-sans">{round.imported
                  ? <span className="subtle" title={round.imported.file}>Imported</span>
                  : !round.completed ? "—"
                    : round.file ? <button type="button" className="accent hover:underline" title={round.file}
                      onClick={() => onRevealFile(round.number)}>Show</button>
                      : <button type="button" className="accent hover:underline" onClick={() => onSaveFile(round.number)}>Save</button>}</td>
              </tr>)}
            </tbody>
          </table>
        </div> : <div className="subtle rounded-xl border border-dashed line px-4 py-5 text-center text-sm">
          No rounds yet. Picking up from an older project folder? Import its round files to skip the clips they cover.</div>}
      </section>

      <p className="subtle text-[13px]">Need something outside a round?{" "}
        <button type="button" className="accent underline-offset-2 hover:underline" onClick={onReviewAll}>Review all clips</button>.
        {" "}Those decisions won't count toward rounds.</p>
    </div>
  </main>;
}
