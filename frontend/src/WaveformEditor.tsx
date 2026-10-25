import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Clip, type SnapPoints, type TrimMap, type WaveformWindow } from "./api";
import { adjacentSnap, edgeSnap, nearestSnap, snapsInRange, snapTargets } from "./snapPoints";
import { removedRanges } from "./trimMap";
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
import { ShortcutBadge } from "./ShortcutBadge";

type Edge = "start" | "end";
type TimeRange = { start: number; end: number };

const MIN_CLIP_MS = 10;
const KEYBOARD_NUDGE_DEBOUNCE_MS = 300;
const BOUNDARY_AUDITION_MS = 500;
const MAX_WINDOW_MS = 120_000;
const FINE_WINDOW_MS = 700;
const MIN_OVERVIEW_SPAN_MS = 500;
const MIN_FINE_SPAN_MS = 100;
const MAX_FINE_SPAN_MS = 10_000;
const WAVEFORM_FETCH_DELAY_MS = 80;
// Trackpad pinch arrives as ctrlKey wheel events; this maps deltaY to a zoom factor.
const PINCH_ZOOM_SPEED = 0.01;
const PLOT_WIDTH = 1000;
const PLOT_HEIGHT = 160;
const NUB_WIDTH = 18;
const NUB_HEIGHT = 33;
const NUB_TOP = 4;
const MARKER_LINE_HIT_WIDTH = 3;
// A dragged edge snaps to a point this many screen pixels away; Option bypasses it.
const SNAP_DISTANCE_PX = 8;
// Keyboard and controller jumps ignore snap points further away than this, such as across a long silence.
const MAX_SNAP_JUMP_MS = 5000;
// A background drag selects a new range only after moving this many screen pixels; less is a click.
const RANGE_DRAG_MIN_PX = 4;
// Each snap point's solid tab (start points at the bottom, end points at the top) is this tall, in plot units.
const SNAP_TAB_HEIGHT = 12;
// Clicks reach a tab from further away than it is drawn: this far into the plot, in plot units,
// and this many screen pixels to either side.
const SNAP_TAB_HIT_HEIGHT = 36;
const SNAP_TAB_HIT_PX = 10;
const START_COLOR = "#f2cf86";
const END_COLOR = "#e7a6ca";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export function boundedRange(start: number, span: number, duration: number): TimeRange {
  const width = Math.min(duration, Math.max(1, Math.round(span)));
  const boundedStart = clamp(Math.round(start), 0, duration - width);
  return { start: boundedStart, end: boundedStart + width };
}

/**
 * The snap point whose tab is under a point on the plot, in plot units: start tabs
 * sit along the bottom edge, end tabs along the top. ``tolerance`` is in plot units.
 */
export function snapTabAt(
  snaps: { start?: readonly number[]; end?: readonly number[] } | undefined,
  range: TimeRange, point: { x: number; y: number }, tolerance: number,
): { edge: Edge; time: number } | null {
  const span = range.end - range.start;
  const edge: Edge | null = point.y >= PLOT_HEIGHT - SNAP_TAB_HIT_HEIGHT ? "start" : point.y <= SNAP_TAB_HIT_HEIGHT ? "end" : null;
  if (!edge || !snaps?.[edge]?.length || span <= 0) return null;
  let best: { edge: Edge; time: number } | null = null;
  let bestDistance = tolerance;
  for (const time of snapsInRange(snaps[edge]!, range.start, range.end)) {
    const distance = Math.abs((time - range.start) / span * PLOT_WIDTH - point.x);
    if (distance <= bestDistance) {
      best = { edge, time };
      bestDistance = distance;
    }
  }
  return best;
}

export function waveformPanDelta(event: Pick<WheelEvent, "deltaX" | "deltaY" | "shiftKey">): number {
  return event.deltaX || (event.shiftKey ? event.deltaY : 0);
}

export function initialRange(clip: Pick<Clip, "start_ms" | "end_ms">, duration: number): TimeRange {
  // A little context on each side, so the clip fills most of the view.
  const length = clip.end_ms - clip.start_ms;
  const padding = clamp(Math.round(length * 0.15), 200, 1000);
  const span = clamp(length + 2 * padding, 500, MAX_WINDOW_MS);
  return boundedRange(clip.start_ms - padding, span, duration);
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

export function useWaveform(clipId: string, range: TimeRange, buckets: number, active = true) {
  const [waveform, setWindow] = useState<WaveformWindow | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setError("");
    // Keep the previous window on screen while the next one loads so panning
    // and zooming stay continuous; the plot positions it by its own time span.
    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({
        start_ms: String(range.start), end_ms: String(range.end), buckets: String(buckets),
      });
      void api<WaveformWindow>(`/waveforms/${encodeURIComponent(clipId)}?${query}`, "GET", undefined, controller.signal)
        .then(setWindow)
        .catch((cause) => {
          if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
        });
    }, WAVEFORM_FETCH_DELAY_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [clipId, range.start, range.end, buckets, retry, active]);

  return { window: waveform, error, retry: () => setRetry((value) => value + 1) };
}

export function WaveformPlot({ label, range, waveform, startMs, endMs, playheadMs, editableEdge,
  originalStartMs, disabled, minSpan, maxSpan, onViewportChange, trimMap, sharedPeak, compact = false, onSeek, canEdit = true, gestureTarget,
  clockOffsetMs = 0, onResetViewport, pinHandles = false, shadeOutside = false, showClock = true, snapTargets: snaps,
  onPreviewRange, onCommitRange, onPreviewEdge, onCommitEdge, onCancel }: {
  label: string;
  range: TimeRange;
  waveform: WaveformWindow | null;
  startMs: number;
  endMs: number;
  playheadMs: number;
  originalStartMs: number | null;
  editableEdge?: Edge;
  disabled: boolean;
  minSpan: number;
  maxSpan: number;
  trimMap?: TrimMap | null;
  sharedPeak?: number;
  compact?: boolean;
  onSeek?: (time: number) => void;
  canEdit?: boolean;
  gestureTarget?: React.RefObject<HTMLElement | null>;
  clockOffsetMs?: number;
  onResetViewport?: () => void;
  pinHandles?: boolean;
  /** Dim the padding outside the clip, for view-only plots without handles. */
  shadeOutside?: boolean;
  showClock?: boolean;
  /** Points each edge snaps to while dragged, drawn as ticks. */
  snapTargets?: { start?: readonly number[]; end?: readonly number[] };
  onViewportChange: (start: number, span: number) => TimeRange;
  onPreviewRange: (start: number, end: number) => void;
  onCommitRange: (start: number, end: number) => void;
  onPreviewEdge: (edge: Edge, time: number) => void;
  onCommitEdge: (edge: Edge, time: number) => void;
  onCancel: () => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [overSnapTab, setOverSnapTab] = useState(false);
  const dragging = useRef<{ kind: "range"; start: number; clientX: number; moved: boolean } | { kind: "edge"; edge: Edge }
    | { kind: "pan"; start: number; span: number; clientX: number } | null>(null);
  const points = useMemo(() => {
    if (!waveform?.mins.length) return "";
    const count = Math.min(waveform.mins.length, waveform.maxs.length);
    const peak = Math.max(0.05, sharedPeak ?? Math.max(...waveform.mins.map(Math.abs), ...waveform.maxs.map(Math.abs)));
    const lines: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const x = ((index + 0.5) * PLOT_WIDTH / count).toFixed(1);
      const top = clamp(PLOT_HEIGHT / 2 - waveform.maxs[index] / peak * 64, 8, PLOT_HEIGHT - 8);
      const bottom = clamp(PLOT_HEIGHT / 2 - waveform.mins[index] / peak * 64, 8, PLOT_HEIGHT - 8);
      lines.push(`M${x} ${top.toFixed(1)}V${bottom.toFixed(1)}`);
    }
    return lines.join("");
  }, [waveform, sharedPeak]);

  const span = range.end - range.start;
  // The waveform may be a stale window from before the latest pan or zoom.
  const waveformTransform = waveform
    ? `translate(${(waveform.start_ms - range.start) / span * PLOT_WIDTH} 0) scale(${(waveform.end_ms - waveform.start_ms) / span} 1)`
    : undefined;

  // Wheel events arrive faster than React re-renders, so gestures accumulate
  // against this ref instead of the last rendered range.
  const view = useRef(range);
  view.current = range;
  const gesture = useRef({ minSpan, maxSpan, onViewportChange, dragging, onCancel });
  gesture.current = { minSpan, maxSpan, onViewportChange, dragging, onCancel };

  useEffect(() => {
    const svg = svgRef.current!;
    const target = gestureTarget?.current ?? svg;
    let pinchStartSpan: number | null = null;

    function cancelDrag() {
      if (!dragging.current) return;
      dragging.current = null;
      gesture.current.onCancel();
    }

    function apply(start: number, nextSpan: number) {
      const { minSpan: low, maxSpan: high, onViewportChange: change } = gesture.current;
      view.current = change(start, clamp(nextSpan, low, high));
    }

    function zoomAround(clientX: number, nextSpan: number) {
      const { start, end } = view.current;
      const current = end - start;
      const { minSpan: low, maxSpan: high } = gesture.current;
      const bounded = clamp(nextSpan, low, high);
      const rectangle = svg.getBoundingClientRect();
      const ratio = clamp((clientX - rectangle.left) / rectangle.width, 0, 1);
      apply(start + ratio * current - ratio * bounded, bounded);
    }

    function wheel(event: WheelEvent) {
      if (dragging.current) {
        if (event.buttons) return;
        cancelDrag();
      }
      const width = Math.max(1, svg.getBoundingClientRect().width);
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? width : 1;
      const { start, end } = view.current;
      const current = end - start;
      if (event.ctrlKey) {
        event.preventDefault();
        zoomAround(event.clientX, current * Math.exp(event.deltaY * scale * PINCH_ZOOM_SPEED));
        return;
      }
      // Horizontal two-finger swipes pan; vertical ones keep scrolling the page
      // unless Shift turns them into a horizontal scroll.
      const delta = waveformPanDelta(event);
      if (!delta) return;
      event.preventDefault();
      apply(start + delta * scale / width * current, current);
    }

    // Safari reports trackpad pinches as gesture events instead of ctrl+wheel.
    function gestureStart(event: Event) {
      event.preventDefault();
      cancelDrag();
      pinchStartSpan = view.current.end - view.current.start;
    }
    function gestureChange(event: Event) {
      event.preventDefault();
      const detail = event as Event & { scale: number; clientX: number };
      if (pinchStartSpan === null || !detail.scale) return;
      zoomAround(detail.clientX, pinchStartSpan / detail.scale);
    }
    function gestureEnd(event: Event) {
      event.preventDefault();
      pinchStartSpan = null;
    }

    target.addEventListener("wheel", wheel as EventListener, { passive: false, capture: true });
    target.addEventListener("gesturestart", gestureStart, { passive: false, capture: true });
    target.addEventListener("gesturechange", gestureChange, { passive: false, capture: true });
    target.addEventListener("gestureend", gestureEnd, { passive: false, capture: true });
    window.addEventListener("blur", cancelDrag);
    return () => {
      target.removeEventListener("wheel", wheel as EventListener, true);
      target.removeEventListener("gesturestart", gestureStart, true);
      target.removeEventListener("gesturechange", gestureChange, true);
      target.removeEventListener("gestureend", gestureEnd, true);
      window.removeEventListener("blur", cancelDrag);
    };
  }, []);

  const markerX = (time: number) => (time - range.start) / span * PLOT_WIDTH;
  const inRange = (time: number) => time >= range.start && time <= range.end;
  const startX = markerX(startMs);
  const endX = markerX(endMs);
  const nubWidth = compact ? 40 : NUB_WIDTH;
  function nubTop(edge: Edge) {
    const overlap = pinHandles && !inRange(startMs) && !inRange(endMs)
      && (startMs < range.start) === (endMs < range.start);
    return NUB_TOP + (overlap && edge === "end" ? NUB_HEIGHT + 5 : 0);
  }

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

  /** Pull a dragged edge onto a nearby snap point unless Option is held: a start back, an end forward. */
  function snapped(edge: Edge, time: number, bypass: boolean): number {
    const targets = snaps?.[edge];
    if (bypass || !targets?.length) return time;
    const width = Math.max(1, svgRef.current!.getBoundingClientRect().width);
    return edgeSnap(targets, time, SNAP_DISTANCE_PX / width * span, edge) ?? time;
  }

  function hitsNub(edge: Edge, point: { x: number; y: number }): boolean {
    const time = edge === "start" ? startMs : endMs;
    if (!inRange(time) && !pinHandles) return false;
    const left = clamp(markerX(time) - nubWidth / 2, 0, PLOT_WIDTH - nubWidth);
    return point.x >= left && point.x <= left + nubWidth
      && point.y >= nubTop(edge) && point.y <= nubTop(edge) + NUB_HEIGHT;
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
    if (event.shiftKey) {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragging.current = { kind: "pan", start: range.start, span, clientX: event.clientX };
      return;
    }
    if (!canEdit) { onSeek?.(point.time); return; }
    const edge = hitNub(point);
    if (edge) {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragging.current = { kind: "edge", edge };
      onPreviewEdge(edge, snapped(edge, point.time, event.altKey));
      return;
    }
    // A snap point's tab moves its edge straight there.
    const tab = snapTabAt(snaps, range, point, snapTabTolerance());
    if (tab) {
      onPreviewEdge(tab.edge, tab.time);
      onCommitEdge(tab.edge, tab.time);
      return;
    }
    if (hitsMarkerLine(point)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    // The new range shows once the pointer moves, so a press doesn't pair the new start
    // with the old end for a frame, and a plain click (a seek) changes nothing.
    dragging.current = { kind: "range", start: snapped("start", point.time, event.altKey), clientX: event.clientX, moved: false };
  }

  function snapTabTolerance(): number {
    return SNAP_TAB_HIT_PX / Math.max(1, svgRef.current!.getBoundingClientRect().width) * PLOT_WIDTH;
  }

  function pointerMove(event: React.PointerEvent<SVGSVGElement>) {
    const drag = dragging.current;
    if (!drag) {
      if (!canEdit || disabled) return;
      const point = position(event.clientX, event.clientY);
      const over = !hitNub(point) && snapTabAt(snaps, range, point, snapTabTolerance()) !== null;
      if (over !== overSnapTab) setOverSnapTab(over);
      return;
    }
    if (drag.kind === "pan") {
      const width = event.currentTarget.getBoundingClientRect().width;
      view.current = onViewportChange(drag.start - (event.clientX - drag.clientX) / width * drag.span, drag.span);
      return;
    }
    const point = position(event.clientX, event.clientY);
    if (drag.kind === "edge") onPreviewEdge(drag.edge, snapped(drag.edge, point.time, event.altKey));
    else {
      if (!drag.moved && Math.abs(event.clientX - drag.clientX) < RANGE_DRAG_MIN_PX) return;
      drag.moved = true;
      onPreviewRange(drag.start, snapped("end", point.time, event.altKey));
    }
  }

  function pointerUp(event: React.PointerEvent<SVGSVGElement>) {
    const drag = dragging.current;
    if (!drag) return;
    dragging.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (drag.kind === "pan") return;
    const time = position(event.clientX, event.clientY).time;
    if (drag.kind === "edge") onCommitEdge(drag.edge, snapped(drag.edge, time, event.altKey));
    else {
      if (!drag.moved && Math.abs(event.clientX - drag.clientX) < RANGE_DRAG_MIN_PX) {
        onCancel();
        onSeek?.(time);
        return;
      }
      const end = snapped("end", time, event.altKey);
      onPreviewRange(drag.start, end);
      onCommitRange(drag.start, end);
    }
  }

  function pointerCancel() {
    if (!dragging.current) return;
    dragging.current = null;
    onCancel();
  }

  return <div>
    <svg ref={svgRef} role={onSeek ? "slider" : "img"} aria-label={label} viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`}
      aria-valuemin={onSeek ? Math.min(range.start, startMs) : undefined} aria-valuemax={onSeek ? Math.max(range.end, endMs) : undefined}
      aria-valuenow={onSeek ? playheadMs : undefined} aria-valuetext={onSeek ? formatClock(playheadMs + clockOffsetMs) : undefined}
      data-view-start={range.start} data-view-end={range.end}
      tabIndex={onSeek && !disabled ? 0 : undefined}
      onKeyDown={(event) => {
        if (!onSeek || disabled) return;
        const target = event.key === "ArrowLeft" ? playheadMs - 100 : event.key === "ArrowRight" ? playheadMs + 100
          : event.key === "Home" ? startMs : event.key === "End" ? endMs : null;
        if (target !== null) { event.preventDefault(); onSeek(target); }
      }}
      preserveAspectRatio="none" onPointerDown={pointerDown} onPointerMove={pointerMove}
      onPointerUp={pointerUp} onPointerCancel={pointerCancel} onLostPointerCapture={pointerCancel}
      onPointerLeave={() => setOverSnapTab(false)}
      className={`block ${compact ? "h-24" : "h-36"} w-full ${overSnapTab ? "cursor-pointer" : canEdit || onSeek ? "cursor-crosshair" : "cursor-default"} overscroll-x-none rounded-lg border border-[#46584c] bg-[#101a17] touch-none`}>
      {trimMap && removedRanges(trimMap).map(([start, end]) => <g key={start}>
        <title>{`Removed ${(start / 1000).toFixed(2)}–${(end / 1000).toFixed(2)} s`}</title>
        <rect x={markerX(start)} y="0" width={(end - start) / span * PLOT_WIDTH} height={PLOT_HEIGHT} fill="#e6ad87" fillOpacity=".22" />
        {[start, end].map((time) => <line key={time} x1={markerX(time)} x2={markerX(time)} y1="0" y2={PLOT_HEIGHT}
          stroke="#edbc97" strokeDasharray="4 4" />)}
      </g>)}
      {[250, 500, 750].map((x) => <line key={x} x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke="#526259" strokeWidth="1" opacity="0.35" />)}
      <line x1="0" y1={PLOT_HEIGHT / 2} x2={PLOT_WIDTH} y2={PLOT_HEIGHT / 2} stroke="#46584c" strokeWidth="1" />
      {inRange(startMs) && inRange(endMs) && <rect x={Math.min(startX, endX)} y="0" width={Math.abs(endX - startX)} height={PLOT_HEIGHT} fill="#b7d69d" opacity="0.08" />}
      {points && <path d={points} transform={waveformTransform} vectorEffect="non-scaling-stroke"
        stroke="#a8c9b0" strokeWidth="1.5" fill="none" />}
      {(["start", "end"] as Edge[]).map((kind) => snaps?.[kind] && <g key={kind} aria-hidden="true">
        {snapsInRange(snaps[kind]!, range.start, range.end).map((time) => {
          const x = markerX(time);
          const color = kind === "start" ? START_COLOR : END_COLOR;
          // A full-height guide shows where the edge will land; a solid tab on
          // the start points' bottom or the end points' top tells the two apart.
          return <g key={time}>
            <line x1={x} x2={x} y1="0" y2={PLOT_HEIGHT} stroke={color} strokeWidth="1.5"
              strokeDasharray={kind === "end" ? "5 4" : undefined} opacity="0.55" vectorEffect="non-scaling-stroke" />
            <line x1={x} x2={x} y1={kind === "start" ? PLOT_HEIGHT - SNAP_TAB_HEIGHT : 0} y2={kind === "start" ? PLOT_HEIGHT : SNAP_TAB_HEIGHT}
              stroke={color} strokeWidth="5" vectorEffect="non-scaling-stroke" />
          </g>;
        })}
      </g>)}
      {shadeOutside && <g aria-hidden="true">
        <rect x="0" y="0" width={clamp(startX, 0, PLOT_WIDTH)} height={PLOT_HEIGHT} fill="#101816" opacity="0.6" />
        <rect x={clamp(endX, 0, PLOT_WIDTH)} y="0" width={PLOT_WIDTH - clamp(endX, 0, PLOT_WIDTH)} height={PLOT_HEIGHT} fill="#101816" opacity="0.6" />
        {[startX, endX].map((x) => <line key={x} x1={x} x2={x} y1="0" y2={PLOT_HEIGHT} stroke="#b7d69d" strokeWidth="1.5" opacity="0.7" />)}
      </g>}
      {originalStartMs !== null && inRange(originalStartMs) && <g>
        <title>Original SRT start</title>
        <line x1={markerX(originalStartMs)} y1="0" x2={markerX(originalStartMs)} y2={PLOT_HEIGHT}
          stroke="#80b7c8" strokeWidth="2" strokeDasharray="6 4" opacity="0.95" />
        <text x={clamp(markerX(originalStartMs) + 5, 5, PLOT_WIDTH - 35)} y="14"
          fill="#a9d6e2" fontSize="11">SRT</text>
      </g>}
      {canEdit && (["start", "end"] as Edge[]).map((edge) => {
        const time = edge === "start" ? startMs : endMs;
        if (!inRange(time) && !pinHandles) return null;
        const x = markerX(time);
        const color = edge === "start" ? START_COLOR : END_COLOR;
        return <g key={edge} aria-label={`${edge === "start" ? "Start" : "End"} boundary handle`}>
          <title>{`${edge === "start" ? "Start" : "End"} ${formatClock(time + clockOffsetMs)}${inRange(time) ? "" : " · outside this view; drag to move"}`}</title>
          {snaps?.[edge]?.includes(time) && <line x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke={color}
            strokeWidth="9" opacity="0.35" vectorEffect="non-scaling-stroke" />}
          <line x1={x} y1="0" x2={x} y2={PLOT_HEIGHT} stroke={color} strokeWidth="3" />
          <rect x={clamp(x - nubWidth / 2, 0, PLOT_WIDTH - nubWidth)} y={nubTop(edge)}
            width={nubWidth} height={NUB_HEIGHT} rx="4" fill={color} />
        </g>;
      })}
      {inRange(playheadMs) && <line x1={markerX(playheadMs)} y1="0" x2={markerX(playheadMs)} y2={PLOT_HEIGHT} stroke="#f2f4ef" strokeWidth="2" opacity="0.9" />}
    </svg>
    {showClock && <div className="subtle mono mt-1 flex justify-between text-[11px]">
      <span>{formatClock(range.start + clockOffsetMs)}</span>
      {onResetViewport ? <span className="flex gap-1">
        <button type="button" aria-label={`Zoom out ${label}`} onClick={() => {
          const next = Math.min(maxSpan, span * 2);
          onViewportChange((range.start + range.end - next) / 2, next);
        }} className="rounded px-1 hover:bg-[#304538]">−</button>
        <button type="button" aria-label={`Fit ${label}`} onClick={onResetViewport} className="rounded px-1 hover:bg-[#304538]">Fit</button>
        <button type="button" aria-label={`Zoom in ${label}`} onClick={() => {
          const next = Math.max(minSpan, span / 2);
          onViewportChange((range.start + range.end - next) / 2, next);
        }} className="rounded px-1 hover:bg-[#304538]">+</button>
      </span> : <span>{formatClock(Math.round((range.start + range.end) / 2) + clockOffsetMs)}</span>}
      <span>{formatClock(range.end + clockOffsetMs)}</span>
    </div>}
  </div>;
}

export default function WaveformEditor({ clip, durationMs, audioSrc, busy, gamepadAction, onGamepadActionHandled,
  shortcutsPaused, active = true, detectLeadingSilence, showOriginalStart, onSave, onPlayback, autoplay = false, snapPoints = null, snapping = true }: {
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
  /** Called for every clip playback (replay, play/pause, boundary audition). */
  onPlayback?: () => void;
  /** Play the clip once from its start when it is first shown. */
  autoplay?: boolean;
  /** Word starts and speech ends that boundaries snap to; null while loading or unavailable. */
  snapPoints?: SnapPoints | null;
  /** Off hides every snap control; the Settings option. */
  snapping?: boolean;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const savingRef = useRef(false);
  const keyboardNudgeTimer = useRef<number | null>(null);
  const pendingKeyboardBounds = useRef<{ startMs: number; endMs: number } | null>(null);
  const commitBoundsRef = useRef<(startMs: number, endMs: number) => Promise<void>>(async () => {});
  // A drag that ends while an earlier save is still running waits here instead of being dropped.
  const queuedBounds = useRef<{ startMs: number; endMs: number } | null>(null);
  // The bounds being saved right now; until that save lands the clip prop still holds the old ones.
  const savingBounds = useRef<{ startMs: number; endMs: number } | null>(null);
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
  const [selectedBoundary, setSelectedBoundary] = useState<Edge>("start");

  useEffect(() => {
    if (active) return;
    auditionStop.current = null;
    audioRef.current?.pause();
  }, [active]);
  const overview = useWaveform(clip.clip_id, overviewRange, 1000);
  const startDetail = useWaveform(clip.clip_id, startDetailRange, 800);
  const endDetail = useWaveform(clip.clip_id, endDetailRange, 800);

  useEffect(() => {
    // While a save runs or waits, the bounds on screen are newer than the clip; keep them.
    if (savingRef.current || queuedBounds.current) return;
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
    setSelectedBoundary(edgeToMove);
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    previewRange(nextStart, nextEnd);
  }

  async function commitBounds(nextStart: number, nextEnd: number) {
    if (keyboardNudgeTimer.current !== null) window.clearTimeout(keyboardNudgeTimer.current);
    keyboardNudgeTimer.current = null;
    pendingKeyboardBounds.current = null;
    if (savingRef.current || busy) {
      queuedBounds.current = { startMs: nextStart, endMs: nextEnd };
      previewRange(nextStart, nextEnd);
      return;
    }
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
    savingBounds.current = { startMs: nextStart, endMs: nextEnd };
    setSaving(true);
    try {
      const accepted = await onSave(nextStart, nextEnd);
      if (!accepted) {
        queuedBounds.current = null;
        setStartMs(clip.start_ms);
        setEndMs(clip.end_ms);
        setStartOffset(String(clip.start_ms - clip.original_start_ms));
        setEndOffset(String(clip.end_ms - clip.original_end_ms));
      }
    } finally {
      savingRef.current = false;
      savingBounds.current = null;
      setSaving(false);
    }
  }

  commitBoundsRef.current = commitBounds;

  // Save a drag that was queued behind an earlier save once that save is done.
  useEffect(() => {
    const queued = queuedBounds.current;
    if (saving || busy || !queued) return;
    queuedBounds.current = null;
    void commitBoundsRef.current(queued.startMs, queued.endMs);
  }, [saving, busy, clip.start_ms, clip.end_ms]);

  function commitEdge(edgeToMove: Edge, time: number) {
    const [nextStart, nextEnd] = boundsFor(edgeToMove, time);
    void commitBounds(nextStart, nextEnd);
  }

  function commitRange(nextStart: number, nextEnd: number) {
    void commitBounds(nextStart, nextEnd);
  }

  function cancelPreview() {
    // Go back to what was last placed: a drag still waiting or being saved, else the clip.
    const placed = queuedBounds.current ?? savingBounds.current;
    previewRange(placed?.startMs ?? clip.start_ms, placed?.endMs ?? clip.end_ms);
  }

  function nudge(which: Edge, amount: number, deferred = false) {
    setSelectedBoundary(which);
    if (!deferred) {
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

  /** Where the boundary sits relative to its snap points, so jumps are predictable. */
  function snapStatus(which: Edge): string {
    const targets = snapTargets(snapPoints, which);
    const position = which === "start" ? startMs : endMs;
    const name = which === "start" ? "word start" : "speech end";
    const reachable = (target: number | null) =>
      target === null || Math.abs(target - position) > MAX_SNAP_JUMP_MS ? "none within 5 s" : signed(target - position);
    const on = nearestSnap(targets, position, 0) !== null;
    const neighbours = `${name} ${reachable(adjacentSnap(targets, position, -1))} · next ${reachable(adjacentSnap(targets, position, 1))}`;
    return on ? `On a ${name} · previous ${neighbours}` : `Previous ${neighbours}`;
  }

  /** Move a boundary to its previous or next snap point, debounced like keyboard nudges. */
  function jumpToSnap(which: Edge, direction: -1 | 1) {
    const current = pendingKeyboardBounds.current ?? { startMs, endMs };
    const position = which === "start" ? current.startMs : current.endMs;
    const target = adjacentSnap(snapTargets(snapPoints, which), position, direction);
    if (target === null || Math.abs(target - position) > MAX_SNAP_JUMP_MS) {
      setSelectedBoundary(which);
      return;
    }
    nudge(which, target - position, true);
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
      if (action.type === "playback") event.preventDefault();
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
  // The waveforms stay usable while a save runs: a drag made meanwhile is queued and saved next (see queuedBounds).
  const hasSnapPoints = Boolean(snapPoints && (snapPoints.word_start.length || snapPoints.speech_end.length));
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
      onPlayback?.();
      if (action.mode === "replay") void replay();
      else if (action.mode === "toggle") void play();
      else if (action.mode === "audition-start") void audition("start");
      else void audition("end");
    } else if (action.type === "nudge") {
      nudge(action.edge, action.amount, action.source === "keyboard" || action.source === "gamepad");
    } else if (action.type === "select-boundary") {
      setSelectedBoundary(action.edge);
    } else if (action.type === "nudge-selected") {
      nudge(selectedBoundary, action.amount, true);
    } else if (action.type === "snap") {
      jumpToSnap(action.edge, action.direction);
    } else if (action.type === "snap-selected") {
      jumpToSnap(selectedBoundary, action.direction);
    }
  }

  const handledGamepadAction = useRef<number | null>(null);
  useEffect(() => {
    if (!gamepadAction || gamepadAction.clipId !== clip.clip_id || handledGamepadAction.current === gamepadAction.id ||
        !(gamepadAction.action.type === "nudge" || gamepadAction.action.type === "nudge-selected" ||
          gamepadAction.action.type === "snap" || gamepadAction.action.type === "snap-selected" ||
          (gamepadAction.action.type === "playback" && gamepadAction.action.target === "clip"))) return;
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

  const maxOverviewSpan = Math.min(MAX_WINDOW_MS, durationMs);
  const maxFineSpan = Math.min(MAX_FINE_SPAN_MS, durationMs);
  const viewportSetter = (setRange: (range: TimeRange) => void) =>
    (start: number, span: number) => {
      const next = boundedRange(start, span, durationMs);
      setRange(next);
      return next;
    };

  function zoom(factor: number) {
    const span = overviewRange.end - overviewRange.start;
    const nextSpan = clamp(Math.round(span * factor), MIN_OVERVIEW_SPAN_MS, maxOverviewSpan);
    const center = clamp(playheadMs, overviewRange.start, overviewRange.end);
    setOverviewRange(boundedRange(center - nextSpan / 2, nextSpan, durationMs));
  }

  function pan(direction: number) {
    const span = overviewRange.end - overviewRange.start;
    setOverviewRange(boundedRange(overviewRange.start + direction * span / 2, span, durationMs));
  }

  return <div className="mb-6">
    <audio ref={audioRef} src={audioSrc} preload="metadata" playsInline
      onLoadedMetadata={() => {
        seek(clip.start_ms);
        // Autoplay is best effort: before the first interaction the browser may block it.
        if (autoplay && active && !shortcutsPaused) {
          audioRef.current?.play().then(() => onPlayback?.(), () => {});
        }
      }} onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "replay" })} title="Replay from start (Space)"
          className="btn btn-secondary">
          <span aria-hidden="true" className="text-base leading-none">↻</span><span>Replay from start</span><ShortcutBadge keyboard="Space" bindingId="replay" />
        </button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "toggle" })} className="btn btn-secondary"
          aria-label={playing ? "Pause audio" : "Play clip"} title="Play or pause (Shift+Space)">
          <span aria-hidden="true" className="text-xs leading-none">{playing ? "❚❚" : "▶"}</span><span>{playing ? "Pause" : "Play clip"}</span><ShortcutBadge keyboard="Shift+Space" bindingId="play-pause" />
        </button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "audition-start" })} className="btn btn-quiet">Hear start</button>
        <button type="button" onClick={() => dispatchAction({ type: "playback", target: "clip", mode: "audition-end" })} className="btn btn-quiet">Hear end</button>
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
            snapTargets={{ start: snapTargets(snapPoints, "start"), end: snapTargets(snapPoints, "end") }}
            disabled={false} minSpan={MIN_OVERVIEW_SPAN_MS} maxSpan={maxOverviewSpan}
            onViewportChange={viewportSetter(setOverviewRange)} onPreviewRange={previewRange} onCommitRange={commitRange}
            onPreviewEdge={previewEdge} onCommitEdge={commitEdge} onCancel={cancelPreview} />}
      <p className="subtle mt-1 text-xs">Drag a nub or the background to set the edges. {!snapping ? "" : hasSnapPoints
        ? "Starts snap to amber word starts, ends to pink speech ends; click a tick's tab to move the edge there, or hold Option to place freely. "
        : "No snap points: this recording wasn't transcribed in the app. "}Swipe to pan, pinch to zoom.</p>
    </div>

    <div className="rounded-xl border border-[#405748] bg-[#1b2b23] p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-sm font-medium">Fine boundary views</h4>
          <span className="subtle text-xs" role="status">Controller boundary: <strong className="text-[#d8edb6]">{selectedBoundary}</strong> · fine 10 ms / coarse 100 ms</span>
        </div>
      <div className="grid gap-5 md:grid-cols-2">
        {(["start", "end"] as Edge[]).map((which) => {
          const detail = which === "start" ? startDetail : endDetail;
          const range = which === "start" ? startDetailRange : endDetailRange;
          const offset = which === "start" ? startOffset : endOffset;
          const setOffset = which === "start" ? setStartOffset : setEndOffset;
          const keyPair = which === "start" ? [",", "."] : ["[", "]"];
          return <div key={which} className="min-w-0">
            <h5 className="mb-2 text-sm font-medium"><button type="button" onClick={() => dispatchAction({ type: "select-boundary", edge: which })}
              aria-pressed={selectedBoundary === which} className={selectedBoundary === which ? "accent underline" : "subtle hover:text-[#e7eee7]"}>Fine {which}</button></h5>
            {detail.error ? <p role="alert" className="text-sm text-[#ffb3a8]">{detail.error} <button type="button" onClick={detail.retry} className="underline">Retry</button></p>
              : !detail.window ? <p className="subtle py-8 text-center text-sm">Loading fine waveform…</p>
                : <WaveformPlot label={`Fine ${which} boundary waveform; drag its boundary nub to fine-tune, or drag the waveform background to select a new range`}
                  range={range} waveform={detail.window} startMs={startMs} endMs={endMs}
                  playheadMs={playheadMs} editableEdge={which}
                  snapTargets={{ [which]: snapTargets(snapPoints, which) }}
                  originalStartMs={showOriginalStart ? clip.original_start_ms : null}
                  disabled={false} minSpan={MIN_FINE_SPAN_MS} maxSpan={maxFineSpan}
                  onViewportChange={viewportSetter(which === "start" ? setStartDetailRange : setEndDetailRange)}
                  onPreviewRange={previewRange} onCommitRange={commitRange}
                  onPreviewEdge={previewEdge} onCommitEdge={commitEdge} onCancel={cancelPreview} />}
            {hasSnapPoints && <p className="subtle mt-1 text-xs" role="status">{snapStatus(which)}</p>}
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={`Nudge ${which} boundary`}>
              {[-100, -10, 10, 100].map((amount) => {
                const key = `${Math.abs(amount) === 100 ? "⇧" : ""}${amount < 0 ? keyPair[0] : keyPair[1]}`;
                const shortcutId = which === "start"
                  ? amount === -100 ? "nudge-start-coarse-back" : amount === -10 ? "nudge-start-fine-back" : amount === 10 ? "nudge-start-fine-forward" : "nudge-start-coarse-forward"
                  : amount === -100 ? "nudge-end-coarse-back" : amount === -10 ? "nudge-end-fine-back" : amount === 10 ? "nudge-end-fine-forward" : "nudge-end-coarse-forward";
                return <button key={amount} type="button" onClick={() => dispatchAction({ type: "nudge", edge: which, amount, source: "pointer" })}
                  disabled={controlsDisabled} title={`Nudge ${which} boundary ${amount > 0 ? "+" : ""}${amount} ms (${key})`}
                  className="btn btn-secondary mono">
                  <span>{amount > 0 ? "+" : ""}{amount} ms</span><ShortcutBadge keyboard={key} bindingId={shortcutId} />
                </button>;
              })}
              {snapping && ([-1, 1] as const).map((direction) => {
                const shortcutId = which === "start"
                  ? direction < 0 ? "snap-start-back" : "snap-start-forward"
                  : direction < 0 ? "snap-end-back" : "snap-end-forward";
                const key = `⌥ ${direction < 0 ? keyPair[0] : keyPair[1]}`;
                const target = which === "start" ? "word start" : "speech end";
                return <button key={`snap${direction}`} type="button" onClick={() => dispatchAction({ type: "snap", edge: which, direction })}
                  disabled={controlsDisabled || !hasSnapPoints} title={`Move ${which} to the ${direction < 0 ? "previous" : "next"} ${target} (${key})`}
                  className="btn btn-secondary">
                  <span>{direction < 0 ? `◂ ${target}` : `${target} ▸`}</span><ShortcutBadge keyboard={key} bindingId={shortcutId} />
                </button>;
              })}
              {which === "start" && detectLeadingSilence && <button type="button"
                onClick={() => void commitBounds(clip.original_start_ms, endMs)}
                disabled={controlsDisabled || startMs === clip.original_start_ms || clip.original_start_ms > endMs - MIN_CLIP_MS}
                title="Restore the start time from the SRT"
                className="btn btn-quiet">
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
