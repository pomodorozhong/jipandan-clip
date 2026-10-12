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

type PlaybackMode = "replay" | "toggle";

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

const decisions: { status: ClassificationStatus; label: string; keyboard: string; tone: string }[] = [
  { status: "group1", label: "Group 1", keyboard: "1", tone: "bg-[#254d38] border-[#498c61] text-[#c1f3cd] hover:bg-[#2d5d43]" },
  { status: "group2", label: "Group 2", keyboard: "2", tone: "bg-[#284762] border-[#4c80a8] text-[#c4e7ff] hover:bg-[#305676]" },
  { status: "unsure", label: "Unsure", keyboard: "3", tone: "bg-[#573b26] border-[#a5683c] text-[#f6cfa8] hover:bg-[#68472e]" },
  { status: "rejected", label: "Reject", keyboard: "X", tone: "bg-[#36413e] border-[#66756e] text-[#d6e0da] hover:bg-[#424f4b]" },
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

  return <main className="flex min-h-0 flex-1 flex-col items-center overflow-auto px-4 py-6 md:py-10" aria-label="Triage">
    <audio ref={audioRef} src={audioSrc} preload="auto" playsInline
      onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    <div className="w-full max-w-2xl">
      <div className="subtle mb-3 flex flex-wrap items-center justify-between gap-2 text-xs" role="status">
        <span>{remaining.toLocaleString()} left · {decided.toLocaleString()} decided ({kept} kept · {counts.unsure} unsure · {counts.rejected} rejected)</span>
        {orderNote && <span>{orderNote}</span>}
      </div>
      {soundBlocked && <p role="alert" className="mb-3 rounded-lg border border-[#7c6845] bg-[#3c3525] px-4 py-3 text-sm">
        Sound is blocked until you click or press any key once on this page. Browsers don't count controller buttons.
      </p>}
      {clip ? <section className="surface rounded-2xl p-6 md:p-8" aria-label={`Clip ${clip.clip_id}`}>
        <div className="subtle mono mb-3 flex items-center justify-between text-xs">
          <span>#{clip.clip_id} · {position} of {remaining}</span>
          <span>{formatSeconds(clip.end_ms - clip.start_ms)}</span>
        </div>
        <h2 title={clip.title} className="line-clamp-3 break-words text-3xl font-semibold leading-snug md:text-4xl">{clip.title}</h2>
        <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-[#17241c]" role="progressbar"
          aria-label="Clip playback" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
          <div className="h-full bg-[#b7d69d]" style={{ width: `${progress * 100}%` }} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => play("replay")}
            className="inline-flex items-center gap-2 rounded-lg bg-[#b7d69d] px-3 py-2 text-sm font-medium text-[#1b291f] hover:bg-[#c8e5af]">
            <span aria-hidden="true">↻</span><span>Replay</span><ShortcutBadge keyboard="Space" bindingId="replay" />
          </button>
          <button type="button" onClick={() => play("toggle")} aria-label={playing ? "Pause" : "Play"}
            className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm">
            <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span><ShortcutBadge keyboard="Shift+Space" bindingId="play-pause" />
          </button>
        </div>
        <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4" role="group" aria-label="Decision">
          {decisions.map((decision) => <button key={decision.status} type="button" disabled={busy}
            onClick={() => onDecide(decision.status)}
            className={`flex flex-col items-center gap-2 rounded-xl border px-3 py-4 text-base font-semibold disabled:opacity-50 ${decision.tone}`}>
            <span>{decision.label}</span><ShortcutBadge keyboard={decision.keyboard} bindingId={decision.status} />
          </button>)}
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm">
          <div className="flex gap-2">
            <button type="button" onClick={() => onNavigate("previous")} className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2">
              <span aria-hidden="true">←</span><span>Back</span><ShortcutBadge keyboard="K" bindingId="previous" />
            </button>
            <button type="button" onClick={() => onNavigate("next")} className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2"
              title="Leave this clip unsorted and move on">
              <span>Pass</span><span aria-hidden="true">→</span><ShortcutBadge keyboard="J" bindingId="next" />
            </button>
          </div>
          <button type="button" onClick={onUndo} disabled={!canUndo || busy}
            className="soft-surface inline-flex items-center gap-2 rounded-lg px-3 py-2 disabled:opacity-50">
            <span>Undo</span><ShortcutBadge keyboard="U" bindingId="undo" />
          </button>
        </div>
      </section> : <section className="surface rounded-2xl p-8 text-center">
        <h2 className="mb-2 text-2xl font-semibold">Everything is triaged</h2>
        <p className="subtle">No unsorted clips are left. Switch to Polish to fix titles and timing of your keepers.</p>
      </section>}
    </div>
  </main>;
}
