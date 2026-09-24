import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Clip, type WaveformWindow } from "./api";

type Edge = "start" | "end";
type TimeRange = { start: number; end: number };

const MIN_CLIP_MS = 10;
const MAX_WINDOW_MS = 120_000;
const PLOT_WIDTH = 1000;
const PLOT_HEIGHT = 160;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function boundedRange(start: number, span: number, duration: number): TimeRange {
  const width = Math.min(duration, Math.max(1, Math.round(span)));
  const boundedStart = clamp(Math.round(start), 0, duration - width);
  return { start: boundedStart, end: boundedStart + width };
}

function initialRange(clip: Clip, duration: number): TimeRange {
  const span = clamp(clip.end_ms - clip.start_ms + 2000, 2000, MAX_WINDOW_MS);
  return boundedRange(clip.start_ms - 1000, span, duration);
}

function fineRange(time: number, duration: number): TimeRange {
  return boundedRange(time - 1000, 2000, duration);
}

function formatClock(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const hours = Math.floor(total / 3_600_000);
  const minutes = Math.floor((total % 3_600_000) / 60_000);
  const seconds = Math.floor((total % 60_000) / 1000);
  const milliseconds = total % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}

function signed(ms: number): string {
  return `${ms > 0 ? "+" : ""}${ms} ms`;
}

function useWaveform(clipId: string, range: TimeRange, buckets: number) {
  const [window, setWindow] = useState<WaveformWindow | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setWindow(null);
    setError("");
    const query = new URLSearchParams({
      start_ms: String(range.start), end_ms: String(range.end), buckets: String(buckets),
    });
    void api<WaveformWindow>(`/waveforms/${encodeURIComponent(clipId)}?${query}`, "GET", undefined, controller.signal)
      .then(setWindow)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => controller.abort();
  }, [clipId, range.start, range.end, buckets, retry]);

  return { window, error, retry: () => setRetry((value) => value + 1) };
}

function WaveformPlot({ label, range, waveform, startMs, endMs, playheadMs, editableEdge,
  disabled, onPreview, onCommit, onCancel, onSeek }: {
  label: string;
  range: TimeRange;
  waveform: WaveformWindow | null;
  startMs: number;
  endMs: number;
  playheadMs: number;
  editableEdge?: Edge;
  disabled: boolean;
  onPreview: (edge: Edge, time: number) => void;
  onCommit: (edge: Edge, time: number) => void;
  onCancel: () => void;
  onSeek: (time: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<Edge | null>(null);
  const points = useMemo(() => {
    if (!waveform?.mins.length) return "";
    const count = Math.min(waveform.mins.length, waveform.maxs.length);
    const peak = Math.max(0.05, ...waveform.mins.map(Math.abs), ...waveform.maxs.map(Math.abs));
    const lines: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const x = ((index + 0.5) * PLOT_WIDTH / count).toFixed(1);
      const top = clamp(PLOT_HEIGHT / 2 - waveform.maxs[index] / peak * 64, 8, PLOT_HEIGHT - 8);
      const bottom = clamp(PLOT_HEIGHT / 2 - waveform.mins[index] / peak * 64, 8, PLOT_HEIGHT - 8);
      lines.push(`M${x} ${top.toFixed(1)}V${bottom.toFixed(1)}`);
    }
    return lines.join("");
  }, [waveform]);

  const span = range.end - range.start;
  const markerX = (time: number) => (time - range.start) / span * PLOT_WIDTH;
  const inRange = (time: number) => time >= range.start && time <= range.end;
  const startX = markerX(startMs);
  const endX = markerX(endMs);

  function position(clientX: number): { time: number; x: number } {
    const rectangle = svgRef.current!.getBoundingClientRect();
    const x = clamp(clientX - rectangle.left, 0, rectangle.width);
    return { time: Math.round(range.start + x / rectangle.width * span), x };
  }

  function pointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (disabled) return;
    const point = position(event.clientX);
    const startDistance = inRange(startMs) ? Math.abs(point.x - startX / PLOT_WIDTH * event.currentTarget.clientWidth) : Infinity;
    const endDistance = inRange(endMs) ? Math.abs(point.x - endX / PLOT_WIDTH * event.currentTarget.clientWidth) : Infinity;
    const nearest: Edge = editableEdge ?? (startDistance <= endDistance ? "start" : "end");
    const distance = nearest === "start" ? startDistance : endDistance;
    if (distance <= 18) {
      event.preventDefault();
      dragging.current = nearest;
      event.currentTarget.setPointerCapture(event.pointerId);
      onPreview(nearest, point.time);
    } else {
      onSeek(point.time);
    }
  }

  function pointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (dragging.current) onPreview(dragging.current, position(event.clientX).time);
  }

  function pointerUp(event: React.PointerEvent<SVGSVGElement>) {
    const edge = dragging.current;
    if (!edge) return;
    dragging.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    onCommit(edge, position(event.clientX).time);
  }

  function pointerCancel() {
    if (!dragging.current) return;
    dragging.current = null;
    onCancel();
  }

  return <div>
    <svg ref={svgRef} role="img" aria-label={label} viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`}
      preserveAspectRatio="none" onPointerDown={pointerDown} onPointerMove={pointerMove}
      onPointerUp={pointerUp} onPointerCancel={pointerCancel}
      className="block h-36 w-full cursor-crosshair rounded-lg border border-[#46584c] bg-[#101a17] touch-none">
      {[250, 500, 750].map((x) => <line key={x} x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke="#526259" strokeWidth="1" opacity="0.35" />)}
      <line x1="0" y1={PLOT_HEIGHT / 2} x2={PLOT_WIDTH} y2={PLOT_HEIGHT / 2} stroke="#46584c" strokeWidth="1" />
      {inRange(startMs) && inRange(endMs) && <rect x={startX} y="0" width={Math.max(0, endX - startX)} height={PLOT_HEIGHT} fill="#b7d69d" opacity="0.08" />}
      {points && <path d={points} stroke="#a8c9b0" strokeWidth="1.5" fill="none" />}
      {(["start", "end"] as Edge[]).map((edge) => {
        const time = edge === "start" ? startMs : endMs;
        if (!inRange(time)) return null;
        const x = markerX(time);
        const color = edge === "start" ? "#f2cf86" : "#e7a6ca";
        return <g key={edge}>
          <line x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke={color} strokeWidth="3" />
          <rect x={clamp(x - 9, 0, PLOT_WIDTH - 18)} y="4" width="18" height="22" rx="4" fill={color} />
        </g>;
      })}
      {inRange(playheadMs) && <line x1={markerX(playheadMs)} y1="0" x2={markerX(playheadMs)} y2={PLOT_HEIGHT} stroke="#f2f4ef" strokeWidth="2" opacity="0.9" />}
    </svg>
    <div className="subtle mono mt-1 flex justify-between text-[11px]">
      <span>{formatClock(range.start)}</span>
      <span>{formatClock(Math.round((range.start + range.end) / 2))}</span>
      <span>{formatClock(range.end)}</span>
    </div>
  </div>;
}

export default function WaveformEditor({ clip, durationMs, audioSrc, busy, shortcutsPaused, onSave }: {
  clip: Clip;
  durationMs: number;
  audioSrc: string;
  busy: boolean;
  shortcutsPaused: boolean;
  onSave: (startMs: number, endMs: number) => Promise<boolean>;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const savingRef = useRef(false);
  const auditionStop = useRef<number | null>(null);
  const cancelOffsetBlur = useRef(false);
  const [startMs, setStartMs] = useState(clip.start_ms);
  const [endMs, setEndMs] = useState(clip.end_ms);
  const [startOffset, setStartOffset] = useState(String(clip.start_ms - clip.original_start_ms));
  const [endOffset, setEndOffset] = useState(String(clip.end_ms - clip.original_end_ms));
  const [overviewRange, setOverviewRange] = useState(() => initialRange(clip, durationMs));
  const [startDetailRange, setStartDetailRange] = useState(() => fineRange(clip.start_ms, durationMs));
  const [endDetailRange, setEndDetailRange] = useState(() => fineRange(clip.end_ms, durationMs));
  const [playheadMs, setPlayheadMs] = useState(clip.start_ms);
  const [playing, setPlaying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const overview = useWaveform(clip.clip_id, overviewRange, 1000);
  const startDetail = useWaveform(clip.clip_id, startDetailRange, 800);
  const endDetail = useWaveform(clip.clip_id, endDetailRange, 800);

  useEffect(() => {
    setStartMs(clip.start_ms);
    setEndMs(clip.end_ms);
    setStartOffset(String(clip.start_ms - clip.original_start_ms));
    setEndOffset(String(clip.end_ms - clip.original_end_ms));
  }, [clip.start_ms, clip.end_ms, clip.original_start_ms, clip.original_end_ms]);

  useEffect(() => {
    setStartDetailRange((current) => {
      const margin = (current.end - current.start) * 0.15;
      if (clip.start_ms >= current.start + margin && clip.start_ms <= current.end - margin) return current;
      const centered = fineRange(clip.start_ms, durationMs);
      return centered.start === current.start && centered.end === current.end ? current : centered;
    });
  }, [clip.start_ms, durationMs]);

  useEffect(() => {
    setEndDetailRange((current) => {
      const margin = (current.end - current.start) * 0.15;
      if (clip.end_ms >= current.start + margin && clip.end_ms <= current.end - margin) return current;
      const centered = fineRange(clip.end_ms, durationMs);
      return centered.start === current.start && centered.end === current.end ? current : centered;
    });
  }, [clip.end_ms, durationMs]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    let frame = 0;
    const tick = () => {
      const current = Math.round(audio.currentTime * 1000);
      setPlayheadMs(current);
      if (current >= (auditionStop.current ?? endMs)) {
        audio.pause();
        auditionStop.current = null;
      } else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, endMs]);

  function boundsFor(edgeToMove: Edge, time: number): [number, number] {
    const position = Math.round(time);
    return edgeToMove === "start"
      ? [clamp(position, 0, endMs - MIN_CLIP_MS), endMs]
      : [startMs, clamp(position, startMs + MIN_CLIP_MS, durationMs)];
  }

  function previewEdge(edgeToMove: Edge, time: number) {
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    setStartMs(nextStart);
    setEndMs(nextEnd);
    setStartOffset(String(nextStart - clip.original_start_ms));
    setEndOffset(String(nextEnd - clip.original_end_ms));
  }

  async function commitBounds(nextStart: number, nextEnd: number) {
    if (savingRef.current || busy) return;
    if (!Number.isInteger(nextStart) || !Number.isInteger(nextEnd) ||
        nextStart < 0 || nextEnd > durationMs || nextEnd - nextStart < MIN_CLIP_MS) {
      setLocalError("Keep at least 10 ms between the boundaries, within the recording.");
      setStartMs(clip.start_ms);
      setEndMs(clip.end_ms);
      setStartOffset(String(clip.start_ms - clip.original_start_ms));
      setEndOffset(String(clip.end_ms - clip.original_end_ms));
      return;
    }
    setLocalError("");
    setStartMs(nextStart);
    setEndMs(nextEnd);
    setStartOffset(String(nextStart - clip.original_start_ms));
    setEndOffset(String(nextEnd - clip.original_end_ms));
    if (nextStart === clip.start_ms && nextEnd === clip.end_ms) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const accepted = await onSave(nextStart, nextEnd);
      if (!accepted) {
        setStartMs(clip.start_ms);
        setEndMs(clip.end_ms);
        setStartOffset(String(clip.start_ms - clip.original_start_ms));
        setEndOffset(String(clip.end_ms - clip.original_end_ms));
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  function commitEdge(edgeToMove: Edge, time: number) {
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    void commitBounds(nextStart, nextEnd);
  }

  function cancelPreview() {
    setStartMs(clip.start_ms);
    setEndMs(clip.end_ms);
    setStartOffset(String(clip.start_ms - clip.original_start_ms));
    setEndOffset(String(clip.end_ms - clip.original_end_ms));
  }

  function nudge(which: Edge, amount: number) {
    commitEdge(which, (which === "start" ? startMs : endMs) + amount);
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (shortcutsPaused || busy || savingRef.current || event.isComposing) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.code === "Space" && !event.altKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        if (!event.repeat) void play();
        return;
      }
      const which: Edge = event.code === "BracketLeft" || event.code === "BracketRight" ? "end" : "start";
      const direction = event.code === "Comma" || event.code === "BracketLeft" ? -1
        : event.code === "Period" || event.code === "BracketRight" ? 1 : 0;
      if (direction) {
        event.preventDefault();
        nudge(which, direction * (event.shiftKey ? 100 : 10));
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function seek(time: number) {
    const position = clamp(time, 0, durationMs);
    if (audioRef.current) audioRef.current.currentTime = position / 1000;
    setPlayheadMs(position);
  }

  async function play() {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.paused) { audio.pause(); return; }
    auditionStop.current = null;
    if (audio.currentTime * 1000 < startMs || audio.currentTime * 1000 >= endMs) seek(startMs);
    try { await audio.play(); setLocalError(""); }
    catch { setLocalError("Audio playback was blocked. Press Play again after interacting with the page."); }
  }

  async function replay() {
    seek(startMs);
    auditionStop.current = null;
    try { await audioRef.current?.play(); setLocalError(""); }
    catch { setLocalError("Audio playback was blocked. Press Play again after interacting with the page."); }
  }

  async function audition(which: Edge) {
    const boundary = which === "start" ? startMs : endMs;
    seek(clamp(boundary - 500, 0, durationMs));
    auditionStop.current = clamp(boundary + 500, 0, durationMs);
    try { await audioRef.current?.play(); setLocalError(""); }
    catch { setLocalError("Audio playback was blocked. Press Play again after interacting with the page."); }
  }

  function applyOffset(which: Edge, value: string) {
    if (!/^[+-]?\d+$/.test(value.trim())) {
      setLocalError("Enter a whole number of milliseconds, such as -120 or 50.");
      which === "start"
        ? setStartOffset(String(startMs - clip.original_start_ms))
        : setEndOffset(String(endMs - clip.original_end_ms));
      return;
    }
    const offset = Number(value);
    if (!Number.isSafeInteger(offset)) {
      setLocalError("Offset is too large; enter a smaller number of milliseconds.");
      which === "start"
        ? setStartOffset(String(startMs - clip.original_start_ms))
        : setEndOffset(String(endMs - clip.original_end_ms));
      return;
    }
    const absolute = (which === "start" ? clip.original_start_ms : clip.original_end_ms) + offset;
    void commitBounds(which === "start" ? absolute : startMs, which === "end" ? absolute : endMs);
  }

  function offsetBlur(which: Edge, value: string) {
    if (cancelOffsetBlur.current) {
      cancelOffsetBlur.current = false;
      return;
    }
    applyOffset(which, value);
  }

  function cancelOffset(which: Edge, input: HTMLInputElement) {
    cancelOffsetBlur.current = true;
    which === "start"
      ? setStartOffset(String(startMs - clip.original_start_ms))
      : setEndOffset(String(endMs - clip.original_end_ms));
    input.blur();
  }

  function zoom(factor: number) {
    const span = overviewRange.end - overviewRange.start;
    const nextSpan = clamp(Math.round(span * factor), 500, Math.min(MAX_WINDOW_MS, durationMs));
    const center = clamp(playheadMs, overviewRange.start, overviewRange.end);
    setOverviewRange(boundedRange(center - nextSpan / 2, nextSpan, durationMs));
  }

  function pan(direction: number) {
    const span = overviewRange.end - overviewRange.start;
    setOverviewRange(boundedRange(overviewRange.start + direction * span / 2, span, durationMs));
  }

  const controlsDisabled = busy || saving;
  return <div className="mb-6">
    <audio ref={audioRef} src={audioSrc} preload="metadata" playsInline
      onLoadedMetadata={() => seek(clip.start_ms)} onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => void play()} className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
          aria-label={playing ? "Pause audio" : "Play clip"} title="Play or pause (Space)">
          <span>{playing ? "Pause" : "Play clip"}</span><kbd aria-hidden="true" className="shortcut-key">Space</kbd>
        </button>
        <button type="button" onClick={() => void replay()} className="soft-surface rounded-lg px-3 py-2 text-sm">Replay from start</button>
        <button type="button" onClick={() => void audition("start")} className="soft-surface rounded-lg px-3 py-2 text-sm">Hear start</button>
        <button type="button" onClick={() => void audition("end")} className="soft-surface rounded-lg px-3 py-2 text-sm">Hear end</button>
      </div>
      <span className="subtle mono text-xs">Playhead {formatClock(playheadMs)}</span>
    </div>

    <div className="mb-3 rounded-xl border border-[#405748] bg-[#1b2b23] p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">Overview</h4>
        <div className="flex gap-1 text-xs">
          <button type="button" onClick={() => pan(-1)} className="soft-surface rounded px-2 py-1" aria-label="Move waveform earlier">←</button>
          <button type="button" onClick={() => zoom(2)} className="soft-surface rounded px-2 py-1">Zoom out</button>
          <button type="button" onClick={() => zoom(0.5)} className="soft-surface rounded px-2 py-1">Zoom in</button>
          <button type="button" onClick={() => pan(1)} className="soft-surface rounded px-2 py-1" aria-label="Move waveform later">→</button>
        </div>
      </div>
      {overview.error ? <p role="alert" className="text-sm text-[#ffb3a8]">{overview.error} <button type="button" onClick={overview.retry} className="underline">Retry</button></p>
        : !overview.window ? <p className="subtle py-8 text-center text-sm">Loading waveform…</p>
          : <WaveformPlot label="Overview waveform; drag the start or end handle, or click to seek"
            range={overviewRange} waveform={overview.window} startMs={startMs} endMs={endMs}
            playheadMs={playheadMs} disabled={controlsDisabled} onPreview={previewEdge}
            onCommit={commitEdge} onCancel={cancelPreview} onSeek={seek} />}
      <p className="subtle mt-1 text-xs">Drag the amber start or pink end handle. Click elsewhere in the waveform to seek.</p>
    </div>

    <div className="rounded-xl border border-[#405748] bg-[#1b2b23] p-3">
      <h4 className="mb-2 text-sm font-medium">Fine boundary views</h4>
      {(["start", "end"] as Edge[]).map((which) => {
        const detail = which === "start" ? startDetail : endDetail;
        const range = which === "start" ? startDetailRange : endDetailRange;
        const offset = which === "start" ? startOffset : endOffset;
        const setOffset = which === "start" ? setStartOffset : setEndOffset;
        const keyPair = which === "start" ? [",", "."] : ["[", "]"];
        return <div key={which} className={which === "end" ? "mt-5 border-t line pt-5" : ""}>
          <h5 className="mb-2 text-sm font-medium">{which === "start" ? "Start" : "End"} boundary</h5>
          {detail.error ? <p role="alert" className="text-sm text-[#ffb3a8]">{detail.error} <button type="button" onClick={detail.retry} className="underline">Retry</button></p>
            : !detail.window ? <p className="subtle py-8 text-center text-sm">Loading fine waveform…</p>
              : <WaveformPlot label={`Fine ${which} boundary waveform; drag the handle, or click to seek`}
                range={range} waveform={detail.window} startMs={startMs} endMs={endMs}
                playheadMs={playheadMs} editableEdge={which} disabled={controlsDisabled}
                onPreview={previewEdge} onCommit={commitEdge} onCancel={cancelPreview} onSeek={seek} />}
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={`Nudge ${which} boundary`}>
            {[-100, -10, 10, 100].map((amount) => {
              const key = `${Math.abs(amount) === 100 ? "⇧" : ""}${amount < 0 ? keyPair[0] : keyPair[1]}`;
              return <button key={amount} type="button" onClick={() => nudge(which, amount)}
                disabled={controlsDisabled} title={`Nudge ${which} boundary ${amount > 0 ? "+" : ""}${amount} ms (${key})`}
                className="mono inline-flex items-center justify-center gap-2 rounded-lg bg-[#304538] px-3 py-2 text-sm hover:bg-[#3b5543] disabled:opacity-50">
                <span>{amount > 0 ? "+" : ""}{amount} ms</span><kbd aria-hidden="true" className="shortcut-key">{key}</kbd>
              </button>;
            })}
          </div>
          <label className="mt-3 block max-w-xs text-sm"><span className="subtle block text-xs">{which === "start" ? "Start" : "End"} offset from SRT (ms)</span>
            <input type="text" inputMode="numeric" value={offset}
              onChange={(event) => setOffset(event.target.value)}
              onBlur={(event) => offsetBlur(which, event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
                if (event.key === "Escape") { event.preventDefault(); cancelOffset(which, event.currentTarget); }
              }} disabled={controlsDisabled} className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2 mono" />
          </label>
        </div>;
      })}
      <div className="mt-4 grid gap-2 border-t line pt-3 text-xs sm:grid-cols-2">
        <span><span className="subtle">Current start</span> <strong className="mono ml-1">{formatClock(startMs)}</strong> <span className="subtle mono">({signed(startMs - clip.original_start_ms)})</span></span>
        <span><span className="subtle">Current end</span> <strong className="mono ml-1">{formatClock(endMs)}</strong> <span className="subtle mono">({signed(endMs - clip.original_end_ms)})</span></span>
        <span><span className="subtle">SRT start</span> <span className="mono ml-1">{formatClock(clip.original_start_ms)}</span></span>
        <span><span className="subtle">SRT end</span> <span className="mono ml-1">{formatClock(clip.original_end_ms)}</span></span>
        <span><span className="subtle">Current duration</span> <strong className="mono ml-1">{((endMs - startMs) / 1000).toFixed(3)} s</strong></span>
        {saving && <span className="text-[#ead49b]">Saving trim…</span>}
      </div>
      {localError && <p role="alert" className="mt-3 text-sm text-[#ffb3a8]">{localError}</p>}
    </div>
  </div>;
}
