import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Clip, type WaveformWindow } from "./api";
import {
  deactivateTextEditingTarget,
  getInputContext,
  isActionAvailable,
  keyboardInputFromEvent,
  resolveKeyboardAction,
  shouldDispatchAction,
  type InputAction,
} from "./inputActions";
import type { GamepadActionRequest } from "./gamepad";

type Edge = "start" | "end";
type TimeRange = { start: number; end: number };

const MIN_CLIP_MS = 10;
const KEYBOARD_NUDGE_DEBOUNCE_MS = 300;
const BOUNDARY_AUDITION_MS = 500;
const MAX_WINDOW_MS = 120_000;
const FINE_WINDOW_MS = 700;
const PLOT_WIDTH = 1000;
const PLOT_HEIGHT = 160;
const NUB_WIDTH = 18;
const NUB_HEIGHT = 33;
const NUB_TOP = 4;
const MARKER_LINE_HIT_WIDTH = 3;

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
  return boundedRange(time - FINE_WINDOW_MS / 2, FINE_WINDOW_MS, duration);
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
  originalStartMs, disabled, onPreviewRange, onCommitRange, onPreviewEdge, onCommitEdge, onCancel }: {
  label: string;
  range: TimeRange;
  waveform: WaveformWindow | null;
  startMs: number;
  endMs: number;
  playheadMs: number;
  originalStartMs: number | null;
  editableEdge?: Edge;
  disabled: boolean;
  onPreviewRange: (start: number, end: number) => void;
  onCommitRange: (start: number, end: number) => void;
  onPreviewEdge: (edge: Edge, time: number) => void;
  onCommitEdge: (edge: Edge, time: number) => void;
  onCancel: () => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<{ kind: "range"; start: number } | { kind: "edge"; edge: Edge } | null>(null);
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

  function position(clientX: number, clientY: number): { time: number; x: number; y: number } {
    const rectangle = svgRef.current!.getBoundingClientRect();
    const x = clamp(clientX - rectangle.left, 0, rectangle.width);
    const y = clamp(clientY - rectangle.top, 0, rectangle.height);
    return {
      time: Math.round(range.start + x / rectangle.width * span),
      x: x / rectangle.width * PLOT_WIDTH,
      y: y / rectangle.height * PLOT_HEIGHT,
    };
  }

  function hitsNub(edge: Edge, point: { x: number; y: number }): boolean {
    const time = edge === "start" ? startMs : endMs;
    if (!inRange(time)) return false;
    const left = clamp(markerX(time) - NUB_WIDTH / 2, 0, PLOT_WIDTH - NUB_WIDTH);
    return point.x >= left && point.x <= left + NUB_WIDTH
      && point.y >= NUB_TOP && point.y <= NUB_TOP + NUB_HEIGHT;
  }

  function hitsMarkerLine(point: { x: number }): boolean {
    const halfWidth = MARKER_LINE_HIT_WIDTH / 2;
    return (inRange(startMs) && Math.abs(point.x - startX) <= halfWidth)
      || (inRange(endMs) && Math.abs(point.x - endX) <= halfWidth);
  }

  function hitNub(point: { x: number; y: number }): Edge | null {
    const startHit = hitsNub("start", point);
    const endHit = hitsNub("end", point);
    if (editableEdge) {
      return editableEdge === "start" ? (startHit ? "start" : null) : (endHit ? "end" : null);
    }
    if (startHit && endHit) {
      return Math.abs(point.x - startX) <= Math.abs(point.x - endX) ? "start" : "end";
    }
    if (startHit) return "start";
    if (endHit) return "end";
    return null;
  }

  function pointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (disabled || event.button !== 0) return;
    const point = position(event.clientX, event.clientY);
    event.preventDefault();
    const edge = hitNub(point);
    if (edge) {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragging.current = { kind: "edge", edge };
      onPreviewEdge(edge, point.time);
      return;
    }
    if (hitsMarkerLine(point)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = { kind: "range", start: point.time };
    onPreviewRange(point.time, endMs);
  }

  function pointerMove(event: React.PointerEvent<SVGSVGElement>) {
    const drag = dragging.current;
    if (!drag) return;
    const point = position(event.clientX, event.clientY);
    if (drag.kind === "edge") onPreviewEdge(drag.edge, point.time);
    else onPreviewRange(drag.start, point.time);
  }

  function pointerUp(event: React.PointerEvent<SVGSVGElement>) {
    const drag = dragging.current;
    if (!drag) return;
    dragging.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const time = position(event.clientX, event.clientY).time;
    if (drag.kind === "edge") onCommitEdge(drag.edge, time);
    else {
      onPreviewRange(drag.start, time);
      onCommitRange(drag.start, time);
    }
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
      {inRange(startMs) && inRange(endMs) && <rect x={Math.min(startX, endX)} y="0" width={Math.abs(endX - startX)} height={PLOT_HEIGHT} fill="#b7d69d" opacity="0.08" />}
      {points && <path d={points} stroke="#a8c9b0" strokeWidth="1.5" fill="none" />}
      {originalStartMs !== null && inRange(originalStartMs) && <g>
        <title>Original SRT start</title>
        <line x1={markerX(originalStartMs)} y1="0" x2={markerX(originalStartMs)} y2={PLOT_HEIGHT}
          stroke="#80b7c8" strokeWidth="2" strokeDasharray="6 4" opacity="0.95" />
        <text x={clamp(markerX(originalStartMs) + 5, 5, PLOT_WIDTH - 35)} y="14"
          fill="#a9d6e2" fontSize="11">SRT</text>
      </g>}
      {(["start", "end"] as Edge[]).map((edge) => {
        const time = edge === "start" ? startMs : endMs;
        if (!inRange(time)) return null;
        const x = markerX(time);
        const color = edge === "start" ? "#f2cf86" : "#e7a6ca";
        return <g key={edge}>
          <line x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke={color} strokeWidth="3" />
          <rect x={clamp(x - NUB_WIDTH / 2, 0, PLOT_WIDTH - NUB_WIDTH)} y={NUB_TOP}
            width={NUB_WIDTH} height={NUB_HEIGHT} rx="4" fill={color} />
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

export default function WaveformEditor({ clip, durationMs, audioSrc, busy, gamepadAction, onGamepadActionHandled,
  shortcutsPaused, active = true, detectLeadingSilence, showOriginalStart, onSave }: {
  clip: Clip;
  durationMs: number;
  audioSrc: string;
  busy: boolean;
  gamepadAction?: GamepadActionRequest | null;
  onGamepadActionHandled?: (id: number) => void;
  shortcutsPaused: boolean;
  active?: boolean;
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  onSave: (startMs: number, endMs: number) => Promise<boolean>;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const savingRef = useRef(false);
  const keyboardNudgeTimer = useRef<number | null>(null);
  const pendingKeyboardBounds = useRef<{ startMs: number; endMs: number } | null>(null);
  const commitBoundsRef = useRef<(startMs: number, endMs: number) => Promise<void>>(async () => {});
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

  useEffect(() => {
    if (active) return;
    auditionStop.current = null;
    audioRef.current?.pause();
  }, [active]);
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
    if (!showOriginalStart) return;
    setOverviewRange((current) => {
      const start = Math.min(current.start, clip.original_start_ms);
      const end = Math.max(current.end, clip.original_start_ms);
      const next = boundedRange(start, Math.min(MAX_WINDOW_MS, end - start), durationMs);
      return next.start === current.start && next.end === current.end ? current : next;
    });
  }, [showOriginalStart, clip.original_start_ms, durationMs]);

  useEffect(() => {
    setStartDetailRange((current) => {
      const margin = (current.end - current.start) * 0.15;
      const originalVisible = !showOriginalStart || (
        clip.original_start_ms >= current.start + margin && clip.original_start_ms <= current.end - margin
      );
      if (clip.start_ms >= current.start + margin && clip.start_ms <= current.end - margin && originalVisible) return current;
      const centered = fineRange(clip.start_ms, durationMs);
      return centered.start === current.start && centered.end === current.end ? current : centered;
    });
  }, [clip.start_ms, clip.original_start_ms, durationMs, showOriginalStart]);

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

  function boundsFor(
    edgeToMove: Edge, time: number, currentStart = startMs, currentEnd = endMs,
  ): [number, number] {
    const position = Math.round(time);
    return edgeToMove === "start"
      ? [clamp(position, 0, currentEnd - MIN_CLIP_MS), currentEnd]
      : [currentStart, clamp(position, currentStart + MIN_CLIP_MS, durationMs)];
  }

  function previewRange(nextStart: number, nextEnd: number) {
    setStartMs(nextStart);
    setEndMs(nextEnd);
    setStartOffset(String(nextStart - clip.original_start_ms));
    setEndOffset(String(nextEnd - clip.original_end_ms));
  }

  function previewEdge(edgeToMove: Edge, time: number) {
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    previewRange(nextStart, nextEnd);
  }

  async function commitBounds(nextStart: number, nextEnd: number) {
    if (keyboardNudgeTimer.current !== null) window.clearTimeout(keyboardNudgeTimer.current);
    keyboardNudgeTimer.current = null;
    pendingKeyboardBounds.current = null;
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

  commitBoundsRef.current = commitBounds;

  function commitEdge(edgeToMove: Edge, time: number) {
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    void commitBounds(nextStart, nextEnd);
  }

  function commitRange(nextStart: number, nextEnd: number) {
    void commitBounds(nextStart, nextEnd);
  }

  function cancelPreview() {
    setStartMs(clip.start_ms);
    setEndMs(clip.end_ms);
    setStartOffset(String(clip.start_ms - clip.original_start_ms));
    setEndOffset(String(clip.end_ms - clip.original_end_ms));
  }

  function nudge(which: Edge, amount: number, fromKeyboard = false) {
    if (!fromKeyboard) {
      commitEdge(which, (which === "start" ? startMs : endMs) + amount);
      return;
    }

    const current = pendingKeyboardBounds.current ?? { startMs, endMs };
    const [nextStart, nextEnd] = boundsFor(
      which,
      (which === "start" ? current.startMs : current.endMs) + amount,
      current.startMs,
      current.endMs,
    );
    if (nextStart === current.startMs && nextEnd === current.endMs) return;

    pendingKeyboardBounds.current = { startMs: nextStart, endMs: nextEnd };
    setStartMs(nextStart);
    setEndMs(nextEnd);
    setStartOffset(String(nextStart - clip.original_start_ms));
    setEndOffset(String(nextEnd - clip.original_end_ms));
    if (keyboardNudgeTimer.current !== null) window.clearTimeout(keyboardNudgeTimer.current);
    keyboardNudgeTimer.current = window.setTimeout(() => {
      keyboardNudgeTimer.current = null;
      const pending = pendingKeyboardBounds.current;
      if (pending) void commitBoundsRef.current(pending.startMs, pending.endMs);
    }, KEYBOARD_NUDGE_DEBOUNCE_MS);
  }

  useEffect(() => () => {
    if (keyboardNudgeTimer.current !== null) window.clearTimeout(keyboardNudgeTimer.current);
    const pending = pendingKeyboardBounds.current;
    if (pending) void commitBoundsRef.current(pending.startMs, pending.endMs);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const input = keyboardInputFromEvent(event);
      const action = resolveKeyboardAction("waveform", input, waveformContext);
      if (!action || !shouldDispatchAction(action, input)) return;
      if (action.type === "deactivate-text-editing") {
        event.preventDefault();
        deactivateTextEditingTarget(event.target);
        return;
      }
      if (savingRef.current || !isActionAvailable(action, {
        context: waveformContext,
        busy: controlsDisabled,
        enabled: active,
        hasSelection: true,
        canMutate: !controlsDisabled,
      })) return;
      event.preventDefault();
      dispatchAction(action);
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
    const playStart = which === "start" ? startMs : Math.max(startMs, endMs - BOUNDARY_AUDITION_MS);
    const playEnd = which === "start" ? Math.min(endMs, startMs + BOUNDARY_AUDITION_MS) : endMs;
    seek(playStart);
    auditionStop.current = playEnd;
    try { await audioRef.current?.play(); setLocalError(""); }
    catch { setLocalError("Audio playback was blocked. Press Play again after interacting with the page."); }
  }

  const controlsDisabled = busy || saving;
  const waveformContext = getInputContext({ activeDialog: shortcutsPaused || !active });

  function dispatchAction(action: InputAction) {
    if (!isActionAvailable(action, {
      context: waveformContext,
      busy: controlsDisabled,
      enabled: active,
      hasSelection: true,
      canMutate: !controlsDisabled,
    })) return;
    if (action.type === "playback" && action.target === "clip") {
      if (action.mode === "replay") void replay();
      else if (action.mode === "toggle") void play();
      else if (action.mode === "audition-start") void audition("start");
      else void audition("end");
    } else if (action.type === "nudge") {
      nudge(action.edge, action.amount, action.source === "keyboard");
    }
  }

  const handledGamepadAction = useRef<number | null>(null);
  useEffect(() => {
    if (!gamepadAction || gamepadAction.clipId !== clip.clip_id || handledGamepadAction.current === gamepadAction.id) return;
    handledGamepadAction.current = gamepadAction.id;
    dispatchAction(gamepadAction.action);
    onGamepadActionHandled?.(gamepadAction.id);
  }, [clip.clip_id, gamepadAction, onGamepadActionHandled]);

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

  return <div className="mb-6">
    <audio ref={audioRef} src={audioSrc} preload="metadata" playsInline
      onLoadedMetadata={() => seek(clip.start_ms)} onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "replay" })} title="Replay from start (Space)"
          className="inline-flex items-center gap-2 rounded-lg bg-[#b7d69d] px-3 py-2 text-sm font-medium text-[#1b291f] hover:bg-[#c8e5af]">
          <span aria-hidden="true" className="text-base leading-none">↻</span><span>Replay from start</span><kbd aria-hidden="true" className="shortcut-key">Space</kbd>
        </button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "toggle" })} className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
          aria-label={playing ? "Pause audio" : "Play clip"} title="Play or pause (Shift+Space)">
          <span aria-hidden="true" className="text-xs leading-none">{playing ? "❚❚" : "▶"}</span><span>{playing ? "Pause" : "Play clip"}</span><kbd aria-hidden="true" className="shortcut-key">Shift+Space</kbd>
        </button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "audition-start" })} className="soft-surface rounded-lg px-3 py-2 text-sm">Hear start</button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "audition-end" })} className="soft-surface rounded-lg px-3 py-2 text-sm">Hear end</button>
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
          : <WaveformPlot label="Overview waveform; drag a boundary nub to fine-tune it, or drag the waveform background to select a new range"
            range={overviewRange} waveform={overview.window} startMs={startMs} endMs={endMs}
            playheadMs={playheadMs} originalStartMs={showOriginalStart ? clip.original_start_ms : null}
            disabled={controlsDisabled} onPreviewRange={previewRange} onCommitRange={commitRange}
            onPreviewEdge={previewEdge} onCommitEdge={commitEdge} onCancel={cancelPreview} />}
      <p className="subtle mt-1 text-xs">Drag the amber or pink nub to adjust one boundary. Drag the waveform background from the new start to the new end; the vertical marker lines are not draggable.</p>
    </div>

    <div className="rounded-xl border border-[#405748] bg-[#1b2b23] p-3">
      <h4 className="mb-2 text-sm font-medium">Fine boundary views</h4>
      <div className="grid gap-5 md:grid-cols-2">
        {(["start", "end"] as Edge[]).map((which) => {
          const detail = which === "start" ? startDetail : endDetail;
          const range = which === "start" ? startDetailRange : endDetailRange;
          const offset = which === "start" ? startOffset : endOffset;
          const setOffset = which === "start" ? setStartOffset : setEndOffset;
          const keyPair = which === "start" ? [",", "."] : ["[", "]"];
          return <div key={which} className="min-w-0">
            <h5 className="mb-2 text-sm font-medium">Fine {which}</h5>
            {detail.error ? <p role="alert" className="text-sm text-[#ffb3a8]">{detail.error} <button type="button" onClick={detail.retry} className="underline">Retry</button></p>
              : !detail.window ? <p className="subtle py-8 text-center text-sm">Loading fine waveform…</p>
                : <WaveformPlot label={`Fine ${which} boundary waveform; drag its boundary nub to fine-tune, or drag the waveform background to select a new range`}
                  range={range} waveform={detail.window} startMs={startMs} endMs={endMs}
                  playheadMs={playheadMs} editableEdge={which}
                  originalStartMs={showOriginalStart ? clip.original_start_ms : null}
                  disabled={controlsDisabled}
                  onPreviewRange={previewRange} onCommitRange={commitRange}
                  onPreviewEdge={previewEdge} onCommitEdge={commitEdge} onCancel={cancelPreview} />}
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={`Nudge ${which} boundary`}>
              {[-100, -10, 10, 100].map((amount) => {
                const key = `${Math.abs(amount) === 100 ? "⇧" : ""}${amount < 0 ? keyPair[0] : keyPair[1]}`;
                return <button key={amount} type="button" onClick={() => dispatchAction({ type: "nudge", edge: which, amount, source: "pointer" })}
                  disabled={controlsDisabled} title={`Nudge ${which} boundary ${amount > 0 ? "+" : ""}${amount} ms (${key})`}
                  className="mono inline-flex items-center justify-center gap-2 rounded-lg bg-[#304538] px-3 py-2 text-sm hover:bg-[#3b5543] disabled:opacity-50">
                  <span>{amount > 0 ? "+" : ""}{amount} ms</span><kbd aria-hidden="true" className="shortcut-key">{key}</kbd>
                </button>;
              })}
              {which === "start" && detectLeadingSilence && <button type="button"
                onClick={() => void commitBounds(clip.original_start_ms, endMs)}
                disabled={controlsDisabled || startMs === clip.original_start_ms || clip.original_start_ms > endMs - MIN_CLIP_MS}
                title="Restore the start time from the SRT"
                className="rounded-lg border line px-3 py-2 text-sm hover:bg-[#304538] disabled:opacity-50">
                Use original start
              </button>}
            </div>
            <label className="mt-3 block max-w-xs text-sm"><span className="subtle block text-xs">{which === "start" ? "Start" : "End"} offset from SRT (ms)</span>
              <input type="text" inputMode="numeric" value={offset}
                onChange={(event) => setOffset(event.target.value)}
                onBlur={(event) => offsetBlur(which, event.currentTarget.value)}
                onKeyDown={(event) => {
                  const input = keyboardInputFromEvent(event.nativeEvent);
                  if (input.key === "Enter" && !input.isComposing) { event.preventDefault(); event.currentTarget.blur(); }
                  if (input.key === "Escape" && !input.isComposing) { event.preventDefault(); cancelOffset(which, event.currentTarget); }
                }} disabled={controlsDisabled} className="mt-1 w-full rounded-lg border line bg-[#101816] px-3 py-2 mono" />
            </label>
          </div>;
        })}
      </div>
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
