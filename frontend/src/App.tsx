import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isExploreClip, orderByLikelyKeep } from "./reviewOrder";
import TriageScreen from "./TriageScreen";
import { isIdle, viewEvent, type OpenView, type ViewEndReason } from "./reviewViews";
import { api, applySessionDelta, audioUrl, bootstrap, sendReviewEvents, uploadAudio, type Clip, type ClipFeaturesJob, type ClipTranscriptionJob, type LeadingSilenceJob, type PreviewJob, type Session, type SessionDelta, type SnapPoints, type Status, type ClipSource, clipSourceLabels } from "./api";
import WaveformEditor from "./WaveformEditor";
import { Button, CountBadge, Panel, StageLayout, StatusBadge, statusLabels } from "./ui";
import { publishClips, type PublishView } from "./publish";
import ExportPreview, { type ExportSettings } from "./ExportPreview";
import ShortcutCheatsheet from "./ShortcutCheatsheet";
import TranscriptionScreen from "./TranscriptionScreen";
import SettingsScreen from "./SettingsScreen";
import type { StageTimes } from "./stageTimes";
import { countStatuses, isProcessed, isReviewSetOpen, normalizeReviewSetSize, orderReviewSet, REVIEW_SET_DEFAULT_SIZE, scopeClips } from "./reviewSet";
import GamepadStatusLine from "./GamepadStatus";
import GamepadMappingScreen from "./GamepadMappingScreen";
import { ShortcutBadge, ShortcutDisplayProvider, type BadgeMode, type DisplayInputType, type UnboundBadgeBehavior } from "./ShortcutBadge";
import {
  bindingsForGamepadConfig,
  publishGamepadBindings,
  createGamepadAdapter,
  GAMEPAD_REPEAT_DELAY_MS,
  initialGamepadStatus,
  loadGamepadBindingConfig,
  normalizeGamepadRepeatDelay,
  saveGamepadBindingConfig,
  type GamepadActionRequest,
  type GamepadBindingConfig,
  type GamepadStatus,
} from "./gamepad";
import {
  deactivateTextEditingTarget,
  getInputContext,
  installCompositionTracking,
  isActionAvailable,
  isTextEditingTarget,
  keyboardInputFromEvent,
  resolveKeyboardAction,
  shouldDispatchAction,
  type InputAvailability,
  type InputAction,
} from "./inputActions";

type Filter = "unsorted" | "group1" | "group2" | "rejected";
type AllOrder = "clip-asc" | "clip-desc" | "start-asc" | "start-desc" | "title-asc" | "likely-desc";
// An open review set orders every screen the same way.
type Order = AllOrder | "review-set";
type SaveState = "saved" | "saving" | "failed";
// Triage: one clip at a time for first-pass decisions. Polish: the list and editor for keepers.
// Publish: the Ready queue with export previews, title, and timing fixes.
type Mode = "triage" | "polish" | "publish";
type ExportAllRun = { state: "running" | "completed" | "cancelled" | "failed"; total: number; done: number; failed: string[]; error?: string };
type AppSettings = {
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  snapEdges: boolean;
  badgeMode: BadgeMode;
  unboundBadgeBehavior: UnboundBadgeBehavior;
  gamepadRepeatDelayMs: number;
  exploreRanking: boolean;
  autoplayClips: boolean;
  // The size last used for a review set.
  reviewSetSize: number;
};

// Titles longer than this get a "Show full title" toggle under their two-line clamp.
const LONG_TITLE_CHARS = 60;
const VIEW_FLUSH_MS = 10_000;
const VIEW_IDLE_CHECK_MS = 5_000;

const SETTINGS_STORAGE_KEY = "jipandan-settings";

function loadSettings(): AppSettings {
  try {
    const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<AppSettings>;
      return {
        detectLeadingSilence: typeof parsed.detectLeadingSilence === "boolean" ? parsed.detectLeadingSilence : true,
        showOriginalStart: typeof parsed.showOriginalStart === "boolean" ? parsed.showOriginalStart : false,
        snapEdges: typeof parsed.snapEdges === "boolean" ? parsed.snapEdges : true,
        badgeMode: parsed.badgeMode === "keyboard" || parsed.badgeMode === "xbox" ? parsed.badgeMode : "auto",
        unboundBadgeBehavior: parsed.unboundBadgeBehavior === "keyboard" ? "keyboard" : "hide",
        gamepadRepeatDelayMs: normalizeGamepadRepeatDelay(parsed.gamepadRepeatDelayMs),
        exploreRanking: typeof parsed.exploreRanking === "boolean" ? parsed.exploreRanking : true,
        autoplayClips: typeof parsed.autoplayClips === "boolean" ? parsed.autoplayClips : true,
        reviewSetSize: normalizeReviewSetSize(parsed.reviewSetSize),
      };
    }
  } catch { /* Use defaults when browser storage is unavailable or invalid. */ }
  return {
    detectLeadingSilence: true,
    showOriginalStart: false,
    snapEdges: true,
    badgeMode: "auto",
    unboundBadgeBehavior: "hide",
    gamepadRepeatDelayMs: GAMEPAD_REPEAT_DELAY_MS,
    exploreRanking: true,
    autoplayClips: true,
    reviewSetSize: REVIEW_SET_DEFAULT_SIZE,
  };
}

// Polish's tabs. Ready and Exported clips are listed in Publish, which can edit them too.
const filters: { key: Filter; label: string; hint: string }[] = [
  { key: "group1", label: statusLabels.group1, hint: "Fix titles and timing, then mark Ready" },
  { key: "unsorted", label: "Unsorted", hint: "Clips Triage hasn't decided yet" },
  { key: "rejected", label: statusLabels.rejected, hint: "Change a clip's status to bring it back" },
];

const allOrders: { key: AllOrder; label: string }[] = [
  { key: "clip-asc", label: "Clip number ↑" },
  { key: "clip-desc", label: "Clip number ↓" },
  { key: "start-asc", label: "Start time ↑" },
  { key: "start-desc", label: "Start time ↓" },
  { key: "title-asc", label: "Title A–Z" },
  { key: "likely-desc", label: "Likely keep ↓" },
];

// Top bar stages and the count each one shows: what is still left to do there.
const stageItems: { mode: Mode; label: string; status: Status }[] = [
  { mode: "triage", label: "Triage", status: "pending" },
  { mode: "polish", label: "Polish", status: "group1" },
  { mode: "publish", label: "Publish", status: "group2" },
];

function UndoIcon() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 3 2 6l3 3" /><path d="M2 6h7.5a4 4 0 0 1 0 8H7" /></svg>;
}

function HelpIcon() {
  return <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" aria-hidden="true"><circle cx="9" cy="9" r="7.2" />
    <path d="M6.9 7a2.2 2.2 0 1 1 3 2c-.6.3-.9.7-.9 1.3v.4" /><circle cx="9" cy="13.2" r=".4" fill="currentColor" /></svg>;
}

function SettingsIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
    <circle cx="12" cy="12" r="3" /></svg>;
}

function formatDuration(ms: number): string {
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
}

function visibleClips(clips: Clip[], filter: Filter, query: string): Clip[] {
  const needle = query.trim().normalize("NFKC").toLocaleLowerCase();
  return clips.filter((clip) => {
    if (filter === "unsorted" && clip.status !== "pending") return false;
    if (filter !== "unsorted" && clip.status !== filter) return false;
    if (needle && !clip.title.normalize("NFKC").toLocaleLowerCase().includes(needle)) return false;
    return true;
  });
}

function Dialog({ title, children, onClose, controllerHandlerRef, wide = false }: {
  title: string; children: React.ReactNode; onClose: () => void; wide?: boolean;
  controllerHandlerRef: React.MutableRefObject<((action: InputAction) => void) | null>;
}) {
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      if (previousFocus) requestAnimationFrame(() => previousFocus.focus());
    };
  }, []);

  useEffect(() => {
    const handler = (action: InputAction) => {
      const root = dialogRef.current;
      if (!root) return;
      if (action.type === "dialog-back" || action.type === "dialog-close") {
        const active = document.activeElement;
        if (active instanceof HTMLElement && root.contains(active) && isTextEditingTarget(active)) {
          active.blur();
          return;
        }
        onClose();
        return;
      }
      const focusable = Array.from(root.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => !element.hidden && element.getClientRects().length > 0);
      if (action.type === "dialog-confirm") {
        const active = document.activeElement;
        const target = active instanceof HTMLElement && root.contains(active) ? active : focusable[0];
        if (target instanceof HTMLButtonElement) target.click();
        return;
      }
      if (action.type === "focus-move" && focusable.length > 0) {
        const currentIndex = Math.max(0, focusable.findIndex((element) => element === document.activeElement));
        const delta = action.direction === "up" || action.direction === "left" ? -1 : 1;
        focusable[(currentIndex + delta + focusable.length) % focusable.length]?.focus();
      }
    };
    controllerHandlerRef.current = handler;
    requestAnimationFrame(() => {
      const first = dialogRef.current?.querySelector<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
      );
      if (first && !dialogRef.current?.contains(document.activeElement)) first.focus();
    });
    return () => {
      if (controllerHandlerRef.current === handler) controllerHandlerRef.current = null;
    };
  }, [controllerHandlerRef, onClose]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const input = keyboardInputFromEvent(event);
      const action = resolveKeyboardAction("dialog", input, "active-dialog");
      if (!action || !shouldDispatchAction(action, input)) return;
      event.preventDefault();
      if (action.type === "deactivate-text-editing") deactivateTextEditingTarget(event.target);
      else onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return <div className="fixed inset-0 z-30 flex items-center justify-center bg-[#07100bcf] p-4"
    role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
      className={`panel max-h-[85vh] w-full ${wide ? "max-w-[640px]" : "max-w-lg"} overflow-auto p-5 shadow-2xl`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Close dialog (Esc)"
          className="subtle inline-flex items-center gap-2 text-xl">
          <span aria-hidden="true">×</span><ShortcutBadge keyboard="Esc" bindingId="dialog-close" />
        </button>
      </div>
      {children}
    </section>
  </div>;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [openPath, setOpenPath] = useState("");
  const [filter, setFilter] = useState<Filter>("unsorted");
  const [mode, setMode] = useState<Mode>("triage");
  const [publishView, setPublishView] = useState<PublishView>("ready");
  const [publishSettings, setPublishSettings] = useState<ExportSettings>({ mode: "trim_edges", startDb: "-40", stopDb: "-50" });
  // Clip edge snap points are measured once per recording, so load them once per session.
  const [snapPoints, setSnapPoints] = useState<SnapPoints | null>(null);
  const sessionPath = session?.session_path ?? null;
  useEffect(() => {
    setSnapPoints(null);
    if (!sessionPath) return;
    const controller = new AbortController();
    void api<SnapPoints>("/session/snap-points", "GET", undefined, controller.signal)
      .then(setSnapPoints)
      .catch(() => {});
    return () => controller.abort();
  }, [sessionPath]);
  // Short confirmation for actions with no other visible result, such as undo.
  const [notice, setNotice] = useState<{ id: number; text: string } | null>(null);
  const showNotice = useCallback((text: string) => setNotice({ id: Date.now(), text }), []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice((current) => current?.id === notice.id ? null : current), 3000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  const [allOrder, setAllOrder] = useState<AllOrder>("clip-asc");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleExpanded, setTitleExpanded] = useState(false);
  const [showClipMenu, setShowClipMenu] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  const [showJump, setShowJump] = useState(false);
  const [jumpDraft, setJumpDraft] = useState("");
  const [showMerge, setShowMerge] = useState(false);
  const [removeIndexes, setRemoveIndexes] = useState<number[]>([]);
  const [showDetailMobile, setShowDetailMobile] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsAtController, setSettingsAtController] = useState(false);
  const [showStorageConfirm, setShowStorageConfirm] = useState(false);
  // The clip source Start over is waiting to confirm, and how it went.
  const [startOverSource, setStartOverSource] = useState<ClipSource | null>(null);
  // The "Complete this review set?" dialog, and the recording whose prompt was answered with "Not yet".
  const [showCompleteReviewSet, setShowCompleteReviewSet] = useState(false);
  const [reviewSetPromptDismissed, setReviewSetPromptDismissed] = useState<string | null>(null);
  const [completingReviewSet, setCompletingReviewSet] = useState(false);
  const [startingReviewSet, setStartingReviewSet] = useState(false);
  const [reviewSetError, setReviewSetError] = useState("");
  // A review set asked for before Likely keep scores were final; it starts as soon as measuring finishes.
  const [pendingReviewSet, setPendingReviewSet] = useState<{ audio: string; size: number } | null>(null);
  const [startOverBusy, setStartOverBusy] = useState(false);
  const [startOverMessage, setStartOverMessage] = useState("");
  const [startOverError, setStartOverError] = useState("");
  const [showGamepadMapping, setShowGamepadMapping] = useState(false);
  const [clipDirDraft, setClipDirDraft] = useState("");
  const [storageMessage, setStorageMessage] = useState("");
  // Storage failures are shown inside Settings, apart from clip-save status (#26).
  const [storageError, setStorageError] = useState("");
  const [storageBusy, setStorageBusy] = useState(false);
  const [settings, setSettings] = useState<AppSettings>(loadSettings);
  const [inputType, setInputType] = useState<DisplayInputType>("keyboard");
  // Which input made the last decision, for the review log; gamepad actions also arrive as dispatches.
  const lastInputSourceRef = useRef<"keyboard" | "gamepad" | "pointer">("keyboard");
  const [gamepadBindingConfig, setGamepadBindingConfig] = useState<GamepadBindingConfig>(loadGamepadBindingConfig);
  const [gamepadActionRequest, setGamepadActionRequest] = useState<GamepadActionRequest | null>(null);
  const [gamepadStatus, setGamepadStatus] = useState<GamepadStatus>(() => initialGamepadStatus(
    typeof navigator !== "undefined" && typeof navigator.getGamepads === "function",
  ));
  const [leadingSilenceJob, setLeadingSilenceJob] = useState<LeadingSilenceJob | null>(null);
  const [clipFeaturesJob, setClipFeaturesJob] = useState<ClipFeaturesJob | null>(null);
  const [clipFeaturesAttempt, setClipFeaturesAttempt] = useState(0);
  const [clipTranscriptionJob, setClipTranscriptionJob] = useState<ClipTranscriptionJob | null>(null);
  const [dismissedClipTranscriptionId, setDismissedClipTranscriptionId] = useState<string | null>(null);
  const [dismissedDetectionJobId, setDismissedDetectionJobId] = useState<string | null>(null);
  const autoDetectionRequest = useRef<string | null>(null);
  const loadedDetectionJob = useRef<string | null>(null);
  const loadedDetectionAdjustment = useRef<{ id: string; adjusted: number } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const gamepadMappingButtonRef = useRef<HTMLButtonElement>(null);
  const restoreGamepadMappingFocus = useRef(false);
  const clipMenuRef = useRef<HTMLDivElement>(null);
  const detailScrollRef = useRef<HTMLDivElement>(null);
  const clipListRef = useRef<HTMLDivElement>(null);
  const gamepadActionIdRef = useRef(0);
  const gamepadCaptureActiveRef = useRef(false);
  const dialogControllerHandlerRef = useRef<((action: InputAction) => void) | null>(null);
  const gamepadDispatchRef = useRef<{
    dispatch: (action: InputAction) => void;
    availability: InputAvailability;
  } | null>(null);
  const gamepadBindingConfigRef = useRef(gamepadBindingConfig);
  const gamepadRepeatDelayRef = useRef(settings.gamepadRepeatDelayMs);
  gamepadBindingConfigRef.current = gamepadBindingConfig;
  gamepadRepeatDelayRef.current = settings.gamepadRepeatDelayMs;
  const configuredGamepadBindings = useMemo(() => bindingsForGamepadConfig(gamepadBindingConfig), [gamepadBindingConfig]);
  const setGamepadCaptureActive = useCallback((active: boolean) => {
    gamepadCaptureActiveRef.current = active;
  }, []);

  useEffect(() => installCompositionTracking(), []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!["Shift", "Control", "Alt", "Meta", "CapsLock", "NumLock", "ScrollLock"].includes(event.key)) {
        setInputType("keyboard");
        lastInputSourceRef.current = "keyboard";
      }
    }
    function onInput() { setInputType("keyboard"); }
    function onPointerDown() { lastInputSourceRef.current = "pointer"; }
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("input", onInput, true);
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("input", onInput, true);
      window.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings)); }
    catch { /* Settings still apply for this browser session. */ }
  }, [settings]);

  useEffect(() => {
    saveGamepadBindingConfig(gamepadBindingConfig);
  }, [gamepadBindingConfig]);

  useEffect(() => {
    if (showSettings && session) {
      setClipDirDraft(session.clip_dir);
      setStorageMessage("");
      setStorageError("");
    }
  }, [showSettings, session?.audio]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await bootstrap();
        const data = await api<Session>("/session");
        if (alive) setSession(data);
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (alive) setInitializing(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!session?.audio) return;
    const saved = localStorage.getItem(`jipandan-review:${session.audio}`);
    if (saved) {
      try {
        const preferences = JSON.parse(saved) as {
          filter?: Filter; selectedId?: string;
          allOrder?: AllOrder; mode?: Mode;
        };
        setMode(preferences.mode === "polish" || preferences.mode === "publish" ? preferences.mode : "triage");
        if (preferences.filter && filters.some((item) => item.key === preferences.filter)) {
          setFilter(preferences.filter);
        } else if (session.counts.pending === 0) setFilter("group1");
        setSelectedId(preferences.selectedId ?? null);
        if (allOrders.some((item) => item.key === preferences.allOrder)) {
          setAllOrder(preferences.allOrder!);
        }
      } catch {
        if (session.counts.pending === 0) setFilter("group1");
      }
    } else {
      // New sessions start in Triage, and Polish lists them in Likely keep order by default.
      setMode("triage");
      setAllOrder("likely-desc");
      if (session.counts.pending === 0) setFilter("group1");
    }
  }, [session?.audio]);

  useEffect(() => {
    if (!session?.audio) return;
    localStorage.setItem(`jipandan-review:${session.audio}`, JSON.stringify({
      filter, selectedId, allOrder, mode,
    }));
  }, [session?.audio, filter, selectedId, allOrder, mode]);

  useEffect(() => {
    if (!settings.detectLeadingSilence || !session?.audio || session.needs_transcription ||
        session.revision === null || session.leading_silence_detection_complete ||
        leadingSilenceJob?.state === "queued" || leadingSilenceJob?.state === "running") return;
    const requestKey = `${session.audio}:${session.revision}`;
    if (autoDetectionRequest.current === requestKey) return;
    autoDetectionRequest.current = requestKey;
    let active = true;
    void api<LeadingSilenceJob>("/session/leading-silence-detection", "POST")
      .then((job) => { if (active) setLeadingSilenceJob(job); })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => { active = false; };
  }, [settings.detectLeadingSilence, session?.audio, session?.needs_transcription,
    session?.revision, session?.leading_silence_detection_complete, leadingSilenceJob?.state]);

  useEffect(() => {
    if (!session?.audio || session.needs_transcription) {
      setLeadingSilenceJob(null);
      return;
    }
    let active = true;
    let timer: number | null = null;
    async function poll() {
      try {
        const job = await api<LeadingSilenceJob | null>("/session/leading-silence-detection");
        if (!active) return;
        setLeadingSilenceJob(job);
        if (job?.state === "running" && job.adjusted > 0 &&
            (loadedDetectionAdjustment.current?.id !== job.id ||
             loadedDetectionAdjustment.current.adjusted < job.adjusted)) {
          const latest = await api<Session>("/session");
          if (active) {
            setSession(latest);
            loadedDetectionAdjustment.current = { id: job.id, adjusted: job.adjusted };
          }
        }
        if (job?.state === "completed" && loadedDetectionJob.current !== job.id) {
          const latest = await api<Session>("/session");
          if (active) {
            setSession(latest);
            loadedDetectionJob.current = job.id;
          }
        }
        if (job?.state === "queued" || job?.state === "running") {
          timer = window.setTimeout(() => { void poll(); }, 750);
        }
      } catch {
        if (active) timer = window.setTimeout(() => { void poll(); }, 1500);
      }
    }
    void poll();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session?.audio, session?.needs_transcription, leadingSilenceJob?.id, leadingSilenceJob?.state]);

  useEffect(() => {
    setClipFeaturesJob(null);
    if (!session?.audio || session.needs_transcription || session.clip_features_complete) return;
    let active = true;
    let timer: number | null = null;
    // Starting is idempotent on the server: a second request returns the running job.
    async function poll(start: boolean) {
      try {
        const job = start
          ? await api<ClipFeaturesJob>("/session/clip-features", "POST")
          : await api<ClipFeaturesJob | null>("/session/clip-features");
        if (!active) return;
        setClipFeaturesJob(job);
        if (job?.state === "queued" || job?.state === "running") {
          timer = window.setTimeout(() => { void poll(false); }, 1000);
        } else if (job?.state === "completed") {
          const latest = await api<Session>("/session");
          if (active) setSession(latest);
        }
      } catch (cause) {
        if (active) setClipFeaturesJob({
          id: "request", state: "failed", progress: 0, total: 0,
          error: cause instanceof Error ? cause.message : String(cause),
        });
      }
    }
    void poll(true);
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session?.audio, session?.needs_transcription, session?.clip_features_complete, clipFeaturesAttempt]);

  useEffect(() => {
    if (!session?.audio || session.needs_transcription) {
      setClipTranscriptionJob(null);
      return;
    }
    let active = true;
    let timer: number | null = null;
    let loadedProgress: number | null = null;
    async function poll() {
      try {
        const job = await api<ClipTranscriptionJob | null>("/session/clip-transcription");
        if (!active) return;
        setClipTranscriptionJob(job);
        // Suggestions arrive outside the session revision, so reload when results land.
        if (job && loadedProgress !== null && job.progress !== loadedProgress) {
          const latest = await api<Session>("/session");
          if (active) setSession(latest);
        }
        loadedProgress = job?.progress ?? null;
        if (job?.state === "queued" || job?.state === "running") {
          timer = window.setTimeout(() => { void poll(); }, 1000);
        }
      } catch {
        if (active) timer = window.setTimeout(() => { void poll(); }, 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session?.audio, session?.needs_transcription, clipTranscriptionJob?.id]);

  const startClipTranscription = useCallback(async (clipIds: string[]) => {
    if (!clipIds.length) return;
    setError("");
    try {
      setClipTranscriptionJob(await api<ClipTranscriptionJob>("/session/clip-transcription", "POST", { clip_ids: clipIds }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const cancelClipTranscription = useCallback(async () => {
    try {
      setClipTranscriptionJob(await api<ClipTranscriptionJob | null>("/session/clip-transcription/cancel", "POST"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const exploreSeed = session?.srt_fingerprint ?? null;
  // While a review set is open, every stage, list, and count covers only its clips.
  const reviewSetOpen = isReviewSetOpen(session?.review_set);
  const scopedCandidates = useMemo(() => scopeClips(session?.candidates ?? [], reviewSetOpen),
    [session?.candidates, reviewSetOpen]);
  const scopedCounts = useMemo(() => countStatuses(scopedCandidates), [scopedCandidates]);
  // Once every set clip is exported or rejected, ask whether to complete the set.
  const reviewSetProcessed = reviewSetOpen && isProcessed(scopedCandidates);
  useEffect(() => {
    if (reviewSetProcessed && reviewSetPromptDismissed !== session?.audio) setShowCompleteReviewSet(true);
  }, [reviewSetProcessed, reviewSetPromptDismissed, session?.audio]);
  // Triage works through the Unsorted queue in Likely keep order; Publish through Ready in clip order.
  // An open review set replaces both, and Polish's order, with its own shuffled order.
  const activeFilter: Filter = mode === "triage" ? "unsorted" : mode === "publish" ? "group2" : filter;
  const activeQuery = mode === "polish" ? query : "";
  const activeOrder: Order = reviewSetOpen ? "review-set"
    : mode === "triage" ? "likely-desc" : mode === "publish" ? "clip-asc" : allOrder;
  // Scores shift while clips are still being measured, so hold clip order until they settle.
  const likelyKeepPending = activeOrder === "likely-desc" && Boolean(session && !session.clip_features_complete);
  const effectiveOrder: Order = likelyKeepPending ? "clip-asc" : activeOrder;
  const reviewSetSeed = session?.review_set?.seed ?? "";
  const visible = useMemo(() => {
    const clips = mode === "publish" ? publishClips(scopedCandidates, publishView)
      : visibleClips(scopedCandidates, activeFilter, activeQuery);
    if (effectiveOrder === "review-set") return orderReviewSet(clips, reviewSetSeed);
    if (mode === "publish") return clips;
    const compareClipId = (a: Clip, b: Clip) => a.index - b.index || a.suffix - b.suffix;
    if (effectiveOrder === "likely-desc") return orderByLikelyKeep(clips, exploreSeed, settings.exploreRanking, compareClipId);
    return clips.sort((a, b) => {
      if (effectiveOrder === "clip-desc") return compareClipId(b, a);
      if (effectiveOrder === "start-asc") return a.start_ms - b.start_ms || compareClipId(a, b);
      if (effectiveOrder === "start-desc") return b.start_ms - a.start_ms || compareClipId(a, b);
      if (effectiveOrder === "title-asc") return a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" }) || compareClipId(a, b);
      return compareClipId(a, b);
    });
  }, [scopedCandidates, reviewSetSeed, activeFilter, activeQuery, effectiveOrder, exploreSeed, settings.exploreRanking, mode, publishView]);
  const effectiveSelectedId = visible.some((clip) => clip.clip_id === selectedId)
    ? selectedId : (visible[0]?.clip_id ?? null);
  const selected = session?.candidates.find((clip) => clip.clip_id === effectiveSelectedId) ?? null;
  const selectedPosition = visible.findIndex((clip) => clip.clip_id === effectiveSelectedId);
  const triageUpNext = mode === "triage" && selectedPosition >= 0
    ? visible.slice(selectedPosition, selectedPosition + 6) : [];

  // Where a clip sits in the current ranking, recorded with each decision in the review log.
  const rankingContext = useCallback((clip: Clip) => {
    const rank = visible.findIndex((item) => item.clip_id === clip.clip_id) + 1;
    return {
      source: lastInputSourceRef.current, order: effectiveOrder, filter: mode === "polish" ? activeFilter : mode,
      rank: rank || undefined, score: clip.likely_keep ?? undefined,
      explore: reviewSetOpen ? clip.review_set === "random"
        : effectiveOrder === "likely-desc" && settings.exploreRanking && exploreSeed !== null
          && isExploreClip(exploreSeed, clip.clip_id),
      score_version: session?.likely_keep_version,
      // "top" or "random" inside an open set; "outside" for clips reviewed beyond a session's set.
      review_set: clip.review_set ?? (session?.review_set ? "outside" : undefined),
    };
  }, [visible, effectiveOrder, activeFilter, mode, settings.exploreRanking, exploreSeed, session?.likely_keep_version,
    reviewSetOpen, session?.review_set]);

  // A "view" is logged once a clip has been on screen for VIEW_MIN_MS, with how often it was played.
  // It ends when the clip changes, the page is hidden or loses focus, or input stops for VIEW_IDLE_MS.
  const viewRef = useRef<OpenView | null>(null);
  const pendingViewsRef = useRef<object[]>([]);
  const flushViews = useCallback((keepalive = false) => {
    const events = pendingViewsRef.current.splice(0);
    if (events.length) void sendReviewEvents(events, keepalive);
  }, []);
  // Send finished views first so the breakdown includes them.
  const loadStageTimes = useCallback(async () => {
    const events = pendingViewsRef.current.splice(0);
    if (events.length) await sendReviewEvents(events);
    return api<StageTimes>("/session/stage-times");
  }, []);
  const autoplayRef = useRef(settings.autoplayClips);
  autoplayRef.current = settings.autoplayClips;
  const closeView = useCallback((reason: ViewEndReason) => {
    const view = viewRef.current;
    viewRef.current = null;
    if (!view) return;
    const event = viewEvent(view, Date.now(), reason, autoplayRef.current);
    if (event) pendingViewsRef.current.push(event);
  }, []);
  const reviewingClip = session?.audio && !session.needs_transcription ? selected : null;
  const startViewRef = useRef<() => void>(() => {});
  startViewRef.current = () => {
    const now = Date.now();
    viewRef.current = reviewingClip && session?.audio
      ? { audio: session.audio, clipId: reviewingClip.clip_id, started: now, lastActive: now, plays: 0,
          context: rankingContext(reviewingClip) }
      : null;
  };
  // Input or playback keeps a view going, or starts a new one after it ended for being idle.
  const markViewActivityRef = useRef<() => void>(() => {});
  markViewActivityRef.current = () => {
    if (viewRef.current) viewRef.current.lastActive = Date.now();
    else if (document.visibilityState === "visible" && document.hasFocus()) startViewRef.current();
  };
  const countViewPlayback = useCallback(() => {
    markViewActivityRef.current();
    if (viewRef.current) viewRef.current.plays += 1;
  }, []);
  useEffect(() => {
    closeView("clip_change");
    startViewRef.current();
  }, [reviewingClip?.clip_id, session?.audio, closeView]);
  useEffect(() => {
    const flushTimer = window.setInterval(() => flushViews(), VIEW_FLUSH_MS);
    const idleTimer = window.setInterval(() => {
      if (viewRef.current && isIdle(viewRef.current, Date.now())) closeView("idle");
    }, VIEW_IDLE_CHECK_MS);
    function onVisibility() {
      if (document.visibilityState === "hidden") {
        closeView("hidden");
        flushViews(true);
      } else if (!viewRef.current) startViewRef.current();
    }
    function onBlur() { closeView("blur"); }
    function onFocus() { if (!viewRef.current && document.visibilityState === "visible") startViewRef.current(); }
    function onActivity() { markViewActivityRef.current(); }
    function onPageHide() { closeView("hidden"); flushViews(true); }
    const activityEvents = ["keydown", "pointerdown", "pointermove", "wheel"] as const;
    for (const type of activityEvents) window.addEventListener(type, onActivity, { capture: true, passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.clearInterval(flushTimer);
      window.clearInterval(idleTimer);
      for (const type of activityEvents) window.removeEventListener(type, onActivity, { capture: true });
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pagehide", onPageHide);
      closeView("hidden");
      flushViews(true);
    };
  }, [closeView, flushViews]);
  const nextVisibleClipId = visible[selectedPosition + 1]?.clip_id ?? null;
  const hasMergeChanges = Boolean(session?.merge_preview && (
    session.merge_preview.added.length || session.merge_preview.removed.length ||
    session.merge_preview.timing_changed.length || session.merge_preview.text_changed.length ||
    session.merge_preview.file_changed
  ));

  useEffect(() => {
    detailScrollRef.current?.scrollTo(0, 0);
    setTitleExpanded(false);
  }, [effectiveSelectedId]);

  // Keep the selected row visible when keyboard/gamepad navigation or a reorder moves it (#29).
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      clipListRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    });
    return () => cancelAnimationFrame(frame);
  }, [effectiveSelectedId, effectiveOrder, filter]);

  useEffect(() => { setShowExportModal(false); }, [session?.audio]);

  const clipTranscriptionRunning = clipTranscriptionJob?.state === "queued" || clipTranscriptionJob?.state === "running";
  const group1SuggestionCount = useMemo(() => scopedCandidates
    .filter((clip) => clip.status === "group1" && clip.suggested_title).length, [scopedCandidates]);

  // Export all runs in the browser: render each Ready clip with Publish's settings, then save it.
  const [exportAllRun, setExportAllRun] = useState<ExportAllRun | null>(null);
  const exportAllCancelled = useRef(false);
  const exportAllRunning = exportAllRun?.state === "running";
  const sessionRevisionRef = useRef<number | null>(null);
  sessionRevisionRef.current = session?.revision ?? null;
  const exportAllThresholds = publishSettings.mode === "as_is" ? { start: -40, stop: -50 }
    : { start: Number(publishSettings.startDb), stop: Number(publishSettings.stopDb) };
  const exportAllSettingsValid = publishSettings.mode === "as_is" || (
    publishSettings.startDb.trim() !== "" && publishSettings.stopDb.trim() !== "" &&
    [exportAllThresholds.start, exportAllThresholds.stop].every((value) => Number.isFinite(value) && value >= -90 && value <= -5));

  const startExportAll = useCallback(async () => {
    if (!session || exportAllRunning) return;
    const clips = publishClips(scopedCandidates, "ready");
    if (!clips.length) return;
    const mode = publishSettings.mode;
    const { start, stop } = exportAllThresholds;
    exportAllCancelled.current = false;
    setError("");
    const run: ExportAllRun = { state: "running", total: clips.length, done: 0, failed: [] };
    setExportAllRun({ ...run });
    for (const clip of clips) {
      if (exportAllCancelled.current) { setExportAllRun({ ...run, state: "cancelled" }); return; }
      try {
        let job = await api<PreviewJob>("/previews", "POST", {
          clip_id: clip.clip_id, expected_revision: sessionRevisionRef.current, mode,
          start_threshold_db: start, stop_threshold_db: stop, title: clip.title.trim(),
        });
        while (job.state === "queued" || job.state === "running") {
          await new Promise((resolve) => window.setTimeout(resolve, 700));
          job = await api<PreviewJob>(`/previews/${job.id}`);
        }
        if (job.state === "completed") {
          const next = await api<Session>("/exports", "POST", {
            preview_id: job.id, expected_revision: sessionRevisionRef.current, context: rankingContext(clip),
          });
          sessionRevisionRef.current = next.revision;
          setSession(next);
        } else {
          run.failed = [...run.failed, clip.clip_id];
        }
      } catch (cause) {
        const failure = cause as Error & { status?: number; session?: Session };
        // Another edit changed the session; stop rather than export clips the owner may have changed.
        if (failure.status === 409) {
          if (failure.session) setSession(failure.session);
          setExportAllRun({ ...run, state: "failed", error: failure.message });
          return;
        }
        run.failed = [...run.failed, clip.clip_id];
      }
      run.done += 1;
      setExportAllRun({ ...run });
    }
    setExportAllRun({ ...run, state: "completed" });
  }, [session, scopedCandidates, exportAllRunning, publishSettings.mode, exportAllThresholds.start, exportAllThresholds.stop, rankingContext]);

  const mutate = useCallback(async <T extends Session | SessionDelta>(work: () => Promise<T>) => {
    setBusy(true);
    setSaveState("saving");
    setError("");
    try {
      const next = await work();
      // Edits return a delta of the changed clips; other requests return the full session.
      if ("delta" in next) setSession((current) => current ? applySessionDelta(current, next) : current);
      else setSession(next);
      setSaveState("saved");
      return next;
    } catch (cause) {
      const failure = cause as Error & { status?: number; session?: Session };
      if (failure.status === 409 && failure.session) setSession(failure.session);
      setError(failure.message);
      setSaveState("failed");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const dismissTitleSuggestion = useCallback((clipId: string) => {
    void mutate(() => api<Session>(`/clips/${encodeURIComponent(clipId)}/suggested-title`, "DELETE"));
  }, [mutate]);

  const patchSelected = useCallback((change: Record<string, unknown>) => {
    if (!session || session.revision === null || !effectiveSelectedId) return;
    let nextSelection = effectiveSelectedId;
    if (selected && typeof change.status === "string") {
      const changed = { ...selected, status: change.status as Status };
      if (visibleClips([changed], activeFilter, activeQuery).length === 0) {
        nextSelection = visible[selectedPosition + 1]?.clip_id ??
          visible[selectedPosition - 1]?.clip_id ?? effectiveSelectedId;
      }
    }
    void mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(effectiveSelectedId)}?delta=true`, "PATCH", {
      expected_revision: session.revision, ...change, context: selected ? rankingContext(selected) : undefined,
    })).then((next) => { if (next) setSelectedId(nextSelection); });
  }, [session, effectiveSelectedId, selected, activeFilter, activeQuery,
    visible, selectedPosition, mutate, rankingContext]);

  const moveSelection = useCallback((delta: number) => {
    if (!visible.length) return;
    const position = Math.max(0, Math.min(visible.length - 1, selectedPosition + delta));
    setSelectedId(visible[position].clip_id);
    setShowDetailMobile(false);
  }, [visible, selectedPosition]);

  const activeDialog = showSettings || showStorageConfirm || startOverSource !== null || showCompleteReviewSet || showHelp || showJump || showMerge || showExportModal;
  const reviewContext = getInputContext({ activeDialog, textEditing: editingTitle });

  const undo = useCallback(() => {
    if (!session || session.revision === null) return;
    const before = new Map(session.candidates.map((clip) => [clip.clip_id, clip.status]));
    void mutate(() => api<SessionDelta>("/session/undo?delta=true", "POST", {
      expected_revision: session.revision, context: { source: lastInputSourceRef.current },
    })).then((delta) => {
      if (!delta) return;
      const restored = delta.clips.filter((clip) => before.get(clip.clip_id) !== clip.status);
      const only = restored.length === 1 ? restored[0] : null;
      const touched = [...delta.clips.map((clip) => clip.clip_id), ...delta.removed];
      showNotice(only ? `Undone: #${only.clip_id} is back in ${statusLabels[only.status]}`
        : touched.length === 1 ? `Undone: change to #${touched[0]}`
          : `Undone: ${touched.length} clips restored`);
      // In Triage, bring a clip that returned to the queue back on screen to decide again.
      if (only && only.status === "pending") setSelectedId(only.clip_id);
    });
  }, [session, mutate, showNotice]);

  const duplicateSelected = useCallback(() => {
    if (!session || session.revision === null || !effectiveSelectedId) return;
    void mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(effectiveSelectedId)}/duplicate?delta=true`,
      "POST", { expected_revision: session.revision, context: selected ? rankingContext(selected) : undefined },
    )).then((next) => {
      if (next?.created_clip_id) setSelectedId(next.created_clip_id);
    });
  }, [session, effectiveSelectedId, selected, mutate, rankingContext]);

  const dispatchReviewAction = useCallback((action: InputAction) => {
    if (!isActionAvailable(action, {
      context: reviewContext,
      busy,
      hasSelection: Boolean(selected),
      canMutate: Boolean(session && session.revision !== null && !busy),
      canUndo: Boolean(session?.can_undo && session.revision !== null),
      canDuplicate: Boolean(session && session.revision !== null && effectiveSelectedId),
    })) return;
    switch (action.type) {
      case "navigate":
        moveSelection(action.direction === "next" ? 1 : -1);
        break;
      case "classify":
        patchSelected({ status: action.status });
        break;
      case "set-status":
        patchSelected({ status: action.status });
        break;
      case "undo":
        undo();
        break;
      case "duplicate":
        duplicateSelected();
        break;
      case "rename":
        if (selected) { setTitleDraft(selected.title); setEditingTitle(true); }
        break;
      case "jump":
        setShowJump(true);
        break;
      case "focus-search":
        searchRef.current?.focus();
        break;
      case "show-help":
        setShowHelp(true);
        break;
      case "open-export":
        setShowExportModal(true);
        break;
      default:
        break;
    }
  }, [reviewContext, busy, selected, session, effectiveSelectedId, moveSelection, patchSelected,
    undo, duplicateSelected]);

  gamepadDispatchRef.current = {
    dispatch: (action) => {
      if (action.type === "focus-move" || action.type === "dialog-confirm" || action.type === "dialog-back" || action.type === "dialog-close") {
        dialogControllerHandlerRef.current?.(action);
      } else if ((action.type === "playback" || action.type === "nudge" || action.type === "nudge-selected" || action.type === "select-boundary" ||
          action.type === "snap" || action.type === "snap-selected" ||
          action.type === "export" || action.type === "export-mode" || action.type === "reveal-export") &&
          (effectiveSelectedId || reviewContext === "active-dialog")) {
        gamepadActionIdRef.current += 1;
        setGamepadActionRequest({ id: gamepadActionIdRef.current, clipId: effectiveSelectedId ?? undefined, action });
      } else {
        dispatchReviewAction(action);
      }
    },
    availability: {
      context: reviewContext === "review" && mode === "publish" ? "publish" : reviewContext,
      busy,
      hasSelection: Boolean(selected),
      canMutate: Boolean(session && session.revision !== null && !busy),
      canUndo: Boolean(session?.can_undo && session.revision !== null),
      canDuplicate: Boolean(session && session.revision !== null && effectiveSelectedId),
    },
  };

  useEffect(() => {
    const hasGamepadApi = typeof navigator !== "undefined" && typeof navigator.getGamepads === "function";
    const adapter = createGamepadAdapter({
      getGamepads: hasGamepadApi ? () => navigator.getGamepads() : undefined,
      getBindings: () => gamepadDispatchRef.current?.availability.context === "publish"
        ? publishGamepadBindings(gamepadBindingConfigRef.current) : bindingsForGamepadConfig(gamepadBindingConfigRef.current),
      getRepeatDelayMs: () => gamepadRepeatDelayRef.current,
      isInputSuppressed: () => gamepadCaptureActiveRef.current,
      getContext: () => gamepadDispatchRef.current?.availability.context ?? "review",
      onAction: (action) => {
        markViewActivityRef.current();
        const current = gamepadDispatchRef.current;
        if (!current) return;
        current.dispatch(action);
      },
      onStatusChange: setGamepadStatus,
      onInputTypeChange: (type) => {
        setInputType(type);
        if (type === "xbox") lastInputSourceRef.current = "gamepad";
      },
    });
    adapter.start();
    return () => {
      adapter.stop();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const input = keyboardInputFromEvent(event);
      const action = resolveKeyboardAction("review", input, reviewContext);
      if (!action || !shouldDispatchAction(action, input)) return;
      if (action.type === "deactivate-text-editing") {
        event.preventDefault();
        deactivateTextEditingTarget(event.target);
        return;
      }
      if (!isActionAvailable(action, {
        context: reviewContext,
        busy,
        hasSelection: Boolean(selected),
        canMutate: Boolean(session && session.revision !== null && !busy),
        canUndo: Boolean(session?.can_undo && session.revision !== null),
        canDuplicate: Boolean(session && session.revision !== null && effectiveSelectedId),
      })) return;
      // Publish shows the export panel itself: E picks the Trim edges mode there, and the
      // title is edited in its export title field rather than Polish's rename box.
      if (mode === "publish" && (action.type === "open-export" || action.type === "rename")) return;
      event.preventDefault();
      dispatchReviewAction(action);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [reviewContext, busy, selected, session, effectiveSelectedId, dispatchReviewAction, mode]);

  useEffect(() => { if (editingTitle) titleRef.current?.focus(); }, [editingTitle]);

  useEffect(() => {
    if (!showClipMenu) return;
    function closeMenu(event: MouseEvent) {
      if (!clipMenuRef.current?.contains(event.target as Node)) setShowClipMenu(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); setShowClipMenu(false); }
    }
    document.addEventListener("mousedown", closeMenu);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeMenu);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [showClipMenu]);

  useEffect(() => {
    setShowClipMenu(false);
    if (!effectiveSelectedId) setShowDetailMobile(false);
  }, [effectiveSelectedId]);

  async function openAudio(event: React.FormEvent) {
    event.preventDefault();
    if (!openPath.trim()) return;
    const next = await mutate(() => api<Session>("/session/open", "POST", { path: openPath.trim() }));
    if (next) {
      setLeadingSilenceJob(null); setDismissedDetectionJobId(null); loadedDetectionAdjustment.current = null;
      autoDetectionRequest.current = null; loadedDetectionJob.current = null;
      setQuery(""); setSelectedId(null); setFilter(next.counts.pending > 0 ? "unsorted" : "group1");
    }
  }

  async function openPickedAudio(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const next = await mutate(() => uploadAudio(file));
    if (next) {
      setLeadingSilenceJob(null); setDismissedDetectionJobId(null); loadedDetectionAdjustment.current = null;
      autoDetectionRequest.current = null; loadedDetectionJob.current = null;
      setQuery(""); setSelectedId(null); setFilter("unsorted");
    }
    event.target.value = "";
  }

  async function saveTitle() {
    if (!selected || !titleDraft.trim()) return;
    if (titleDraft.trim() !== selected.title && session?.revision !== null) {
      const next = await mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(selected.clip_id)}?delta=true`, "PATCH", {
        expected_revision: session!.revision, title: titleDraft.trim(), context: rankingContext(selected),
      }));
      if (!next) return;
    }
    setEditingTitle(false);
  }

  function jumpToIndex() {
    const requested = Number(jumpDraft.trim());
    if (!Number.isInteger(requested) || requested < 1) return;
    const target = visible.find((clip) => clip.index === requested) ??
      visible.reduce<Clip | null>((closest, clip) =>
        !closest || Math.abs(clip.index - requested) < Math.abs(closest.index - requested) ? clip : closest, null);
    if (target) {
      setSelectedId(target.clip_id);
      requestAnimationFrame(() => {
        clipListRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
          ?.scrollIntoView({ block: "nearest" });
      });
    }
    setShowJump(false);
    setJumpDraft("");
  }

  async function applyMerge() {
    const preview = session?.merge_preview;
    if (!preview || session?.revision === null) return;
    const next = await mutate(() => api<Session>("/session/merge", "POST", {
      expected_revision: session!.revision,
      srt_fingerprint: preview.srt_fingerprint,
      remove_indexes: removeIndexes,
    }));
    if (next) { setShowMerge(false); setRemoveIndexes([]); }
  }

  async function applyClipDir() {
    if (!session || !clipDirDraft.trim()) return;
    setStorageBusy(true);
    setStorageMessage("");
    setStorageError("");
    try {
      const next = await api<Session>("/session/storage", "PATCH", {
        expected_revision: session.revision,
        clip_dir: clipDirDraft.trim(),
      });
      setSession(next);
      setClipDirDraft(next.clip_dir);
      setStorageMessage("Export directory updated.");
    } catch (cause) {
      const failure = cause as Error & { status?: number; session?: Session };
      if (failure.status === 409 && failure.session) setSession(failure.session);
      setStorageError(failure.message);
    } finally {
      setStorageBusy(false);
    }
  }

  async function chooseClipDir() {
    setStorageBusy(true);
    setStorageMessage("");
    setStorageError("");
    try {
      const result = await api<{ path: string | null; cancelled: boolean }>("/session/storage/pick", "POST");
      if (result.path) {
        setClipDirDraft(result.path);
        setStorageMessage("Folder selected. Review and apply to save it.");
      }
    } catch (cause) {
      setStorageError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStorageBusy(false);
    }
  }

  async function resetClipDir() {
    setStorageBusy(true);
    setStorageMessage("");
    setStorageError("");
    try {
      const result = await api<{ clip_dir: string }>("/session/storage/default");
      setClipDirDraft(result.clip_dir);
      setStorageMessage("Default path selected. Review and apply to save it.");
    } catch (cause) {
      setStorageError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStorageBusy(false);
    }
  }

  async function startReviewSet(size: number) {
    if (!session?.audio) return;
    // Picking the top clips needs every clip's final score, so wait for measuring instead of ranking on partial scores.
    if (!session.clip_features_complete) {
      setReviewSetError("");
      setPendingReviewSet({ audio: session.audio, size });
      return;
    }
    setPendingReviewSet(null);
    setStartingReviewSet(true);
    setReviewSetError("");
    try {
      const next = await api<Session>("/session/review-set", "POST", { size });
      setSession(next);
      setMode("triage");
      setSelectedId(null);
      showNotice(`Review set started: ${next.review_set?.size ?? size} clips.`);
    } catch (cause) {
      setReviewSetError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStartingReviewSet(false);
    }
  }

  const startReviewSetRef = useRef(startReviewSet);
  startReviewSetRef.current = startReviewSet;
  useEffect(() => {
    if (!pendingReviewSet) return;
    if (session?.audio !== pendingReviewSet.audio || session.review_set) setPendingReviewSet(null);
    else if (session.clip_features_complete) void startReviewSetRef.current(pendingReviewSet.size);
  }, [pendingReviewSet, session?.audio, session?.review_set, session?.clip_features_complete]);

  async function completeReviewSet() {
    setCompletingReviewSet(true);
    try {
      const next = await api<Session>("/session/review-set/complete", "POST");
      setSession(next);
      setShowCompleteReviewSet(false);
      showNotice(`Review set completed. All ${next.candidates.length} clips are shown again.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setCompletingReviewSet(false);
    }
  }

  async function startOver(source: ClipSource) {
    if (!session || session.revision === null) return;
    setStartOverSource(null);
    setStartOverBusy(true);
    setStartOverMessage("");
    setStartOverError("");
    // Views of the old session's clips must not land in the new session's review log.
    viewRef.current = null;
    pendingViewsRef.current = [];
    try {
      const next = await api<Session>("/session/start-over", "POST", {
        expected_revision: session.revision, clip_source: source,
      });
      localStorage.removeItem(`jipandan-review:${next.audio}`);
      setSession(next);
      setMode("triage");
      setFilter("unsorted");
      setSelectedId(null);
      setAllOrder("likely-desc");
      // The server stopped the old session's background jobs, so start them again for the new one, even when
      // "measuring finished" reads the same before and after (a start over while measuring was still running).
      setLeadingSilenceJob(null); setDismissedDetectionJobId(null); loadedDetectionAdjustment.current = null;
      autoDetectionRequest.current = null; loadedDetectionJob.current = null;
      setClipFeaturesAttempt((attempt) => attempt + 1);
      setPendingReviewSet(null);
      const backupName = next.start_over_backup?.split(/[\\/]/).pop();
      setStartOverMessage(`Started over. The previous session was saved beside the recording as ${backupName}.`);
    } catch (cause) {
      const failure = cause as Error & { status?: number; session?: Session };
      if (failure.status === 409 && failure.session) setSession(failure.session);
      setStartOverError(failure.message);
    } finally {
      setStartOverBusy(false);
    }
  }

  async function confirmClipDir() {
    setShowStorageConfirm(false);
    await applyClipDir();
  }

  async function retryLeadingSilenceDetection() {
    try {
      const job = await api<LeadingSilenceJob>("/session/leading-silence-detection", "POST");
      setLeadingSilenceJob(job);
      setDismissedDetectionJobId(null);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  const openGamepadMapping = useCallback(() => {
    setShowGamepadMapping(true);
  }, []);

  const closeGamepadMapping = useCallback(() => {
    restoreGamepadMappingFocus.current = true;
    setShowGamepadMapping(false);
  }, []);

  // Focus from an effect rather than an animation frame: frames never run while
  // the page is hidden, which left focus on <body> after leaving the mapping.
  useEffect(() => {
    if (showGamepadMapping || !restoreGamepadMappingFocus.current) return;
    restoreGamepadMappingFocus.current = false;
    gamepadMappingButtonRef.current?.focus();
  }, [showGamepadMapping]);

  const closeSettings = useCallback(() => {
    setShowStorageConfirm(false);
    setShowGamepadMapping(false);
    setShowSettings(false);
    requestAnimationFrame(() => settingsButtonRef.current?.focus());
  }, []);

  const reviewing = Boolean(session?.audio && !session.needs_transcription);

  if (initializing) return <main className="flex min-h-screen items-center justify-center subtle">Opening Jipandan…</main>;

  return <ShortcutDisplayProvider mode={settings.badgeMode} inputType={inputType}
    unboundBehavior={settings.unboundBadgeBehavior} bindings={mode === "publish" && reviewContext !== "active-dialog"
      ? publishGamepadBindings(gamepadBindingConfig) : configuredGamepadBindings}>
  <div className={`flex flex-col ${session?.audio && mode !== "publish" ? "h-dvh min-h-0 overflow-hidden" : "min-h-screen"}`}>
    <header className="topbar shrink-0">
      <div className="topbar-row">
        <div className="topbar-side">
          <div aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-[#b7d69d] font-extrabold text-[#1b291f]">J</div>
          <div className="min-w-0">
            <div className="font-bold">Jipandan</div>
            {/* The session and export paths are rarely needed, so they live in this tooltip. */}
            <div className="subtle truncate text-xs" title={session?.audio
              ? `Session: ${session.session_path ?? "Not created"}\nExports: ${session.clip_dir}` : undefined}>
              {session?.audio_name ?? "No audio open"}
              {reviewing && session && <> · <span className="mono">{formatDuration(session.duration_ms ?? 0)}</span>
                {!session.srt_exists && <> · <span className="text-[#ead49b]">SRT missing</span></>}
                {reviewSetOpen && session.review_set && <> · <span className="text-[#c4e7ff]"
                  title="Only the review set's clips are shown until it is completed">Review set of {session.review_set.size}</span></>}</>}
            </div>
          </div>
        </div>
        {reviewing && session && <nav className="topbar-stages" aria-label="Stage">
          <div className="seg">
            {stageItems.map(({ mode: item, label, status }) => <button key={item} type="button" className="seg-btn"
              aria-pressed={mode === item}
              onClick={() => {
                if (item === "polish" && mode !== "polish") { setFilter("group1"); setQuery(""); setSelectedId(null); }
                setEditingTitle(false); setShowClipMenu(false); setMode(item);
              }}>
              {label} <CountBadge label={`${scopedCounts[status]} ${statusLabels[status]}`}>{scopedCounts[status]}</CountBadge>
            </button>)}
          </div>
        </nav>}
        <div className="topbar-side justify-end">
          {reviewing && <span aria-live="polite" className={`mr-1 inline-flex items-center gap-1.5 text-[13px] ${
            saveState === "failed" ? "text-[#ffb3a8]" : saveState === "saving" ? "text-[#ead49b]" : "accent"}`}>
            <span aria-hidden="true" className="status-dot bg-current" />
            {saveState === "saving" ? "Saving…" : saveState === "failed" ? "Save failed" : "Saved"}
          </span>}
          {reviewing && session && <Button onClick={() => {
            dispatchReviewAction({ type: "undo" });
          }} disabled={!session.can_undo || busy} title="Undo recent change (U)" shortcut="U" shortcutId="undo">
            <UndoIcon />Undo
          </Button>}
          {!session?.needs_transcription && <Button variant="quiet" className="btn-icon"
            onClick={() => dispatchReviewAction({ type: "show-help" })}
            title="Keyboard shortcuts (?)" ariaLabel="Keyboard shortcuts (?)"><HelpIcon /></Button>}
          <Button variant="quiet" className="btn-icon" buttonRef={settingsButtonRef} title="Settings" ariaLabel="Settings" onClick={() => {
            setShowSettings(true);
            setSettingsAtController(false);
            setShowGamepadMapping(false);
            setShowHelp(false); setShowJump(false); setShowMerge(false); setShowExportModal(false);
          }}><SettingsIcon /></Button>
        </div>
      </div>
    </header>

    {notice && <div role="status" aria-live="polite"
      className="pointer-events-none fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-xl border border-[#55744b] bg-[#24372b] px-5 py-3 text-sm font-medium shadow-2xl">
      {notice.text}
    </div>}
    {error && <div role="alert" className="shrink-0 border-b border-[#a96053] bg-[#482d2a] px-5 py-3 text-sm text-[#ffe3dc]">
      {error} <button className="ml-3 underline" onClick={() => setError("")}>Dismiss</button>
    </div>}

    {leadingSilenceJob && leadingSilenceJob.id !== dismissedDetectionJobId && <div
      role="status" aria-live="polite"
      className={`shrink-0 border-b px-4 py-2 text-sm md:px-7 ${leadingSilenceJob.state === "failed" ? "border-[#a96053] bg-[#482d2a] text-[#ffe3dc]" : leadingSilenceJob.state === "completed" ? "border-[#55744b] bg-[#24372b]" : "border-[#7c6845] bg-[#3c3525]"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span>
          {leadingSilenceJob.state === "queued" || leadingSilenceJob.state === "running"
            ? <>Detecting leading silence · {leadingSilenceJob.progress} of {leadingSilenceJob.total} clips checked · {leadingSilenceJob.adjusted} adjusted so far</>
            : leadingSilenceJob.state === "completed"
              ? <>Leading silence detection complete · adjusted {leadingSilenceJob.adjusted} {leadingSilenceJob.adjusted === 1 ? "clip start" : "clip starts"}</>
              : leadingSilenceJob.state === "failed"
                ? `Leading silence detection failed: ${leadingSilenceJob.error ?? "Unknown error"}`
                : "Leading silence detection stopped because the session changed."}
        </span>
        <div className="flex items-center gap-3">
          {leadingSilenceJob.state === "failed" && <button type="button" onClick={() => void retryLeadingSilenceDetection()} className="underline">Retry</button>}
          {(leadingSilenceJob.state === "completed" || leadingSilenceJob.state === "failed" || leadingSilenceJob.state === "cancelled") &&
            <button type="button" onClick={() => setDismissedDetectionJobId(leadingSilenceJob.id)} aria-label="Dismiss detection status" className="text-lg leading-none">×</button>}
        </div>
      </div>
      {(leadingSilenceJob.state === "queued" || leadingSilenceJob.state === "running") && <div
        role="progressbar" aria-label="Leading silence detection progress"
        aria-valuemin={0} aria-valuemax={leadingSilenceJob.total} aria-valuenow={leadingSilenceJob.progress}
        className="mt-2 h-1 overflow-hidden rounded-full bg-[#17241c]">
        <div className="h-full bg-[#b7d69d] transition-[width]" style={{ width: `${leadingSilenceJob.total ? leadingSilenceJob.progress / leadingSilenceJob.total * 100 : 100}%` }} />
      </div>}
    </div>}

    {!session?.audio ? <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-5 py-12">
      <p className="accent mb-3 text-sm font-semibold uppercase tracking-[.2em]">Start a session</p>
      <h1 className="mb-3 text-4xl font-semibold tracking-tight">Open your recording</h1>
      <p className="subtle mb-8 max-w-xl">Enter a local audio path to review its SRT and saved session. The audio stays on this computer.</p>
      <form onSubmit={openAudio} className="surface rounded-2xl p-5">
        <label htmlFor="audio-path" className="mb-2 block text-sm font-medium">Local audio path</label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input id="audio-path" value={openPath} onChange={(event) => setOpenPath(event.target.value)}
            placeholder="/path/to/recording.mp3" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2 text-sm" />
          <button disabled={busy} className="rounded-lg bg-[#b7d69d] px-5 py-2 font-semibold text-[#1d2d20]">Open audio</button>
        </div>
      </form>
      <label className="surface mt-3 flex cursor-pointer items-center justify-between gap-3 rounded-xl px-5 py-4 text-sm hover:bg-[#283b30]">
        <span><strong>Choose an audio file</strong><span className="subtle mt-1 block text-xs">Copies the recording into Jipandan’s local storage.</span></span>
        <span className="accent">Browse…</span>
        <input type="file" accept=".mp3,.m4a,.wav,.flac,.ogg,.aac,audio/*" onChange={(event) => void openPickedAudio(event)} className="sr-only" disabled={busy} />
      </label>
      <p className="subtle mt-4 text-sm">You can also launch directly with <code className="accent">uv run jipandan-web /path/to/audio.mp3</code>.</p>
    </main> : <>
      {hasMergeChanges && <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[#7c6845] bg-[#3c3525] px-4 py-2 text-sm md:px-7">
        <span>The SRT changed since this session was saved. Your reviewed clips are still here.</span>
        <Button onClick={() => setShowMerge(true)}>Review SRT changes</Button>
      </div>}
      {session.needs_transcription ? <TranscriptionScreen key={session.audio} session={session}
        onReady={(next) => { setSession(next); setFilter("unsorted"); setSelectedId(null); }} />
      : mode === "triage" ? <TriageScreen clip={selected} upNext={triageUpNext} durationMs={session.duration_ms ?? 0} position={selectedPosition + 1} remaining={visible.length}
        counts={scopedCounts} hideScores={reviewSetOpen} audioSrc={audioUrl()} autoplay={settings.autoplayClips}
        active={!showExportModal && !showSettings && !showHelp && !showJump && !showMerge}
        busy={busy}
        orderNote={likelyKeepPending ? "Showing clip order until measuring finishes" : null}
        gamepadAction={gamepadActionRequest}
        onGamepadActionHandled={(id) => setGamepadActionRequest((current) => current?.id === id ? null : current)}
        onPlayback={countViewPlayback}
        onDecide={(status) => dispatchReviewAction({ type: "classify", status })}
        onNavigate={(direction) => dispatchReviewAction({ type: "navigate", direction })}
        onSelect={setSelectedId} />
      : mode === "publish" ? <StageLayout label="Publish" list={
        <Panel title="Publish" ariaLabel="Ready to publish"
          aside={<span className="subtle mono text-xs">{visible.length} {visible.length === 1 ? "clip" : "clips"}</span>} className="flex max-h-[calc(100dvh-140px)] flex-col overflow-hidden">
          <div className="border-b line p-4">
            <div className="seg seg-compact mb-1" role="group" aria-label="Publish list">
              {(["ready", "exported"] as const).map((view) => {
                const label = view === "ready" ? "Ready" : "Exported";
                const count = view === "ready" ? scopedCounts.group2 : publishClips(scopedCandidates, "exported").length;
                return <button key={view} type="button" className="seg-btn" aria-label={`${label}, ${count} ${count === 1 ? "clip" : "clips"}`}
                  aria-pressed={publishView === view} onClick={() => { setPublishView(view); setSelectedId(null); }}>
                  <span>{label}</span><span aria-hidden="true" className="mono text-[11px] font-normal leading-none opacity-75">{count}</span>
                </button>;
              })}
            </div>
            <p className="subtle text-xs">{publishView === "ready" ? `Ready clips in ${reviewSetOpen ? "review set" : "clip"} order` : "Saved files, including clips edited after export"} · J/K to move</p>
            {publishView === "ready" && scopedCounts.group2 > 0 && <div className="mt-3">
              <Button onClick={() => void startExportAll()} disabled={exportAllRunning || busy || !exportAllSettingsValid}
                title={exportAllSettingsValid ? "Export every Ready clip with its own title and the current export mode and thresholds"
                  : "Fix the export thresholds first"}>
                Export all Ready clips
              </Button>
            </div>}
            {exportAllRun && <div role="status" aria-live="polite"
              className={`mt-2 text-xs ${exportAllRun.state === "failed" || exportAllRun.failed.length ? "text-[#ffcfc4]" : "subtle"}`}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  {exportAllRunning
                    ? <>Exporting · {exportAllRun.done} of {exportAllRun.total}</>
                    : exportAllRun.state === "completed"
                      ? <>Exported {exportAllRun.total - exportAllRun.failed.length} of {exportAllRun.total} {exportAllRun.total === 1 ? "clip" : "clips"}</>
                      : exportAllRun.state === "failed"
                        ? <>Export all stopped after {exportAllRun.done} of {exportAllRun.total}: {exportAllRun.error}</>
                        : <>Export all stopped after {exportAllRun.done} of {exportAllRun.total}</>}
                  {exportAllRun.failed.length > 0 && <> · could not export {exportAllRun.failed.map((id) => `#${id}`).join(", ")}</>}
                </span>
                {exportAllRunning
                  ? <button type="button" className="underline" onClick={() => { exportAllCancelled.current = true; }}>Cancel</button>
                  : <button type="button" aria-label="Dismiss export all status" className="text-base leading-none"
                    onClick={() => setExportAllRun(null)}>×</button>}
              </div>
              {exportAllRunning && <div role="progressbar" aria-label="Export all progress"
                aria-valuemin={0} aria-valuemax={exportAllRun.total} aria-valuenow={exportAllRun.done}
                className="mt-1.5 h-1 overflow-hidden rounded-full bg-[#17241c]">
                <div className="h-full bg-[#b7d69d] transition-[width]" style={{ width: `${exportAllRun.total ? exportAllRun.done / exportAllRun.total * 100 : 0}%` }} />
              </div>}
            </div>}
          </div>
          <div className="panel-scroll min-h-0 flex-1 overflow-auto" role="listbox" aria-label={publishView === "ready" ? "Ready clips" : "Exported clips"}>
            {visible.length === 0 ? <p className="subtle px-4 py-6 text-sm">{publishView === "ready"
              ? "Nothing is Ready yet. Mark keepers with 2 in Triage or Polish." : "No clips have been exported yet."}</p>
              : visible.map((clip) => <button key={clip.clip_id} type="button" role="option"
                aria-selected={clip.clip_id === effectiveSelectedId} data-selected={clip.clip_id === effectiveSelectedId}
                tabIndex={clip.clip_id === effectiveSelectedId ? 0 : -1}
                onClick={() => setSelectedId(clip.clip_id)}
                className="clip-row flex w-full items-baseline gap-2 border-b border-[#29362f] px-4 py-2.5 text-left">
                <span className="subtle mono shrink-0 text-xs">#{clip.clip_id}</span>
                <span className="min-w-0 flex-1 text-sm"><span className="block truncate" title={clip.title}>{clip.title}</span>
                  {clip.last_export_path && <span className={`mt-1 block text-[11px] ${clip.export_state === "matching" ? "subtle" : "text-[#edbc97]"}`}>
                    {clip.export_state === "matching" ? "Exported" : clip.export_state === "changed" ? "Exported · changed" : "Exported · unverified"}
                  </span>}
                </span>
                <span className="subtle mono shrink-0 text-xs">{formatDuration(clip.end_ms - clip.start_ms)}</span>
              </button>)}
          </div>
        </Panel>} main={selected && session.revision !== null ? <ExportPreview key={selected.clip_id} inline clip={selected}
          heading={`Clip ${selectedPosition + 1} of ${visible.length}`}
          headingDetail={`#${selected.clip_id} · ${formatDuration(selected.end_ms - selected.start_ms)}`}
          recordingDurationMs={session.duration_ms ?? undefined}
          initialSettings={publishSettings} onSettingsChange={setPublishSettings}
          revision={session.revision} open={!showSettings && !showHelp && !showJump && !showMerge}
          nextClipId={nextVisibleClipId} controllerHandlerRef={dialogControllerHandlerRef} onClose={() => {}}
          gamepadAction={gamepadActionRequest}
          onGamepadActionHandled={(id) => setGamepadActionRequest((current) => current?.id === id ? null : current)}
          exportContext={rankingContext(selected)}
          nudgeDisabled={busy || exportAllRunning}
          onTrim={(relativeStart, relativeEnd) => {
            if (session.revision === null || busy) return;
            const start = Math.round(selected.start_ms + relativeStart);
            const end = Math.round(selected.start_ms + relativeEnd);
            if (start < 0 || end - start < 10 || (session.duration_ms !== null && end > session.duration_ms)) return;
            if (start === selected.start_ms && end === selected.end_ms) return;
            void mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(selected.clip_id)}?delta=true`, "PATCH", {
              expected_revision: session.revision, start_ms: start, end_ms: end, context: rankingContext(selected),
            }));
          }}
          onNudge={(edge, amount) => {
            if (session.revision === null) return;
            const start = edge === "start" ? selected.start_ms + amount : selected.start_ms;
            const end = edge === "end" ? selected.end_ms + amount : selected.end_ms;
            if (start < 0 || end - start < 10 || (session.duration_ms !== null && end > session.duration_ms)) return;
            void mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(selected.clip_id)}?delta=true`, "PATCH", {
              expected_revision: session.revision, start_ms: start, end_ms: end, context: rankingContext(selected),
            }));
          }}
          onPublished={(next, advance) => {
            // The exported clip leaves Ready; continue with the clip that followed it.
            setSession(next);
            setSaveState("saved");
            if (publishView === "ready" || advance) setSelectedId(nextVisibleClipId);
          }} />
          : <Panel className="flex items-center justify-center p-8 text-center">
            <p className="subtle">Select a clip to publish.</p>
          </Panel>} />
      : <StageLayout label="Polish" fill list={
        <Panel title="Polish" ariaLabel="Clip list"
          aside={<span className="subtle mono text-xs">{visible.length} {visible.length === 1 ? "clip" : "clips"}</span>}
          className={`${showDetailMobile ? "hidden min-[900px]:flex" : "flex"} min-h-0 flex-col overflow-hidden`}>
          <div className="shrink-0 border-b line p-4">
            <div className="seg seg-compact mb-1" role="group" aria-label="Status filter">
              {filters.map((item) => {
                const count = scopedCounts[item.key === "unsorted" ? "pending" : item.key];
                return <button key={item.key} type="button" onClick={() => setFilter(item.key)}
                  aria-pressed={filter === item.key} aria-label={`${item.label}, ${count} ${count === 1 ? "clip" : "clips"}`}
                  className="seg-btn">
                  <span>{item.label}</span><span aria-hidden="true" className="mono text-[11px] font-normal leading-none opacity-75">{count}</span>
                </button>;
              })}
            </div>
            <p className="subtle mb-3 text-xs">{filters.find((item) => item.key === filter)?.hint} · J/K to move</p>
            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                {/* Native search inputs clear on Escape, including IME-owned Escape presses. */}
                <input ref={searchRef} type="text" role="searchbox" value={query} onChange={(event) => setQuery(event.target.value)}
                  aria-label="Search clip titles" placeholder={`Search within ${filters.find((item) => item.key === filter)?.label}…`}
                  className="w-full rounded-lg border line bg-[#101816] px-3 py-2 pr-10 text-sm" />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2"><ShortcutBadge keyboard="/" bindingId="focus-search" /></span>
              </div>
              <Button onClick={() => setShowJump(true)} title="Jump to clip index (G)" shortcut="G" shortcutId="jump">Go to #</Button>
            </div>
            <div className="mt-3 grid gap-2">
              <label className="subtle min-w-0 text-xs">Order by
                <select value={reviewSetOpen ? "review-set" : allOrder} onChange={(event) => setAllOrder(event.target.value as AllOrder)}
                  disabled={reviewSetOpen} title={reviewSetOpen ? "A review set shows its clips in one order on every screen" : undefined}
                  aria-label="Order clips" className="mt-1 block w-full rounded-lg border line bg-[#101816] px-2.5 py-2 text-sm text-[#e7eee7] disabled:opacity-60">
                  {reviewSetOpen && <option value="review-set">Review set order</option>}
                  {allOrders.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                </select>
              </label>
            </div>
            {filter === "group1" && scopedCounts.group1 > 0 && <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button onClick={() => void startClipTranscription(
                scopedCandidates.filter((clip) => clip.status === "group1").map((clip) => clip.clip_id))}
                disabled={clipTranscriptionRunning}
                title="Run Whisper again on each Needs work clip's own audio and suggest a new title">
                Re-transcribe Needs work titles
              </Button>
              {group1SuggestionCount > 0 && <span className="subtle text-xs">{group1SuggestionCount} {group1SuggestionCount === 1 ? "suggestion" : "suggestions"} to review</span>}
            </div>}
            {clipTranscriptionJob && clipTranscriptionJob.id !== dismissedClipTranscriptionId && <div role="status" aria-live="polite"
              className={`mt-2 text-xs ${clipTranscriptionJob.state === "failed" ? "text-[#ffcfc4]" : "subtle"}`}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  {clipTranscriptionRunning
                    ? <>Re-transcribing titles · {clipTranscriptionJob.progress} of {clipTranscriptionJob.total}{clipTranscriptionJob.progress === 0 && " · loading Whisper"}</>
                    : clipTranscriptionJob.state === "completed"
                      ? <>Re-transcribed {clipTranscriptionJob.total} {clipTranscriptionJob.total === 1 ? "clip" : "clips"}</>
                      : clipTranscriptionJob.state === "failed"
                        ? <>Could not re-transcribe: {clipTranscriptionJob.error}</>
                        : <>Re-transcription stopped after {clipTranscriptionJob.progress} of {clipTranscriptionJob.total}</>}
                </span>
                {clipTranscriptionRunning
                  ? <button type="button" className="underline" onClick={() => void cancelClipTranscription()}>Cancel</button>
                  : <button type="button" aria-label="Dismiss re-transcription status" className="text-base leading-none"
                    onClick={() => setDismissedClipTranscriptionId(clipTranscriptionJob.id)}>×</button>}
              </div>
              {clipTranscriptionRunning && <div role="progressbar" aria-label="Re-transcription progress"
                aria-valuemin={0} aria-valuemax={clipTranscriptionJob.total} aria-valuenow={clipTranscriptionJob.progress}
                className="mt-1.5 h-1 overflow-hidden rounded-full bg-[#17241c]">
                <div className="h-full bg-[#b7d69d] transition-[width]" style={{ width: `${clipTranscriptionJob.total ? clipTranscriptionJob.progress / clipTranscriptionJob.total * 100 : 0}%` }} />
              </div>}
            </div>}
            {(clipFeaturesJob?.state === "queued" || clipFeaturesJob?.state === "running") &&
              <p className="subtle mt-2 text-xs" role="status">
                Measuring clips for likely keep · {clipFeaturesJob.progress.toLocaleString()} of {clipFeaturesJob.total.toLocaleString()}
                {likelyKeepPending && " · showing clip order until done"}
              </p>}
            {clipFeaturesJob?.state === "failed" && <p className="mt-2 text-xs text-[#ffcfc4]" role="status">
              Could not measure clips: {clipFeaturesJob.error}{" "}
              <button type="button" className="underline" onClick={() => setClipFeaturesAttempt((attempt) => attempt + 1)}>Retry</button>
            </p>}
          </div>
          <div ref={clipListRef} className="panel-scroll min-h-0 flex-1 overflow-auto" role="listbox" aria-label="Clips">
            {visible.length === 0 ? <p className="subtle px-5 py-8 text-sm">No clips match this view.</p> : visible.map((clip) => {
              const changed = clip.start_ms !== clip.original_start_ms || clip.end_ms !== clip.original_end_ms;
              // One tab stop for the whole list: only the selected row is focusable; J/K and arrows move (#29).
              return <button key={clip.clip_id} type="button" role="option" aria-selected={clip.clip_id === effectiveSelectedId}
                tabIndex={clip.clip_id === effectiveSelectedId ? 0 : -1}
                data-selected={clip.clip_id === effectiveSelectedId} onClick={() => { setSelectedId(clip.clip_id); setShowDetailMobile(true); }}
                className="clip-row flex w-full items-start gap-3 border-b border-[#29362f] px-4 py-3 text-left transition-colors md:px-5">
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2"><span className="subtle mono shrink-0 text-xs">#{clip.clip_id}</span>
                    <span className="truncate text-sm font-medium" title={clip.title}>{clip.title}</span></span>
                </span>
                {clip.suggested_title && <span className="clip-tag clip-tag-suggestion shrink-0" title="A re-transcribed title is waiting for review">New title</span>}
                {changed && <span className="clip-tag clip-tag-trimmed shrink-0">Trimmed</span>}
                <span className="subtle mono shrink-0 text-xs">{formatDuration(clip.end_ms - clip.start_ms)}</span>
              </button>;
            })}
          </div>
        </Panel>} main={
        <Panel ariaLabel="Clip details" title={selected ? `Clip ${selectedPosition + 1} of ${visible.length}` : undefined}
          aside={selected && <span className="subtle mono text-xs">#{selected.clip_id} · {formatDuration(selected.end_ms - selected.start_ms)}</span>}
          className={`${showDetailMobile ? "flex" : "hidden min-[900px]:flex"} min-h-0 flex-col overflow-hidden`}>
          {selected ? <>
            <div className="shrink-0 border-b line px-4 py-3 md:px-6">
              <button type="button" onClick={() => setShowDetailMobile(false)} className="accent mb-2 text-sm min-[900px]:hidden">← Back to clips</button>
              <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <StatusBadge status={selected.status} />
                  {(selected.start_ms !== selected.original_start_ms || selected.end_ms !== selected.original_end_ms)
                    && <span className="clip-tag clip-tag-trimmed">Trimmed</span>}
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  <button type="button" onClick={() => dispatchReviewAction({ type: "navigate", direction: "previous" })} disabled={selectedPosition <= 0}
                    aria-label="Previous clip (physical K key position)" title="Previous clip (physical K key position)"
                    className="btn btn-quiet">
                    <span aria-hidden="true">←</span><ShortcutBadge keyboard="K" bindingId="previous" />
                  </button>
                  <button type="button" onClick={() => dispatchReviewAction({ type: "navigate", direction: "next" })} disabled={selectedPosition >= visible.length - 1}
                    aria-label="Next clip (physical J key position)" title="Next clip (physical J key position)"
                    className="btn btn-quiet">
                    <span aria-hidden="true">→</span><ShortcutBadge keyboard="J" bindingId="next" />
                  </button>
                  <Button onClick={() => dispatchReviewAction({ type: "rename" })} disabled={busy || editingTitle}
                    title="Edit clip title (R)" shortcut="R" shortcutId="rename">Edit title</Button>
                  <Button onClick={() => dispatchReviewAction({ type: "classify", status: "rejected" })}
                    disabled={busy || editingTitle || selected.status === "rejected"}
                    title="Reject this clip (X)" shortcut="X" shortcutId="rejected">Reject</Button>
                  <Button onClick={() => dispatchReviewAction({ type: "classify", status: "group2" })}
                    disabled={busy || editingTitle || selected.status === "group2"}
                    title="Mark Ready and move it into Publish (2)" shortcut="2" shortcutId="group2" variant="primary">Ready for Publish</Button>
                  <div ref={clipMenuRef} className="relative">
                    <button type="button" onClick={() => setShowClipMenu((open) => !open)}
                      aria-label="More clip actions" aria-expanded={showClipMenu} aria-haspopup="menu" title="More clip actions"
                      className="btn btn-quiet btn-icon">…</button>
                    {showClipMenu && <div role="menu" aria-label="More clip actions"
                      className="surface absolute right-0 top-full z-20 mt-1 min-w-40 rounded-lg p-1 shadow-xl">
                      <button type="button" role="menuitem" disabled={busy} onClick={() => {
                        setShowClipMenu(false); dispatchReviewAction({ type: "open-export" });
                      }} className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm hover:bg-[#304439]">
                        Preview export <ShortcutBadge keyboard="E" bindingId="open-export" />
                      </button>
                      <button type="button" role="menuitem" disabled={busy} onClick={() => {
                        setShowClipMenu(false);
                        dispatchReviewAction({ type: "duplicate" });
                      }} className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm hover:bg-[#304439]">
                        Duplicate <ShortcutBadge keyboard="D" bindingId="duplicate" />
                      </button>
                      <button type="button" role="menuitem" disabled={clipTranscriptionRunning} onClick={() => {
                        setShowClipMenu(false);
                        void startClipTranscription([selected.clip_id]);
                      }} className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm hover:bg-[#304439] disabled:opacity-50">
                        Re-transcribe title
                      </button>
                    </div>}
                  </div>
                </div>
              </div>
              {editingTitle ? <div className="flex gap-2">
                <input ref={titleRef} value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)}
                  onKeyDown={(event) => {
                    const input = keyboardInputFromEvent(event.nativeEvent);
                    if ((input.code === "Enter" || input.code === "NumpadEnter") && !input.isComposing) {
                      event.preventDefault(); void saveTitle();
                    }
                    if (input.code === "Escape" && !input.isComposing) {
                      event.preventDefault(); setEditingTitle(false);
                    }
                  }} aria-label="Clip title" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2" />
                <Button onClick={() => void saveTitle()} disabled={busy || !titleDraft.trim()} variant="primary">Save</Button>
                <Button onClick={() => setEditingTitle(false)}>Cancel</Button>
              </div> : <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  {/* Very long transcript titles are clamped so the waveform stays in view (#27). */}
                  <h2 title={selected.title}
                    className={`break-words text-2xl font-semibold leading-snug ${titleExpanded ? "" : "line-clamp-2"}`}>{selected.title}</h2>
                  {selected.title.length > LONG_TITLE_CHARS && <button type="button" onClick={() => setTitleExpanded((open) => !open)}
                    aria-expanded={titleExpanded} className="subtle mt-1 text-xs underline">
                    {titleExpanded ? "Show less" : `Show full title (${selected.title.length} characters)`}
                  </button>}
                </div>
              </div>}
              {selected.suggested_title && !editingTitle && <div role="region" aria-label="Suggested title"
                className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-[#4f8396] bg-[#203640] px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block text-[11px] font-semibold uppercase tracking-wider text-[#9fd2e2]">Re-transcribed</span>
                  <span className="break-words text-base">{selected.suggested_title}</span>
                </span>
                <span className="flex shrink-0 gap-1.5">
                  <Button variant="primary" disabled={busy} onClick={() => patchSelected({ title: selected.suggested_title })}>Use this</Button>
                  <Button disabled={busy} onClick={() => { setTitleDraft(selected.suggested_title ?? ""); setEditingTitle(true); }}>Edit</Button>
                  <Button disabled={busy} onClick={() => dismissTitleSuggestion(selected.clip_id)}>Dismiss</Button>
                </span>
              </div>}
              {clipTranscriptionRunning && clipTranscriptionJob?.clip_ids.includes(selected.clip_id) && !selected.suggested_title &&
                <p className="subtle mt-2 text-xs" role="status">Re-transcribing this clip…</p>}
            </div>
            <div ref={detailScrollRef} className="panel-scroll min-h-0 flex-1 overflow-auto px-4 py-5 md:px-7">
              <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                <label htmlFor="clip-status" className="font-medium">Status</label>
                <span className="relative inline-flex">
                  <select id="clip-status" value={selected.status} disabled={busy}
                    onChange={(event) => dispatchReviewAction({ type: "set-status", status: event.target.value as Status })}
                    className="appearance-none rounded-lg border line bg-[#22312a] py-2 pl-3 pr-9 text-[#e7eee7] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b4e2b6]">
                    {(["group1", "group2", "rejected", "pending"] as Status[]).map((status) =>
                      <option key={status} value={status}>{statusLabels[status]}</option>)}
                    {selected.status === "exported" && <option value="exported">Exported</option>}
                  </select>
                  <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
                    className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-[#9eafa3]">
                    <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
              </div>
              {selected.last_export_path && <div className={`mb-4 rounded-lg border line px-3 py-2 text-xs ${selected.export_state === "matching" ? "subtle" : "text-[#edbc97]"}`}>
                <p>{selected.export_state === "matching" ? "Exported · matches current edits."
                  : selected.export_state === "changed" ? "Exported · changed. The saved file needs re-exporting."
                    : "Exported · unverified. Re-export to record a snapshot."}</p>
                <Button onClick={() => { setPublishView("exported"); setMode("publish"); setSelectedId(selected.clip_id); }}>
                  View saved file and re-export
                </Button>
              </div>}
              <WaveformEditor key={selected.clip_id} clip={selected}
                durationMs={session.duration_ms ?? selected.end_ms} audioSrc={audioUrl()} busy={busy}
                gamepadAction={gamepadActionRequest}
                onGamepadActionHandled={(id) => setGamepadActionRequest((current) => current?.id === id ? null : current)}
                shortcutsPaused={showHelp || showJump || showMerge || showExportModal || showSettings || editingTitle}
                detectLeadingSilence={settings.detectLeadingSilence}
                showOriginalStart={settings.showOriginalStart}
                active={!showExportModal && !showSettings}
                onPlayback={countViewPlayback}
                autoplay={settings.autoplayClips}
                snapping={settings.snapEdges}
                snapPoints={settings.snapEdges ? snapPoints : null}
                onSave={async (startMs, endMs) => {
                  if (session.revision === null) return false;
                  const next = await mutate(() => api<SessionDelta>(`/clips/${encodeURIComponent(selected.clip_id)}?delta=true`, "PATCH", {
                    expected_revision: session.revision, start_ms: startMs, end_ms: endMs,
                    context: rankingContext(selected),
                  }));
                  return Boolean(next);
                }} />
            </div>
          </> : <div className="subtle flex flex-1 items-center justify-center p-6 text-center">Select a clip to review its details.</div>}
        </Panel>} />}
      {selected && session.revision !== null && <ExportPreview key={selected.clip_id} clip={selected}
        revision={session.revision} open={showExportModal} nextClipId={nextVisibleClipId}
        exportContext={rankingContext(selected)}
        gamepadAction={gamepadActionRequest}
        onGamepadActionHandled={(id) => setGamepadActionRequest((current) => current?.id === id ? null : current)}
        controllerHandlerRef={dialogControllerHandlerRef}
        onClose={() => setShowExportModal(false)} onPublished={(next, advance) => {
          setSession(next);
          setSaveState("saved");
          if (advance && nextVisibleClipId) {
            setSelectedId(nextVisibleClipId);
          } else if (!advance) {
            setSelectedId(selected.clip_id);
            const exportedClip = next.candidates.find((clip) => clip.clip_id === selected.clip_id);
            // Exported clips are listed in Publish, so follow the clip there.
            if (exportedClip && !visibleClips([exportedClip], activeFilter, activeQuery).length) {
              setPublishView("exported");
              setMode("publish");
            }
          }
        }} />}
    </>}

    {showSettings && <Dialog title={showGamepadMapping ? "Gamepad mapping" : "Settings"} wide
      controllerHandlerRef={dialogControllerHandlerRef}
      onClose={showGamepadMapping ? closeGamepadMapping : closeSettings}>
      {showGamepadMapping
        ? <GamepadMappingScreen initialConfig={gamepadBindingConfig} status={gamepadStatus}
            onSave={(config) => { setGamepadBindingConfig(config); closeGamepadMapping(); }} onCancel={closeGamepadMapping}
            onCaptureChange={setGamepadCaptureActive} />
        : <SettingsScreen clipDir={clipDirDraft} storageEnabled={Boolean(session?.audio)}
            storageBusy={busy || storageBusy} storageMessage={storageMessage} storageError={storageError}
            onClipDirChange={(path) => { setClipDirDraft(path); setStorageError(""); }} onChooseClipDir={() => void chooseClipDir()}
            onResetClipDir={() => void resetClipDir()}
            onApplyClipDir={() => setShowStorageConfirm(true)}
            detectLeadingSilence={settings.detectLeadingSilence}
            showOriginalStart={settings.showOriginalStart}
            exploreRanking={settings.exploreRanking}
            autoplayClips={settings.autoplayClips}
            onAutoplayClipsChange={(enabled) => setSettings((current) => ({ ...current, autoplayClips: enabled }))}
            onExploreRankingChange={(enabled) => setSettings((current) => ({ ...current, exploreRanking: enabled }))}
            gamepadStatus={gamepadStatus}
            onLoadStageTimes={loadStageTimes}
            reviewSet={{
              sessionOpen: Boolean(session?.audio && !session.needs_transcription),
              scoresReady: Boolean(session?.clip_features_complete),
              size: settings.reviewSetSize, reviewSet: session?.review_set ?? null,
              busy: startingReviewSet, error: reviewSetError, onStart: (size) => void startReviewSet(size),
              waiting: pendingReviewSet?.audio === session?.audio, onCancelWaiting: () => setPendingReviewSet(null),
              measuring: clipFeaturesJob,
              onSizeChange: (size) => setSettings((current) => ({ ...current, reviewSetSize: normalizeReviewSetSize(size) })),
              onComplete: () => setShowCompleteReviewSet(true),
            }}
            startOver={{
              sources: session?.clip_sources ?? [],
              current: session?.srt?.endsWith(".candidates.srt") ? "generated" : "lines",
              busy: startOverBusy, message: startOverMessage, error: startOverError,
              onStartOver: (source) => { setStartOverMessage(""); setStartOverError(""); setStartOverSource(source); },
            }}
            gamepadRepeatDelayMs={settings.gamepadRepeatDelayMs}
            gamepadMappingButtonRef={gamepadMappingButtonRef}
            onOpenGamepadMapping={openGamepadMapping}
            focusController={settingsAtController}
            onDetectLeadingSilenceChange={(enabled) => setSettings((current) => ({ ...current, detectLeadingSilence: enabled }))}
            onShowOriginalStartChange={(enabled) => setSettings((current) => ({ ...current, showOriginalStart: enabled }))}
            snapEdges={settings.snapEdges}
            onSnapEdgesChange={(enabled) => setSettings((current) => ({ ...current, snapEdges: enabled }))}
            badgeMode={settings.badgeMode}
            unboundBadgeBehavior={settings.unboundBadgeBehavior}
            onBadgeModeChange={(badgeMode) => setSettings((current) => ({ ...current, badgeMode }))}
            onUnboundBadgeBehaviorChange={(unboundBadgeBehavior) => setSettings((current) => ({ ...current, unboundBadgeBehavior }))}
            onGamepadRepeatDelayChange={(gamepadRepeatDelayMs) => setSettings((current) => ({
              ...current,
              gamepadRepeatDelayMs: normalizeGamepadRepeatDelay(gamepadRepeatDelayMs),
            }))} />}
    </Dialog>}

    {showStorageConfirm && <Dialog title="Confirm export directory"
      controllerHandlerRef={dialogControllerHandlerRef} onClose={() => setShowStorageConfirm(false)}>
      <p className="subtle mb-3 text-sm">Use this directory for future audio exports?</p>
      <div className="surface mb-4 rounded-lg border line p-3 font-mono text-xs break-all">{clipDirDraft}</div>
      <p className="subtle mb-5 text-xs">Existing exported files will stay in their current directories.</p>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setShowStorageConfirm(false)}
          className="soft-surface rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#354b3b]">Cancel</button>
        <button type="button" disabled={busy || storageBusy || !clipDirDraft.trim()} onClick={() => void confirmClipDir()}
          className="rounded-lg bg-[#b7d69d] px-4 py-2 text-sm font-semibold text-[#1d2d20] disabled:cursor-not-allowed disabled:opacity-50">Confirm</button>
      </div>
    </Dialog>}

    {showCompleteReviewSet && session?.review_set && <Dialog title="Complete this review set?"
      controllerHandlerRef={dialogControllerHandlerRef}
      onClose={() => { setShowCompleteReviewSet(false); setReviewSetPromptDismissed(session.audio); }}>
      <p className="subtle mb-3 text-sm">{reviewSetProcessed
        ? `All ${session.review_set.size} clips in the set are exported or rejected.`
        : `${session.review_set.unprocessed} of ${session.review_set.size} clips in the set are not exported or rejected yet. Completing now ends the set early.`}</p>
      <p className="subtle mb-5 text-xs">Completing returns to regular review, showing the other {session.candidates.length - scopedCandidates.length} candidates. A session has one review set, so this cannot be undone.</p>
      <div className="flex justify-end gap-2">
        <Button onClick={() => { setShowCompleteReviewSet(false); setReviewSetPromptDismissed(session.audio); }}>Not yet</Button>
        <Button variant="primary" disabled={completingReviewSet} onClick={() => void completeReviewSet()}>Complete review set</Button>
      </div>
    </Dialog>}

    {startOverSource && <Dialog title="Start this session over?"
      controllerHandlerRef={dialogControllerHandlerRef} onClose={() => setStartOverSource(null)}>
      <p className="subtle mb-3 text-sm">A fresh session starts from <strong>{clipSourceLabels[startOverSource]}</strong>,
        with every clip back in Triage. Decisions, edits, titles, undo history, and review time are cleared.</p>
      <p className="subtle mb-5 text-xs">The current session is saved as a backup file beside the recording. Exported MP3s stay where they are.</p>
      <div className="flex justify-end gap-2">
        <Button onClick={() => setStartOverSource(null)}>Cancel</Button>
        <Button variant="danger" disabled={busy || startOverBusy} onClick={() => void startOver(startOverSource)}>Start over</Button>
      </div>
    </Dialog>}

    {showJump && <Dialog title="Jump to clip index" controllerHandlerRef={dialogControllerHandlerRef} onClose={() => setShowJump(false)}>
      <p className="subtle mb-3 text-sm">Find the requested index in the current view, or the nearest visible clip.</p>
      <form onSubmit={(event) => { event.preventDefault(); jumpToIndex(); }} className="flex gap-2">
        <input autoFocus type="number" min="1" value={jumpDraft} onChange={(event) => setJumpDraft(event.target.value)}
          aria-label="Clip index" className="min-w-0 flex-1 rounded-lg border line bg-[#101816] px-3 py-2" />
        <button className="rounded-lg bg-[#b7d69d] px-4 py-2 font-semibold text-[#1d2d20]">Go</button>
      </form>
    </Dialog>}

    {showMerge && session?.merge_preview && <Dialog title="Review SRT changes" controllerHandlerRef={dialogControllerHandlerRef} onClose={() => setShowMerge(false)}>
      <p className="subtle mb-4 text-sm">Nothing changes until you apply this merge. Saved titles, groups, and trims are kept. A backup is made before any selected removal.</p>
      <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
        <span>Added entries: {session.merge_preview.added.length}</span>
        <span>Timing changes: {session.merge_preview.timing_changed.length}</span>
        <span>Text changes: {session.merge_preview.text_changed.length}</span>
        <span>Missing entries: {session.merge_preview.removed.length}</span>
      </div>
      {session.merge_preview.removed.length > 0 && <div className="mb-5">
        <h3 className="mb-2 text-sm font-medium">Missing SRT entries · kept unless selected</h3>
        <div className="panel-scroll max-h-44 overflow-auto rounded-lg border line p-2">
          {session.merge_preview.removed.map((index) => <label key={index} className="flex items-center gap-2 px-2 py-1 text-sm">
            <input type="checkbox" checked={removeIndexes.includes(index)} onChange={(event) =>
              setRemoveIndexes((current) => event.target.checked ? [...current, index] : current.filter((item) => item !== index))} />
            Remove #{index} and its duplicates
          </label>)}
        </div>
      </div>}
      {session.merge_preview.text_change_unverified && <p className="mb-4 text-sm text-[#ead49b]">The SRT file is newer than this older session. Text may have changed, but the original text was not saved for comparison.</p>}
      {session.merge_preview.unknown_original_text_clip_ids.length > 0 && !session.merge_preview.text_change_unverified && <p className="subtle mb-4 text-xs">This older session did not store original SRT text, so text changes cannot be detected for every saved clip.</p>}
      <div className="flex justify-end gap-2"><Button onClick={() => setShowMerge(false)}>Cancel</Button>
        <Button variant="primary" onClick={() => void applyMerge()} disabled={busy}>Apply selected changes</Button></div>
    </Dialog>}

    {showHelp && <Dialog title="Keyboard shortcuts" controllerHandlerRef={dialogControllerHandlerRef} onClose={() => setShowHelp(false)}>
      <ShortcutCheatsheet config={gamepadBindingConfig} />
      <p className="subtle mt-5 text-xs">Review shortcuts pause while you type. Letter and number shortcuts follow their physical US-QWERTY key positions, so a non-QWERTY layout may show different printed characters. Enter and ⌘ Enter work in the export preview when focus is outside an editable field.</p>
      <GamepadStatusLine status={gamepadStatus} onOpenSettings={() => {
        setShowHelp(false);
        setSettingsAtController(true);
        setShowGamepadMapping(false);
        setShowSettings(true);
      }} />
    </Dialog>}
  </div>
  </ShortcutDisplayProvider>;
}
