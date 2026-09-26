import { forwardRef, memo, useCallback, useEffect, useId, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { WaveformWindow } from "./api";
import type { InputAction } from "./inputActions";

export interface PreviewPlayerHandle {
  toggle(): void;
  replay(): void;
  pause(): void;
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
  src?: string;
  placeholder: string;
  playShortcut: string;
  replayShortcut: string;
  onActivate(): void;
  onAction(action: InputAction): void;
};

const WIDTH = 1000;
const HEIGHT = 128;

const WaveformView = memo(function WaveformView({
  variant, waveformPath, ready, durationMs, positionMs, maskId, onPointerDown, onKeyDown,
}: {
  variant: "reference" | "candidate";
  waveformPath: string;
  ready: boolean;
  durationMs: number;
  positionMs: number;
  maskId: string;
  onPointerDown(event: React.PointerEvent<SVGSVGElement>): void;
  onKeyDown(event: React.KeyboardEvent<SVGSVGElement>): void;
}) {
  const reference = variant === "reference";
  const playheadX = clamp((positionMs / durationMs) * WIDTH, 0, WIDTH);
  return <svg role="slider" tabIndex={ready ? 0 : -1}
    aria-label={`Seek in ${reference ? "As is reference" : "export candidate"}`}
    aria-valuemin={0} aria-valuemax={durationMs} aria-valuenow={clamp(positionMs, 0, durationMs)}
    aria-valuetext={clock(positionMs)}
    viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none"
    onPointerDown={onPointerDown} onKeyDown={onKeyDown}
    className={`h-full w-full touch-none ${ready ? "cursor-crosshair" : "cursor-default"}`}>
    <line x1="0" y1={HEIGHT / 2} x2={WIDTH} y2={HEIGHT / 2}
      stroke={reference ? "#3f5c68" : "#385145"} strokeWidth="1" />
    <path d={waveformPath} fill="none" stroke={reference ? "#80b7c8" : "#91bd89"} strokeWidth="1.8" strokeLinecap="round" />
    <clipPath id={maskId}><rect x="0" y="0" width={playheadX} height={HEIGHT} /></clipPath>
    <path d={waveformPath} fill="none" stroke={reference ? "#d1e8ef" : "#d1e6b0"}
      strokeWidth="1.8" strokeLinecap="round" clipPath={`url(#${maskId})`} />
    {ready && <><line x1={playheadX} y1="5" x2={playheadX} y2={HEIGHT - 5} stroke="#f6faf1" strokeWidth="2" />
      <circle cx={playheadX} cy="7" r="4" fill="#f6faf1" /></>}
  </svg>;
});

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
  waveform, sharedPeak, src, placeholder, playShortcut, replayShortcut, onActivate, onAction,
}, ref) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const maskId = useId();
  const [positionMs, setPositionMs] = useState(startMs);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const ready = Boolean(src && endMs > startMs);
  const durationMs = Math.max(1, endMs - startMs);
  const reference = variant === "reference";

  const waveformPath = useMemo(() => {
    if (!waveform?.mins.length || waveform.mins.length !== waveform.maxs.length) return "";
    const peak = Math.max(0.05, sharedPeak);
    return waveform.mins.map((minimum, index) => {
      const x = ((index + 0.5) * WIDTH / waveform.mins.length).toFixed(1);
      const top = clamp(HEIGHT / 2 - waveform.maxs[index] / peak * 55, 5, HEIGHT - 5);
      const bottom = clamp(HEIGHT / 2 - minimum / peak * 55, 5, HEIGHT - 5);
      return `M${x} ${top.toFixed(1)}V${bottom.toFixed(1)}`;
    }).join("");
  }, [waveform, sharedPeak]);

  useEffect(() => {
    const audio = audioRef.current;
    audio?.pause();
    setPlaying(false);
    setPositionMs(startMs);
    setError("");
    if (audio && ready && audio.readyState >= HTMLMediaElement.HAVE_METADATA) {
      audio.currentTime = startMs / 1000;
    }
  }, [src, startMs, ready]);

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
      if (current >= endMs) {
        setPositionMs(endMs);
        audio.pause();
        return;
      }
      setPositionMs(clamp(current, startMs, endMs));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, startMs, endMs]);

  const seek = useCallback((ms: number) => {
    const position = clamp(Math.round(ms), startMs, endMs);
    const audio = audioRef.current;
    if (audio && ready) audio.currentTime = position / 1000;
    setPositionMs(position);
  }, [startMs, endMs, ready]);

  async function play(restart: boolean) {
    const audio = audioRef.current;
    if (!audio || !ready) return;
    if (!restart && !audio.paused) { audio.pause(); return; }
    if (restart || audio.currentTime * 1000 < startMs || audio.currentTime * 1000 >= endMs) seek(startMs);
    onActivate();
    try {
      await audio.play();
      setError("");
    } catch {
      setError("Playback was blocked. Press Play again after interacting with the page.");
    }
  }

  useImperativeHandle(ref, () => ({
    toggle: () => { void play(false); },
    replay: () => { void play(true); },
    pause: () => { audioRef.current?.pause(); },
  }));

  const seekFromPointer = useCallback((event: React.PointerEvent<SVGSVGElement>) => {
    if (!ready) return;
    const box = event.currentTarget.getBoundingClientRect();
    seek(startMs + (event.clientX - box.left) / box.width * durationMs);
  }, [ready, startMs, durationMs, seek]);

  const seekFromKey = useCallback((event: React.KeyboardEvent<SVGSVGElement>) => {
    if (!ready) return;
    const move = event.key === "ArrowRight" ? 100 : event.key === "ArrowLeft" ? -100 : 0;
    if (move) { event.preventDefault(); seek(positionMs + move); }
    else if (event.key === "Home") { event.preventDefault(); seek(startMs); }
    else if (event.key === "End") { event.preventDefault(); seek(endMs); }
  }, [ready, positionMs, seek, startMs, endMs]);

  return <div className={`relative grid min-w-0 gap-x-4 rounded-xl border p-3 sm:grid-cols-[270px_minmax(0,1fr)] ${reference
    ? "border-[#618a9c] bg-[#1c2b32]" : "border-[#8eb36c] bg-[#203225]"}`}>
    <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 rounded-l-xl ${reference ? "bg-[#7eb4c7]" : "bg-[#b7d69d]"}`} />
    <div className="min-w-0 pl-1">
      <p className={`text-[10px] font-bold uppercase tracking-[.13em] ${reference ? "text-[#b9dce7]" : "text-[#cee8ad]"}`}>{eyebrow}</p>
      <h4 className={`mt-0.5 text-sm font-semibold ${reference ? "text-[#d5edf4]" : "text-[#def0c7]"}`}>{title}</h4>
      <div className="mt-2 flex gap-1.5">
        <button type="button" disabled={!ready} onClick={() => onAction({
          type: "playback", target: reference ? "reference" : "candidate", mode: "toggle",
        })}
          aria-label={`${playing ? "Pause" : "Play"} ${reference ? "As is reference" : "export candidate"}`}
          className={`inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold disabled:opacity-45 ${reference
            ? "bg-[#b8dbe6] text-[#1d3038]" : "bg-[#c9e5a6] text-[#1d3020]"}`}>
          <span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span><span>{playing ? "Pause" : "Play"}</span>
          <kbd aria-hidden="true" className="shortcut-key">{playShortcut}</kbd>
        </button>
        <button type="button" disabled={!ready} onClick={() => onAction({
          type: "playback", target: reference ? "reference" : "candidate", mode: "replay",
        })}
          aria-label={`Replay ${reference ? "As is reference" : "export candidate"}`}
          className={`inline-flex min-w-0 flex-1 items-center justify-center gap-1 rounded-lg px-2 py-2 text-xs font-semibold disabled:opacity-45 ${reference
            ? "bg-[#344c55]" : "bg-[#38563c]"}`}>
          <span aria-hidden="true">↺</span><span>Replay</span>
          <kbd aria-hidden="true" className="shortcut-key">{replayShortcut}</kbd>
        </button>
      </div>
      <p className="mono mt-2 text-xs font-semibold">{clock(positionMs - startMs)} <span className="subtle font-normal">/ {clock(durationMs)}</span></p>
      <div className="mt-3 text-xs"><span className="subtle">{durationLabel}</span> <strong className={reference ? "text-[#d3ecf3]" : "text-[#d8edb6]"}>{durationText}</strong></div>
      <p className="subtle mt-1 text-[11px]">{note}</p>
      {error && <p role="alert" className="mt-2 text-xs text-[#ffb3a8]">{error}</p>}
    </div>
    <div className="mt-3 min-w-0 sm:mt-0">
      <audio ref={audioRef} src={src} preload="metadata" playsInline
        onLoadedMetadata={() => seek(startMs)} onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setPositionMs(endMs); }} />
      <div className={`flex h-32 items-center justify-center overflow-hidden rounded-lg border ${reference
        ? "border-[#4c7180] bg-[#111e24]" : "border-[#55774c] bg-[#132116]"}`}>
        {waveformPath ? <WaveformView variant={variant} waveformPath={waveformPath} ready={ready}
          durationMs={durationMs} positionMs={positionMs - startMs} maskId={maskId}
          onPointerDown={seekFromPointer} onKeyDown={seekFromKey} />
          : <p className="subtle px-4 text-center text-sm" aria-live="polite">{placeholder}</p>}
      </div>
      <div className="subtle mono mt-1 flex justify-between text-[11px]">
        <span>0:00</span><span>{ready ? "Click waveform to seek" : ""}</span><span>{clock(durationMs)}</span>
      </div>
    </div>
  </div>;
});

export default PreviewPlayer;
