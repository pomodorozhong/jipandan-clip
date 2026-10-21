import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { GamepadStatusBadge, gamepadStatusMessage } from "./GamepadStatus";
import {
  GAMEPAD_REPEAT_DELAY_MAX_MS,
  GAMEPAD_REPEAT_DELAY_MIN_MS,
  GAMEPAD_REPEAT_DELAY_STEP_MS,
  type GamepadStatus,
} from "./gamepad";
import type { BadgeMode, UnboundBadgeBehavior } from "./ShortcutBadge";
import { formatDuration, formatPerClip, formatShare, stageLabels, type StageTimes } from "./stageTimes";
import { Button } from "./ui";

const ROW_BASE = "grid items-center gap-x-6 gap-y-2.5 border-b border-[#2a3731] py-3.5 last:border-b-0";
// Checkboxes always sit beside their text; wider controls drop below it on narrow screens.
const CHECK_ROW = `${ROW_BASE} grid-cols-[minmax(0,1fr)_auto]`;
const ROW = `${ROW_BASE} grid-cols-1 justify-items-start sm:grid-cols-[minmax(0,1fr)_auto] sm:justify-items-stretch`;
const FIELD = "min-h-9 rounded-lg border line bg-[#101816] px-2.5 text-[13px]";

function SettingsSection({ title, tag, description, sectionRef, children }: {
  title: string;
  tag?: string;
  description?: ReactNode;
  sectionRef?: Ref<HTMLElement>;
  children: ReactNode;
}) {
  const headingId = useId();
  return <section ref={sectionRef} aria-labelledby={headingId}
    className="mt-5 rounded-xl border line bg-[#121b18] px-[18px] pt-4 pb-1 first:mt-0">
    <div className="flex min-h-6 items-center justify-between gap-3 border-b line pb-3">
      <h3 id={headingId} className="text-[15px] font-semibold">{title}</h3>
      {tag && <span className="clip-tag border-[#4c80a8] bg-[#284762] text-[#c4e7ff]">{tag}</span>}
    </div>
    {description && <p className="subtle mt-2.5 text-[13px]">{description}</p>}
    <div>{children}</div>
  </section>;
}

function RowText({ title, description, htmlFor, extra }: {
  title: string; description: ReactNode; htmlFor?: string; extra?: ReactNode;
}) {
  const Title = htmlFor ? "label" : "span";
  return <span className="min-w-0">
    <span className="flex flex-wrap items-center gap-2">
      <Title htmlFor={htmlFor} className="block text-sm font-semibold">{title}</Title>{extra}
    </span>
    <span className="subtle mt-0.5 block text-[13px]">{description}</span>
  </span>;
}

function CheckboxRow({ title, description, checked, onChange }: {
  title: string; description: ReactNode; checked: boolean; onChange: (checked: boolean) => void;
}) {
  return <label className={`${CHECK_ROW} cursor-pointer`}>
    <RowText title={title} description={description} />
    <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)}
      className="size-[18px] accent-[#b7d69d]" />
  </label>;
}

function ControlRow({ title, description, extra, children }: {
  title: string; description: ReactNode; extra?: ReactNode; children: (id: string) => ReactNode;
}) {
  const id = useId();
  return <div className={ROW}>
    <RowText title={title} description={description} htmlFor={id} extra={extra} />
    {children(id)}
  </div>;
}

function Footnote({ children }: { children: ReactNode }) {
  return <p className="subtle mt-3 mb-3.5 text-xs">{children}</p>;
}

const CELL = "border-b border-[#2a3731] px-2 py-2 text-right tabular-nums first:pl-0 first:text-left last:pr-0";

function formatDay(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// Time per stage for the open session, so the slowest stage can be worked on first.
function ReviewTimeSection({ enabled, onLoad }: { enabled: boolean; onLoad: () => Promise<StageTimes> }) {
  const [result, setResult] = useState<StageTimes | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function analyze() {
    setLoading(true);
    setError("");
    try {
      setResult(await onLoad());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read the review log");
    } finally {
      setLoading(false);
    }
  }

  return <SettingsSection title="Review time" tag="This session" description={enabled
    ? "Add up how long clips were on screen in each stage, from the session's review log."
    : "Open an audio session to see its review time."}>
    <div className="grid gap-3 py-3.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <Button disabled={!enabled || loading} onClick={() => void analyze()}>
          {loading ? "Analyzing…" : result ? "Analyze again" : "Analyze review time"}
        </Button>
        {result?.first_view && result.last_view && <span className="subtle text-xs">
          Views from {formatDay(result.first_view)} to {formatDay(result.last_view)}
        </span>}
      </div>
      {error && <p role="alert" className="text-xs text-[#ffb3a8]">{error}</p>}
      {result && (result.total_ms
        ? <table className="w-full border-collapse text-[13px]">
          <thead className="subtle text-xs">
            <tr>{["Stage", "Time", "Share", "Clips viewed", "Per clip", "Changes"].map((label) =>
              <th key={label} scope="col" className={`${CELL} font-medium`}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {result.stages.map((row) => <tr key={row.stage}>
              <th scope="row" className={`${CELL} font-semibold`}>{stageLabels[row.stage]}</th>
              <td className={CELL}>{formatDuration(row.ms)}</td>
              <td className={CELL}>{formatShare(row, result.total_ms)}</td>
              <td className={CELL}>{row.clips}</td>
              <td className={CELL}>{formatPerClip(row)}</td>
              <td className={CELL}>{row.changes}</td>
            </tr>)}
            <tr>
              <th scope="row" className={`${CELL} border-b-0 font-semibold`}>Total</th>
              <td className={`${CELL} border-b-0 font-semibold`}>{formatDuration(result.total_ms)}</td>
              <td className={`${CELL} border-b-0`} colSpan={4} />
            </tr>
          </tbody>
        </table>
        : <p className="subtle text-[13px]">No clip views recorded yet.</p>)}
    </div>
    <Footnote>Time counts while a clip is selected and the app is in front; it stops after 60 s without input and leaves out the clip on screen now until you move on. Changes count edits such as status, title, and trim, plus exports in Publish.</Footnote>
  </SettingsSection>;
}

export default function SettingsScreen({ clipDir, storageEnabled, storageBusy, storageMessage, storageError, onClipDirChange,
  onChooseClipDir, onResetClipDir, onApplyClipDir,
  detectLeadingSilence, showOriginalStart, exploreRanking, onExploreRankingChange,
  autoplayClips, onAutoplayClipsChange,
  gamepadStatus, gamepadMappingButtonRef, onOpenGamepadMapping, focusController = false,
  onDetectLeadingSilenceChange, onShowOriginalStartChange, badgeMode, unboundBadgeBehavior,
  onBadgeModeChange, onUnboundBadgeBehaviorChange, gamepadRepeatDelayMs,
  onGamepadRepeatDelayChange, snapEdges, onSnapEdgesChange, onLoadStageTimes }: {
  clipDir: string;
  storageEnabled: boolean;
  storageBusy: boolean;
  storageMessage: string;
  storageError: string;
  onClipDirChange: (path: string) => void;
  onChooseClipDir: () => void;
  onResetClipDir: () => void;
  onApplyClipDir: () => void;
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  exploreRanking: boolean;
  onExploreRankingChange: (enabled: boolean) => void;
  autoplayClips: boolean;
  onAutoplayClipsChange: (enabled: boolean) => void;
  gamepadStatus: GamepadStatus;
  gamepadMappingButtonRef?: Ref<HTMLButtonElement>;
  onOpenGamepadMapping: () => void;
  // Opened from the controller line in another dialog: start at the Controller section.
  focusController?: boolean;
  onDetectLeadingSilenceChange: (enabled: boolean) => void;
  onShowOriginalStartChange: (enabled: boolean) => void;
  snapEdges: boolean;
  onSnapEdgesChange: (enabled: boolean) => void;
  badgeMode: BadgeMode;
  unboundBadgeBehavior: UnboundBadgeBehavior;
  onBadgeModeChange: (mode: BadgeMode) => void;
  onUnboundBadgeBehaviorChange: (behavior: UnboundBadgeBehavior) => void;
  gamepadRepeatDelayMs: number;
  onGamepadRepeatDelayChange: (delayMs: number) => void;
  onLoadStageTimes: () => Promise<StageTimes>;
}) {
  const controllerRef = useRef<HTMLElement>(null);
  const clipDirId = useId();
  const clipDirRef = useRef<HTMLInputElement>(null);
  const storageDisabled = !storageEnabled || storageBusy;

  useEffect(() => {
    if (!storageError) return;
    // Wait a frame so the closing confirmation's focus restore doesn't win.
    const frame = requestAnimationFrame(() => clipDirRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [storageError]);

  useEffect(() => {
    if (!focusController) return;
    // Wait a frame so the closing dialog's focus restore doesn't win.
    const frame = requestAnimationFrame(() => {
      const section = controllerRef.current;
      section?.scrollIntoView({ block: "start" });
      section?.querySelector<HTMLElement>("button")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [focusController]);

  return <div>
    <SettingsSection title="Playback and review">
      <CheckboxRow title="Play each clip when it is selected" checked={autoplayClips} onChange={onAutoplayClipsChange}
        description="Hear every clip you land on without pressing Space, so each decision is based on listening." />
      <CheckboxRow title="Mix in random clips when ordering by Likely keep" checked={exploreRanking}
        onChange={onExploreRankingChange}
        description="About 1 in 20 clips is placed at a random position instead of by score. These reveal good clips the score ranks too low; they are not marked, so judge them like any other clip." />
      <Footnote>Your decisions, which clips you viewed and played, and where each clip ranked are recorded in the session's <code>.jipandan.db</code> file beside the recording, to improve the Likely keep score.</Footnote>
    </SettingsSection>

    <SettingsSection title="Clip timing">
      <CheckboxRow title="Detect leading silence" checked={detectLeadingSilence} onChange={onDetectLeadingSilenceChange}
        description="Analyze clips that still use their SRT start in the background and move them to the first sustained audio activity. You can restore the SRT start from the nudging screen." />
      <CheckboxRow title="Show original start time on waveform" checked={showOriginalStart}
        onChange={onShowOriginalStartChange}
        description="Draw the SRT start as a separate marker in the waveform views." />
      <CheckboxRow title="Snap clip edges" checked={snapEdges} onChange={onSnapEdgesChange}
        description="In Polish, show word starts and speech ends on the waveforms and snap dragged edges to them. Turn off to hide them and place edges freely." />
    </SettingsSection>

    <SettingsSection title="Controller" sectionRef={controllerRef}>
      <div className={ROW}>
        <RowText title="Status" description={gamepadStatusMessage(gamepadStatus)}
          extra={<GamepadStatusBadge status={gamepadStatus} />} />
        <Button buttonRef={gamepadMappingButtonRef} onClick={onOpenGamepadMapping}>Configure mapping</Button>
      </div>
      <ControlRow title="Debounce time"
        description="Delay before a held navigation or stick control repeats. Lower values respond faster; higher values filter accidental holds.">
        {(id) => <span className="flex items-center gap-3">
          <input id={id} type="range" min={GAMEPAD_REPEAT_DELAY_MIN_MS} max={GAMEPAD_REPEAT_DELAY_MAX_MS}
            step={GAMEPAD_REPEAT_DELAY_STEP_MS} value={gamepadRepeatDelayMs}
            onChange={(event) => onGamepadRepeatDelayChange(Number(event.target.value))}
            className="w-36 accent-[#b7d69d]" />
          <output htmlFor={id} className="mono subtle min-w-14 text-right text-[13px]" aria-live="polite">{gamepadRepeatDelayMs} ms</output>
        </span>}
      </ControlRow>
      <ControlRow title="Badge display"
        description="Auto starts with Xbox badges when a standard controller is connected, then follows the last meaningful input.">
        {(id) => <select id={id} value={badgeMode} onChange={(event) => onBadgeModeChange(event.target.value as BadgeMode)}
          className={`${FIELD} w-52`}>
          <option value="auto">Auto — last used input</option>
          <option value="keyboard">Keyboard</option>
          <option value="xbox">Xbox controller</option>
        </select>}
      </ControlRow>
      <ControlRow title="Unbound shortcut badges"
        description="New actions remain unbound until you capture a controller button.">
        {(id) => <select id={id} value={unboundBadgeBehavior}
          onChange={(event) => onUnboundBadgeBehaviorChange(event.target.value as UnboundBadgeBehavior)}
          className={`${FIELD} w-52`}>
          <option value="hide">Hide the badge</option>
          <option value="keyboard">Fall back to keyboard shortcut</option>
        </select>}
      </ControlRow>
      <Footnote>Controller actions pause while typing or this tab is inactive; dialogs use D-pad/left-stick focus, A confirm, and B back. Saving blocks mutating actions while navigation remains available. After reconnecting or changing context, release a held control before pressing it again.</Footnote>
    </SettingsSection>

    <ReviewTimeSection enabled={storageEnabled} onLoad={onLoadStageTimes} />

    <SettingsSection title="Storage" tag="This session" description={storageEnabled
      ? "Choose where new audio exports from this session are saved. Existing exported files stay in their current folder."
      : "Open an audio session to choose its export directory."}>
      <div className="grid gap-2 py-3.5">
        <RowText title="Export directory" htmlFor={clipDirId}
          description={<span id={`${clipDirId}-hint`}>Absolute paths and paths beginning with <code>~</code> are supported.</span>} />
        <input ref={clipDirRef} id={clipDirId} type="text" value={clipDir} disabled={storageDisabled}
          onChange={(event) => onClipDirChange(event.target.value)}
          placeholder="/path/to/exports" aria-invalid={Boolean(storageError)}
          aria-describedby={storageError ? `${clipDirId}-hint ${clipDirId}-error` : `${clipDirId}-hint`}
          className={`${FIELD} block w-full font-mono text-xs disabled:opacity-50 ${storageError ? "border-[#a96053]" : ""}`} />
        {storageError && <p id={`${clipDirId}-error`} role="alert" className="text-xs text-[#ffb3a8]">{storageError}</p>}
        <div className="mt-1 flex flex-wrap items-center gap-2.5">
          <Button disabled={storageDisabled} onClick={onChooseClipDir}>Choose folder…</Button>
          <Button disabled={storageDisabled} onClick={onResetClipDir}>Reset to default</Button>
          <span className="flex-1" />
          <Button variant="primary" disabled={storageDisabled || !clipDir.trim()} onClick={onApplyClipDir}>
            {storageBusy ? "Saving…" : "Apply export directory"}
          </Button>
        </div>
        {storageMessage && <span role="status" className="accent text-xs">{storageMessage}</span>}
      </div>
    </SettingsSection>
  </div>;
}
