import { useEffect, useRef, useState } from "react";
import type { Clip, Status } from "./api";
import type { GamepadActionRequest } from "./gamepad";
import {
  getInputContext,
  keyboardInputFromEvent,
  resolveKeyboardAction,
  shouldDispatchAction,
  type ClassificationStatus,
} from "./inputActions";
import { ShortcutBadge } from "./ShortcutBadge";
import { Button, Panel, StageLayout, statusLabels } from "./ui";

type PlaybackMode = "replay" | "toggle";

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

const decisions: { status: ClassificationStatus; label: string; keyboard: string }[] = [
  { status: "group1", label: statusLabels.group1, keyboard: "1" },
  { status: "group2", label: statusLabels.group2, keyboard: "2" },
  { status: "unsure", label: statusLabels.unsure, keyboard: "3" },
  { status: "rejected", label: "Reject", keyboard: "X" },
];

/**
 * One clip at a time for fast first-pass decisions, built for the gamepad.
 * Decisions, navigation, and undo arrive through the app's shared input
 * handling; this screen owns playback, which plays only the clip's span.
 */
export default function TriageScreen({
  clip, position, remaining, counts, audioSrc, autoplay, active, busy, orderNote,
  gamepadAction, onGamepadActionHandled, onPlayback, onDecide, onNavigate, onUndo, canUndo,
}: {
  clip: Clip | null;
  position: number;
  remaining: number;
  counts: Record<Status, number>;
  audioSrc: string;
  autoplay: boolean;
  active: boolean;
  busy: boolean;
  orderNote: string | null;
  gamepadAction?: GamepadActionRequest | null;
  onGamepadActionHandled?: (id: number) => void;
  onPlayback: () => void;
  onDecide: (status: ClassificationStatus) => void;
  onNavigate: (direction: "next" | "previous") => void;
  onUndo: () => void;
  canUndo: boolean;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const stopAtRef = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  // Browsers block sound until the page gets a click or key press; controller
  // buttons do not count. Remember the blocked play and retry it after one.
  const [soundBlocked, setSoundBlocked] = useState(false);
  const clipRef = useRef(clip);
  clipRef.current = clip;

  function play(mode: PlaybackMode) {
    const audio = audioRef.current;
    const current = clipRef.current;
    if (!audio || !current) return;
    if (mode === "toggle" && !audio.paused) { audio.pause(); return; }
    const position = audio.currentTime * 1000;
    if (mode === "replay" || position < current.start_ms || position >= current.end_ms) {
      audio.currentTime = current.start_ms / 1000;
    }
    stopAtRef.current = current.end_ms;
    audio.play().then(() => { setSoundBlocked(false); onPlayback(); }, (error: unknown) => {
      if (error instanceof DOMException && error.name === "NotAllowedError") setSoundBlocked(true);
    });
  }

  useEffect(() => {
    if (!soundBlocked) return;
    function unlock() { play("replay"); }
    window.addEventListener("pointerdown", unlock, { once: true, capture: true });
    window.addEventListener("keydown", unlock, { once: true, capture: true });
    return () => {
      window.removeEventListener("pointerdown", unlock, { capture: true });
      window.removeEventListener("keydown", unlock, { capture: true });
    };
  }, [soundBlocked]);

  // Stop at the clip's end and drive the progress bar.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const audio = audioRef.current;
      const current = clipRef.current;
      if (!audio || !current) return;
      const now = audio.currentTime * 1000;
      setProgress(Math.min(1, Math.max(0, (now - current.start_ms) / Math.max(1, current.end_ms - current.start_ms))));
      if (stopAtRef.current !== null && now >= stopAtRef.current) {
        audio.pause();
        stopAtRef.current = null;
        setProgress(1);
      } else {
        frame = requestAnimationFrame(tick);
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  // A new clip resets playback and, with autoplay, starts it once the audio can seek.
  useEffect(() => {
    const audio = audioRef.current;
    setProgress(0);
    if (!audio || !clip) return;
    audio.pause();
    if (!autoplay || !active) return;
    if (audio.readyState >= 1) {
      play("replay");
      return;
    }
    const start = () => play("replay");
    audio.addEventListener("loadedmetadata", start, { once: true });
    return () => audio.removeEventListener("loadedmetadata", start);
  }, [clip?.clip_id, clip?.start_ms, clip?.end_ms]);

  useEffect(() => {
    if (!active) audioRef.current?.pause();
  }, [active]);

  // Space / Shift+Space follow the same playback shortcuts as the waveform editor.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const input = keyboardInputFromEvent(event);
      const context = getInputContext({ activeDialog: !active });
      const action = resolveKeyboardAction("waveform", input, context);
      if (!action || action.type !== "playback" || action.target !== "clip" || !shouldDispatchAction(action, input)) return;
      event.preventDefault();
      play(action.mode === "toggle" ? "toggle" : "replay");
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const handledGamepadAction = useRef<number | null>(null);
  useEffect(() => {
    if (!gamepadAction || handledGamepadAction.current === gamepadAction.id) return;
    const action = gamepadAction.action;
    if (action.type !== "playback" || action.target !== "clip") return;
    handledGamepadAction.current = gamepadAction.id;
    play(action.mode === "toggle" ? "toggle" : "replay");
    onGamepadActionHandled?.(gamepadAction.id);
  }, [gamepadAction]);

  const kept = counts.group1 + counts.group2 + counts.exported;
  const decided = kept + counts.rejected + counts.unsure;

  const total = remaining + decided;

  return <StageLayout label="Triage" list={
    <Panel title="Progress" aside={<span className="subtle mono text-xs">{total ? Math.round(decided / total * 100) : 100}%</span>}>
      <div className="flex flex-col gap-3 p-4 text-sm" role="status">
        <div className="flex items-baseline justify-between gap-2">
          <span><strong className="mono text-2xl font-semibold">{decided.toLocaleString()}</strong> <span className="subtle">of {total.toLocaleString()} decided</span></span>
          <span className="mono font-semibold text-[#f5e7a9]">{remaining.toLocaleString()} left</span>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
          {([["group1", counts.group1], ["group2", counts.group2 + counts.exported], ["unsure", counts.unsure], ["rejected", counts.rejected]] as const)
            .map(([status, count]) => <div key={status} className="flex items-center gap-2">
              <span className={`status-dot status-${status}`} aria-hidden="true" />
              <dt className="flex-1">{statusLabels[status]}</dt><dd className="subtle mono">{count.toLocaleString()}</dd>
            </div>)}
        </dl>
        {orderNote && <p className="subtle text-xs">{orderNote}</p>}
      </div>
    </Panel>} main={<div className="flex min-w-0 flex-col gap-3">
    <audio ref={audioRef} src={audioSrc} preload="auto" playsInline
      onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    {soundBlocked && <p role="alert" className="rounded-lg border border-[#7c6845] bg-[#3c3525] px-4 py-3 text-sm">
      Sound is blocked until you click or press any key once on this page. Browsers don't count controller buttons.
    </p>}
    {clip ? <Panel ariaLabel={`Clip ${clip.clip_id}`} title={`Clip ${position} of ${remaining}`}
      aside={<span className="subtle mono flex items-center gap-2 text-xs">#{clip.clip_id} · {formatSeconds(clip.end_ms - clip.start_ms)}</span>}>
      <div className="p-5 md:p-7">
        <h2 title={clip.title} className="line-clamp-3 break-words text-3xl font-semibold leading-snug">{clip.title}</h2>
        <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-[#17241c]" role="progressbar"
          aria-label="Clip playback" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
          <div className="h-full bg-[#b7d69d]" style={{ width: `${progress * 100}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button onClick={() => play("replay")} shortcut="Space" shortcutId="replay">
            <span aria-hidden="true">↻</span>Replay
          </Button>
          <Button onClick={() => play("toggle")} ariaLabel={playing ? "Pause" : "Play"} shortcut="Shift+Space" shortcutId="play-pause">
            <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span>
          </Button>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4" role="group" aria-label="Decision">
          {decisions.map((decision) => <button key={decision.status} type="button" disabled={busy}
            onClick={() => onDecide(decision.status)}
            className={`btn btn-decision tone-${decision.status}`}>
            {decision.label}<ShortcutBadge keyboard={decision.keyboard} bindingId={decision.status} />
          </button>)}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t line pt-4">
          <Button variant="quiet" onClick={() => onNavigate("previous")} shortcut="K" shortcutId="previous">
            <span aria-hidden="true">←</span>Back
          </Button>
          <div className="flex gap-2">
            <Button variant="quiet" onClick={onUndo} disabled={!canUndo || busy} shortcut="U" shortcutId="undo">Undo</Button>
            <Button variant="quiet" onClick={() => onNavigate("next")} title="Leave this clip unsorted and move on" shortcut="J" shortcutId="next">
              Pass<span aria-hidden="true">→</span>
            </Button>
          </div>
        </div>
      </div>
    </Panel> : <Panel className="p-8 text-center">
      <h2 className="mb-2 text-2xl font-semibold">Everything is triaged</h2>
      <p className="subtle">No unsorted clips are left. Switch to Polish to fix titles and timing of your keepers.</p>
    </Panel>}
  </div>} />;
}
