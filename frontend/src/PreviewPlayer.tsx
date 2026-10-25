import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { TrimMap, WaveformWindow } from "./api";
import { removedRanges, renderedTimeToSource, sourceTimeToRendered } from "./trimMap";
import { boundedRange, initialRange, useWaveform, WaveformPlot } from "./WaveformEditor";
import type { InputAction } from "./inputActions";
import { ShortcutBadge } from "./ShortcutBadge";

export interface PreviewPlayerHandle {
  toggle(): void;
  replay(): void;
  pause(): void;
  seek(ms: number): void;
}

type Props = {
  variant: "reference" | "candidate";
  eyebrow: string;
  title: string;
  durationLabel: string;
  durationText: string;
  note: string;
  startMs: number;
  endMs: number;
  waveform: WaveformWindow | null;
  sharedPeak: number;
  trimMap?: TrimMap | null;
  src?: string;
  placeholder: string;
  playShortcut: string;
  replayShortcut: string;
  playShortcutId: string;
  replayShortcutId: string;
  onTrim?: (start: number, end: number, edge?: "start" | "end") => void;
  editingDisabled?: boolean;
  /** Show the candidate on the original timeline; clicks outside the clip play that nearby audio. */
  sourceContext?: { clipId: string; audioSrc: string; durationMs: number; startMs: number; endMs: number };
  /** A problem shown prominently above the waveform, such as a failed render. */
  alert?: React.ReactNode;
  onActivate(): void;
  onAction(action: InputAction): void;
  /** Called each time playback starts, including nearby audio outside the clip, to count it in the clip's view. */
  onPlayback?: () => void;
};

const NEARBY_AUDIO_MS = 5000;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function clock(ms: number): string {
  const value = Math.max(0, Math.round(ms));
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.floor(value % 60_000 / 1000);
  const hundredths = Math.floor(value % 1000 / 10);
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(hundredths).padStart(2, "0")}`;
}

const PreviewPlayer = forwardRef<PreviewPlayerHandle, Props>(function PreviewPlayer({
  variant, eyebrow, title, durationLabel, durationText, note, startMs, endMs,
  waveform, sharedPeak, trimMap, src, placeholder, playShortcut, replayShortcut, playShortcutId, replayShortcutId, onActivate, onAction, onTrim, editingDisabled = false, sourceContext, alert, onPlayback,
}, ref) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const contextAudioRef = useRef<HTMLAudioElement>(null);
  const contextStop = useRef(0);
  const [contextPlaying, setContextPlaying] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const auditionEnd = useRef(endMs);
  const [positionMs, setPositionMs] = useState(startMs);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const ready = Boolean(src && endMs > startMs);
  const durationMs = Math.max(1, endMs - startMs);
  const reference = variant === "reference";
  const timelineOrigin = sourceContext?.startMs ?? startMs;
  const selectedDuration = sourceContext ? sourceContext.endMs - sourceContext.startMs : durationMs;
  // The original-timeline view only reaches nearby audio, so a swipe cannot
  // fling it far from the clip.
  const timelineMin = sourceContext ? Math.max(0, sourceContext.startMs - NEARBY_AUDIO_MS) - timelineOrigin : 0;
  const timelineMax = sourceContext
    ? Math.min(sourceContext.durationMs, sourceContext.endMs + NEARBY_AUDIO_MS) - timelineOrigin : durationMs;
  const timelineDuration = timelineMax - timelineMin;
  // The viewport is kept in recording time so a trim, which moves the
  // timeline origin, does not shift the view for a frame.
  function boundView(start: number, span: number) {
    const bounded = boundedRange(start - timelineMin - timelineOrigin, span, timelineDuration);
    return { start: bounded.start + timelineMin + timelineOrigin, end: bounded.end + timelineMin + timelineOrigin };
  }
  function initialViewport() {
    if (!sourceContext) return { start: timelineOrigin, end: timelineOrigin + durationMs };
    return initialRange({ start_ms: sourceContext.startMs, end_ms: sourceContext.endMs }, sourceContext.durationMs);
  }

  const [viewport, setViewport] = useState(initialViewport);
  const range = { start: viewport.start - timelineOrigin, end: viewport.end - timelineOrigin };
  const [selection, setSelection] = useState({ start: 0, end: selectedDuration });
  const [contextCursor, setContextCursor] = useState<number | null>(null);
  useEffect(() => {
    if (sourceContext) setViewport((current) => {
      const next = boundView(current.start, current.end - current.start);
      return next.start === current.start && next.end === current.end ? current : next;
    });
    else setViewport(initialViewport());
    setSelection({ start: 0, end: selectedDuration });
    setContextCursor(null);
  }, [src, durationMs, timelineOrigin, selectedDuration, sourceContext?.durationMs]);
  const sourceWaveform = useWaveform(sourceContext?.clipId ?? "", viewport, 1000, Boolean(sourceContext));
  const displayWaveform = sourceContext ? sourceWaveform.window && {
    ...sourceWaveform.window,
    start_ms: sourceWaveform.window.start_ms - timelineOrigin,
    end_ms: sourceWaveform.window.end_ms - timelineOrigin,
  } : waveform;
  function viewportChange(start: number, span: number) {
    const next = boundView(start + timelineOrigin, span);
    setViewport(next);
    return { start: next.start - timelineOrigin, end: next.end - timelineOrigin };
  }
  function previewRange(start: number, end: number) {
    if (onTrim && !editingDisabled) setSelection({ start: clamp(Math.min(start, end), timelineMin, timelineMax), end: clamp(Math.max(start, end), timelineMin, timelineMax) });
  }
  function previewEdge(edge: "start" | "end", time: number) {
    if (!onTrim || editingDisabled) return;
    setSelection((current) => ({ ...current, [edge]: clamp(time,
      edge === "start" ? timelineMin : current.start + 10, edge === "start" ? current.end - 10 : timelineMax) }));
  }
  function commit(start: number, end: number, edge?: "start" | "end") {
    if (!onTrim || editingDisabled) return;
    const lower = Math.max(timelineMin, Math.min(start, end));
    const upper = Math.min(timelineMax, Math.max(start, end));
    if (upper - lower >= 10) onTrim(lower, upper, edge);
    else setSelection({ start: 0, end: selectedDuration });
  }

  useEffect(() => {
    const audio = audioRef.current;
    audio?.pause();
    setPlaying(false);
    setPositionMs(startMs);
    auditionEnd.current = endMs;
    setError("");
    if (audio && ready && audio.readyState >= HTMLMediaElement.HAVE_METADATA) {
      audio.currentTime = startMs / 1000;
    }
  }, [src, startMs, endMs, ready]);

  useEffect(() => {
    const audio = audioRef.current;
    return () => { audio?.pause(); };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    let frame = 0;
    const tick = () => {
      const current = Math.round(audio.currentTime * 1000);
      const limit = auditionEnd.current;
      if (current >= limit) {
        setPositionMs(limit);
        audio.pause();
        return;
      }
      setPositionMs(clamp(current, startMs, endMs));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, startMs, endMs]);

  useEffect(() => {
    const audio = contextAudioRef.current;
    if (!audio || !contextPlaying) return;
    let frame = 0;
    const tick = () => {
      const current = Math.round(audio.currentTime * 1000) - timelineOrigin;
      if (current >= contextStop.current) {
        setContextCursor(contextStop.current);
        audio.pause();
        return;
      }
      setContextCursor(current);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [contextPlaying, timelineOrigin]);

  const seek = useCallback((ms: number) => {
    const position = clamp(Math.round(ms), startMs, endMs);
    auditionEnd.current = endMs;
    const audio = audioRef.current;
    if (audio && ready) audio.currentTime = position / 1000;
    setPositionMs(position);
  }, [startMs, endMs, ready]);

  function seekTimeline(time: number) {
    if (!sourceContext) { seek(timelineOrigin + time); return; }
    if (time < 0 || time > selectedDuration) {
      void playContext(time);
      return;
    }
    contextAudioRef.current?.pause();
    setContextCursor(null);
    seek(trimMap ? sourceTimeToRendered(trimMap, time, durationMs) : time / selectedDuration * durationMs);
  }
  const timelinePlayhead = contextCursor ?? (sourceContext && !reference
    ? trimMap ? renderedTimeToSource(trimMap, positionMs, "start", durationMs) : positionMs / durationMs * selectedDuration
    : positionMs - startMs);

  /** Play original audio from outside the clip: up to the clip start, or on to the end of the nearby range. */
  async function playContext(time: number) {
    audioRef.current?.pause();
    setContextCursor(time);
    const audio = contextAudioRef.current;
    if (!audio) return;
    contextStop.current = time < 0 ? 0 : timelineMax;
    audio.currentTime = (timelineOrigin + time) / 1000;
    onActivate();
    try {
      await audio.play();
      setError("");
      onPlayback?.();
    } catch {
      setError("Playback was blocked. Press Play again after interacting with the page.");
    }
  }

  async function play(restart: boolean) {
    const audio = audioRef.current;
    if (!audio || !ready) return;
    if (!restart && !audio.paused) { audio.pause(); return; }
    contextAudioRef.current?.pause();
    setContextCursor(null);
    if (restart || audio.currentTime * 1000 < startMs || audio.currentTime * 1000 >= auditionEnd.current) seek(startMs);
    onActivate();
    try {
      await audio.play();
      setError("");
      onPlayback?.();
    } catch {
      setError("Playback was blocked. Press Play again after interacting with the page.");
    }
  }

  useImperativeHandle(ref, () => ({
    toggle: () => { void play(false); },
    replay: () => { void play(true); },
    pause: () => { audioRef.current?.pause(); contextAudioRef.current?.pause(); },
    seek,
  }));

  return <div ref={cardRef} className={`relative grid min-w-0 gap-x-4 rounded-xl border p-3 sm:grid-cols-[240px_minmax(0,1fr)] ${reference
    ? "border-[#618a9c] bg-[#1c2b32]" : "border-[#8eb36c] bg-[#203225]"}`}>
    {alert && <div role="alert" className="mb-3 ml-1 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border sm:col-span-2 border-[#e58a7a] bg-[#3b211d] px-3 py-2 text-sm font-medium text-[#ffd6cc]">
      <span aria-hidden="true" className="text-base leading-none">⚠</span>{alert}
    </div>}
    <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 rounded-l-xl ${reference ? "bg-[#7eb4c7]" : "bg-[#b7d69d]"}`} />
    <div className="min-w-0 pl-1">
      <p className={`text-[10px] font-bold uppercase tracking-[.13em] ${reference ? "text-[#b9dce7]" : "text-[#cee8ad]"}`}>{eyebrow}</p>
      <h4 className={`mt-0.5 text-sm font-semibold ${reference ? "text-[#d5edf4]" : "text-[#def0c7]"}`}>{title}</h4>
      <div className="mt-2 flex gap-1.5">
        <button type="button" disabled={!ready} onClick={() => onAction({
          type: "playback", target: reference ? "reference" : "candidate", mode: "toggle",
        })}
          aria-label={`${playing ? "Pause" : "Play"} ${reference ? "As is reference" : "export candidate"}`}
          className={`inline-flex min-w-0 flex-auto items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold disabled:opacity-45 ${reference
            ? "bg-[#b8dbe6] text-[#1d3038]" : "bg-[#c9e5a6] text-[#1d3020]"}`}>
          <span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span><span>{playing ? "Pause" : "Play"}</span>
          <ShortcutBadge keyboard={playShortcut} bindingId={playShortcutId} />
        </button>
        <button type="button" disabled={!ready} onClick={() => onAction({
          type: "playback", target: reference ? "reference" : "candidate", mode: "replay",
        })}
          aria-label={`Replay ${reference ? "As is reference" : "export candidate"}`}
          className={`inline-flex min-w-0 flex-auto items-center justify-center gap-1 rounded-lg px-2 py-2 text-xs font-semibold disabled:opacity-45 ${reference
            ? "bg-[#344c55]" : "bg-[#38563c]"}`}>
          <span>Replay</span>
          <ShortcutBadge keyboard={replayShortcut} bindingId={replayShortcutId} />
        </button>
      </div>
      <p className="mono mt-2 text-xs font-semibold" aria-label={`${durationLabel} ${durationText}`}>{clock(positionMs - startMs)} <span className="subtle font-normal">/ {clock(durationMs)}</span></p>
      {error && <p role="alert" className="mt-2 text-xs text-[#ffb3a8]">{error}</p>}
    </div>
    <div className="mt-3 min-w-0 sm:mt-0">
      <audio ref={audioRef} src={src} preload="metadata" playsInline
        onLoadedMetadata={() => seek(startMs)} onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setPositionMs(endMs); }} />
      {sourceContext && <audio ref={contextAudioRef} src={sourceContext.audioSrc} preload="metadata" playsInline
        onPlay={() => setContextPlaying(true)} onPause={() => setContextPlaying(false)} onEnded={() => setContextPlaying(false)} />}
      {displayWaveform?.mins.length ? <WaveformPlot
        label={`${reference ? "As is reference" : "Export candidate"} waveform`}
        range={range} waveform={displayWaveform} startMs={selection.start} endMs={selection.end}
        playheadMs={timelinePlayhead} originalStartMs={null} compact
        sharedPeak={sharedPeak} trimMap={trimMap} disabled={(!sourceContext && !ready) || editingDisabled}
        canEdit={Boolean(onTrim)}
        pinHandles={Boolean(sourceContext && onTrim)}
        gestureTarget={cardRef}
        clockOffsetMs={sourceContext ? timelineOrigin : 0} onResetViewport={() => setViewport(initialViewport())}
        minSpan={Math.min(100, timelineDuration)} maxSpan={Math.min(120_000, timelineDuration)} onViewportChange={viewportChange}
        onPreviewRange={previewRange} onCommitRange={(start, end) => {
          if (onTrim) commit(start, end);
          else seekTimeline(end);
        }}
        onPreviewEdge={previewEdge} onCommitEdge={(edge, time) => {
          const bounded = clamp(time, edge === "start" ? timelineMin : selection.start + 10,
            edge === "start" ? selection.end - 10 : timelineMax);
          commit(edge === "start" ? bounded : selection.start, edge === "end" ? bounded : selection.end, edge);
        }}
        onCancel={() => setSelection({ start: 0, end: selectedDuration })} onSeek={seekTimeline} />
        : <>
          <p className="subtle flex h-24 items-center justify-center px-4 text-center text-sm" aria-live="polite">{sourceContext ? "Loading recording waveform…" : placeholder}</p>
          {/* Holds the height of the waveform's clock row, so the card doesn't grow when the waveform arrives. */}
          <div aria-hidden="true" className="mono invisible mt-1 text-[11px]">00:00:00.000</div>
        </>}
      {sourceWaveform.error && sourceContext && <p role="alert" className="text-xs text-[#ffb3a8]">{sourceWaveform.error} <button onClick={sourceWaveform.retry}>Retry</button></p>}
      {/* The legend keeps its line while a render is on its way, so the layout below doesn't jump. */}
      {(trimMap || sourceContext) && <p aria-hidden={!trimMap}
        className={`mt-1 flex items-center gap-2 text-[11px] text-[#edbc97] ${trimMap ? "" : "invisible"}`}>
        <span aria-hidden="true" className="h-2.5 w-3 rounded-sm border border-[#edbc97] bg-[#e6ad87]/25" />
        {trimMap && !removedRanges(trimMap).length ? "No audio removed" : "Shaded audio is removed from the export"}
      </p>}
    </div>
    <p className="subtle mt-1 text-[11px] sm:col-span-2">{note}</p>
  </div>;
});

export default PreviewPlayer;
