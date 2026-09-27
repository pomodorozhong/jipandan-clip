import type { ExportMode, Status } from "./api";

export type InputSurface = "review" | "waveform" | "export" | "dialog";
export type InputContext = "review" | "active-dialog" | "text-editing" | "composition";
export type PlaybackTarget = "clip" | "candidate" | "reference";
export type ClassificationStatus = Extract<Status, "group1" | "group2" | "skipped">;
export type ShortcutSource = "keyboard" | "pointer" | "gamepad";

export type InputAction =
  | { type: "navigate"; direction: "next" | "previous" }
  | { type: "playback"; target: PlaybackTarget; mode: "replay" | "toggle" | "audition-start" | "audition-end" }
  | { type: "classify"; status: ClassificationStatus }
  | { type: "set-status"; status: Status }
  | { type: "nudge"; edge: "start" | "end"; amount: number; source: ShortcutSource }
  | { type: "select-boundary"; edge: "start" | "end" }
  | { type: "nudge-selected"; amount: number; source: "gamepad" }
  | { type: "undo" }
  | { type: "duplicate" }
  | { type: "rename" }
  | { type: "jump" }
  | { type: "focus-search" }
  | { type: "show-help" }
  | { type: "open-export" }
  | { type: "deactivate-text-editing" }
  | { type: "dialog-close" }
  | { type: "focus-move"; direction: "up" | "down" | "left" | "right" }
  | { type: "dialog-confirm" }
  | { type: "dialog-back" }
  | { type: "export"; advance: boolean }
  | { type: "export-mode"; mode: ExportMode }
  | { type: "reveal-export" };

export type ShortcutId =
  | "previous" | "next" | "replay" | "play-pause"
  | "group1" | "group2" | "skipped" | "undo" | "duplicate" | "rename"
  | "jump" | "focus-search" | "show-help" | "open-export"
  | "nudge-start-fine-back" | "nudge-start-fine-forward"
  | "nudge-start-coarse-back" | "nudge-start-coarse-forward"
  | "nudge-end-fine-back" | "nudge-end-fine-forward"
  | "nudge-end-coarse-back" | "nudge-end-coarse-forward"
  | "trim-select-start" | "trim-select-end"
  | "trim-nudge-fine-back" | "trim-nudge-fine-forward"
  | "trim-nudge-coarse-back" | "trim-nudge-coarse-forward"
  | "dialog-close" | "candidate-replay" | "candidate-play-pause"
  | "reference-replay" | "reference-play-pause" | "export-mode-as-is"
  | "export-mode-trim-edges" | "export-mode-trim-all" | "export" | "export-next"
  | "reveal-export";

export type ShortcutDefinition = {
  id: ShortcutId;
  label: string;
  keyboard?: string;
  contexts: readonly InputContext[];
  action: InputAction;
  defaultGamepadIndex?: number;
};

const reviewContext = ["review"] as const;
const dialogContext = ["active-dialog"] as const;

// This is the single source of truth for shortcut labels, keyboard help, and
// configurable gamepad rows. Add future shortcut actions here once; the UI
// surfaces and gamepad persistence derive their rows automatically.
export const SHORTCUT_DEFINITIONS: readonly ShortcutDefinition[] = [
  { id: "previous", label: "Previous clip", keyboard: "K / ↑", contexts: reviewContext, action: { type: "navigate", direction: "previous" }, defaultGamepadIndex: 12 },
  { id: "next", label: "Next clip", keyboard: "J / ↓", contexts: reviewContext, action: { type: "navigate", direction: "next" }, defaultGamepadIndex: 13 },
  { id: "replay", label: "Replay clip", keyboard: "Space", contexts: reviewContext, action: { type: "playback", target: "clip", mode: "replay" }, defaultGamepadIndex: 0 },
  { id: "play-pause", label: "Play / pause clip", keyboard: "Shift+Space", contexts: reviewContext, action: { type: "playback", target: "clip", mode: "toggle" } },
  { id: "group1", label: "Mark Group 1", keyboard: "1", contexts: reviewContext, action: { type: "classify", status: "group1" }, defaultGamepadIndex: 1 },
  { id: "group2", label: "Mark Group 2", keyboard: "2", contexts: reviewContext, action: { type: "classify", status: "group2" }, defaultGamepadIndex: 2 },
  { id: "skipped", label: "Skip clip", keyboard: "X", contexts: reviewContext, action: { type: "classify", status: "skipped" }, defaultGamepadIndex: 3 },
  { id: "undo", label: "Undo recent change", keyboard: "U", contexts: reviewContext, action: { type: "undo" } },
  { id: "duplicate", label: "Duplicate clip", keyboard: "D", contexts: reviewContext, action: { type: "duplicate" } },
  { id: "rename", label: "Rename title", keyboard: "R", contexts: reviewContext, action: { type: "rename" } },
  { id: "jump", label: "Jump to index", keyboard: "G", contexts: reviewContext, action: { type: "jump" } },
  { id: "focus-search", label: "Search titles", keyboard: "/", contexts: reviewContext, action: { type: "focus-search" } },
  { id: "show-help", label: "Show keyboard shortcuts", keyboard: "?", contexts: reviewContext, action: { type: "show-help" } },
  { id: "open-export", label: "Open export preview", keyboard: "E", contexts: reviewContext, action: { type: "open-export" } },
  { id: "nudge-start-fine-back", label: "Nudge start −10 ms", keyboard: ",", contexts: reviewContext, action: { type: "nudge", edge: "start", amount: -10, source: "keyboard" } },
  { id: "nudge-start-fine-forward", label: "Nudge start +10 ms", keyboard: ".", contexts: reviewContext, action: { type: "nudge", edge: "start", amount: 10, source: "keyboard" } },
  { id: "nudge-start-coarse-back", label: "Nudge start −100 ms", keyboard: "Shift+,", contexts: reviewContext, action: { type: "nudge", edge: "start", amount: -100, source: "keyboard" } },
  { id: "nudge-start-coarse-forward", label: "Nudge start +100 ms", keyboard: "Shift+.", contexts: reviewContext, action: { type: "nudge", edge: "start", amount: 100, source: "keyboard" } },
  { id: "nudge-end-fine-back", label: "Nudge end −10 ms", keyboard: "[", contexts: reviewContext, action: { type: "nudge", edge: "end", amount: -10, source: "keyboard" } },
  { id: "nudge-end-fine-forward", label: "Nudge end +10 ms", keyboard: "]", contexts: reviewContext, action: { type: "nudge", edge: "end", amount: 10, source: "keyboard" } },
  { id: "nudge-end-coarse-back", label: "Nudge end −100 ms", keyboard: "Shift+[", contexts: reviewContext, action: { type: "nudge", edge: "end", amount: -100, source: "keyboard" } },
  { id: "nudge-end-coarse-forward", label: "Nudge end +100 ms", keyboard: "Shift+]", contexts: reviewContext, action: { type: "nudge", edge: "end", amount: 100, source: "keyboard" } },
  { id: "trim-select-start", label: "Select start boundary", contexts: reviewContext, action: { type: "select-boundary", edge: "start" } },
  { id: "trim-select-end", label: "Select end boundary", contexts: reviewContext, action: { type: "select-boundary", edge: "end" } },
  { id: "trim-nudge-fine-back", label: "Nudge selected boundary −10 ms", contexts: reviewContext, action: { type: "nudge-selected", amount: -10, source: "gamepad" } },
  { id: "trim-nudge-fine-forward", label: "Nudge selected boundary +10 ms", contexts: reviewContext, action: { type: "nudge-selected", amount: 10, source: "gamepad" } },
  { id: "trim-nudge-coarse-back", label: "Nudge selected boundary −100 ms", contexts: reviewContext, action: { type: "nudge-selected", amount: -100, source: "gamepad" } },
  { id: "trim-nudge-coarse-forward", label: "Nudge selected boundary +100 ms", contexts: reviewContext, action: { type: "nudge-selected", amount: 100, source: "gamepad" } },
  { id: "dialog-close", label: "Close dialog", keyboard: "Esc", contexts: dialogContext, action: { type: "dialog-close" } },
  { id: "candidate-replay", label: "Replay export candidate", keyboard: "Space", contexts: dialogContext, action: { type: "playback", target: "candidate", mode: "replay" } },
  { id: "candidate-play-pause", label: "Play / pause export candidate", keyboard: "Shift+Space", contexts: dialogContext, action: { type: "playback", target: "candidate", mode: "toggle" } },
  { id: "reference-replay", label: "Replay reference", keyboard: "Q", contexts: dialogContext, action: { type: "playback", target: "reference", mode: "replay" } },
  { id: "reference-play-pause", label: "Play / pause reference", keyboard: "Shift+Q", contexts: dialogContext, action: { type: "playback", target: "reference", mode: "toggle" } },
  { id: "export-mode-as-is", label: "Export mode: As is", keyboard: "A", contexts: dialogContext, action: { type: "export-mode", mode: "as_is" } },
  { id: "export-mode-trim-edges", label: "Export mode: Trim edges", keyboard: "E", contexts: dialogContext, action: { type: "export-mode", mode: "trim_edges" } },
  { id: "export-mode-trim-all", label: "Export mode: Trim all", keyboard: "T", contexts: dialogContext, action: { type: "export-mode", mode: "trim_all" } },
  { id: "export", label: "Export", keyboard: "Enter", contexts: dialogContext, action: { type: "export", advance: false } },
  { id: "export-next", label: "Export and next", keyboard: "⌘ Enter", contexts: dialogContext, action: { type: "export", advance: true } },
  { id: "reveal-export", label: "Reveal exported file", contexts: dialogContext, action: { type: "reveal-export" } },
];

const shortcutDefinitionMap = new Map(SHORTCUT_DEFINITIONS.map((definition) => [definition.id, definition]));

export function shortcutDefinition(id: ShortcutId): ShortcutDefinition {
  const definition = shortcutDefinitionMap.get(id);
  if (!definition) throw new Error(`Unknown shortcut definition: ${id}`);
  return definition;
}

export function actionForShortcut(id: ShortcutId, source: ShortcutSource = "gamepad"): InputAction {
  const action = shortcutDefinition(id).action;
  if (action.type === "nudge") return { ...action, source };
  if (action.type === "nudge-selected") return { ...action, source: "gamepad" };
  return { ...action };
}

export type KeyboardInput = {
  key: string;
  code: string;
  repeat: boolean;
  shiftKey: boolean;
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  isComposing: boolean;
  targetEditable: boolean;
  targetTextEditing: boolean;
  targetInteractive: boolean;
};

export type InputAvailability = {
  context: InputContext;
  busy?: boolean;
  enabled?: boolean;
  hasSelection?: boolean;
  canMutate?: boolean;
  canUndo?: boolean;
  canDuplicate?: boolean;
  candidateReady?: boolean;
  hasNextClip?: boolean;
};

export type RepeatPolicy = "repeat" | "once";

export type CompositionTracker = {
  start(target: EventTarget | null): void;
  end(target: EventTarget | null): void;
  isActiveFor(target: EventTarget | null, event?: KeyboardEvent): boolean;
};

export function createCompositionTracker(): CompositionTracker {
  let activeTarget: EventTarget | null = null;
  const imeEvents = new WeakSet<KeyboardEvent>();
  let lastImeKey: Pick<KeyboardEvent, "target" | "key" | "code" | "timeStamp"> | null = null;
  function rememberImeKey(event: KeyboardEvent) {
    imeEvents.add(event);
    lastImeKey = { target: event.target, key: event.key, code: event.code, timeStamp: event.timeStamp };
  }
  return {
    start: (target) => {
      activeTarget = target;
    },
    end: (target) => {
      if (activeTarget === target) activeTarget = null;
    },
    isActiveFor: (target, event) => {
      // React and native listeners must agree for the entire event dispatch.
      // A microtask can run between listeners, so never expire event ownership there.
      if (event && imeEvents.has(event)) return true;
      // Chrome/macOS can replay an IME keydown as a different event after
      // compositionend, retaining its timestamp but clearing the IME flags.
      // Keep this across start/end updates, and match the target as well.
      if (event && event.timeStamp > 0 && lastImeKey?.target === target &&
          lastImeKey.timeStamp === event.timeStamp && lastImeKey.key === event.key &&
          lastImeKey.code === event.code) {
        imeEvents.add(event);
        return true;
      }
      // keyCode 229 also identifies IME boundary events with isComposing false.
      if ((event && (event.isComposing || event.keyCode === 229 || event.key === "Process")) ||
          (target !== null && activeTarget === target)) {
        if (event) rememberImeKey(event);
        return true;
      }
      return false;
    },
  };
}

const compositionTracker = createCompositionTracker();

export function installCompositionTracking(tracker: CompositionTracker = compositionTracker): () => void {
  function onKeyDown(event: KeyboardEvent) { tracker.isActiveFor(event.target, event); }
  function onStart(event: CompositionEvent) { tracker.start(event.target); }
  function onEnd(event: CompositionEvent) { tracker.end(event.target); }
  window.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("compositionstart", onStart, true);
  window.addEventListener("compositionend", onEnd, true);
  return () => {
    window.removeEventListener("keydown", onKeyDown, true);
    window.removeEventListener("compositionstart", onStart, true);
    window.removeEventListener("compositionend", onEnd, true);
  };
}

export function getInputContext({ activeDialog, textEditing, composing }: {
  activeDialog?: boolean;
  textEditing?: boolean;
  composing?: boolean;
}): InputContext {
  if (activeDialog) return "active-dialog";
  if (composing) return "composition";
  if (textEditing) return "text-editing";
  return "review";
}

export function keyboardInputFromEvent(event: KeyboardEvent, tracker: CompositionTracker = compositionTracker): KeyboardInput {
  // Always record IME keydowns, even when the browser's flags already identify them.
  const composing = tracker.isActiveFor(event.target, event);
  return {
    key: event.key,
    code: event.code,
    repeat: event.repeat,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    isComposing: composing,
    targetEditable: isEditableTarget(event.target),
    targetTextEditing: isTextEditingTarget(event.target),
    targetInteractive: isInteractiveTarget(event.target),
  };
}

export function isEditableTarget(target: EventTarget | null): boolean {
  return typeof Element !== "undefined" && target instanceof Element && target.closest("input, textarea, select, [contenteditable='true']") !== null;
}

export function isTextEditingTarget(target: EventTarget | null): boolean {
  if (typeof Element === "undefined" || !(target instanceof Element)) return false;
  const editable = target.closest("input, textarea, [contenteditable='true']");
  if (!editable) return false;
  if (typeof HTMLInputElement === "undefined" || !(editable instanceof HTMLInputElement)) return true;
  return !["button", "checkbox", "file", "hidden", "image", "radio", "range", "reset", "submit"].includes(editable.type);
}

export function deactivateTextEditingTarget(target: EventTarget | null): void {
  if (typeof Element === "undefined" || !(target instanceof Element)) return;
  const editable = target.closest("input, textarea, [contenteditable='true']");
  if (typeof HTMLElement !== "undefined" && editable instanceof HTMLElement) editable.blur();
}

export function isInteractiveTarget(target: EventTarget | null): boolean {
  return typeof Element !== "undefined" && target instanceof Element && target.closest("button, a, [role='button']") !== null;
}

export function actionRepeatPolicy(action: InputAction): RepeatPolicy {
  switch (action.type) {
    case "navigate":
    case "nudge":
    case "nudge-selected":
    case "focus-move":
      return "repeat";
    default:
      return "once";
  }
}

export function shouldDispatchAction(action: InputAction, input: Pick<KeyboardInput, "repeat">): boolean {
  return !input.repeat || actionRepeatPolicy(action) === "repeat";
}

export function isActionAvailable(action: InputAction, availability: InputAvailability): boolean {
  if (availability.enabled === false || !contextAllowsAction(action, availability.context)) return false;
  if (availability.busy && blocksWhileBusy(action)) return false;
  if (availability.canMutate === false && blocksWhileBusy(action)) return false;

  switch (action.type) {
    case "navigate":
      return true;
    case "deactivate-text-editing":
      return true;
    case "playback":
      return Boolean(availability.hasSelection);
    case "classify":
    case "set-status":
    case "nudge":
    case "select-boundary":
    case "nudge-selected":
    case "rename":
    case "open-export":
      return Boolean(availability.hasSelection);
    case "undo":
      return Boolean(availability.canUndo);
    case "duplicate":
      return Boolean(availability.canDuplicate);
    case "export":
      return Boolean(availability.candidateReady) && (!action.advance || Boolean(availability.hasNextClip));
    case "export-mode":
    case "dialog-close":
    case "dialog-confirm":
    case "dialog-back":
    case "focus-move":
    case "jump":
    case "focus-search":
    case "show-help":
    case "reveal-export":
      return true;
  }
}

export function resolveKeyboardAction(
  surface: InputSurface,
  input: KeyboardInput,
  context: InputContext,
): InputAction | null {
  if (input.isComposing) return null;
  if (isCode(input, "Escape") && input.targetTextEditing) return { type: "deactivate-text-editing" };

  switch (surface) {
    case "review":
      return resolveReviewAction(input, context);
    case "waveform":
      return resolveWaveformAction(input, context);
    case "export":
      return resolveExportAction(input, context);
    case "dialog":
      return resolveDialogAction(input, context);
  }
}

function resolveReviewAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "review" || input.targetEditable || input.altKey || input.ctrlKey || input.metaKey) return null;
  // `key` can be a locale-specific character or `Process` while an IME is
  // selected. `code` keeps these application shortcuts tied to physical keys.
  if (isCode(input, "KeyE")) return actionForShortcut("open-export", "keyboard");
  if (isCode(input, "KeyJ", "ArrowDown")) return actionForShortcut("next", "keyboard");
  if (isCode(input, "KeyK", "ArrowUp")) return actionForShortcut("previous", "keyboard");
  if (!input.shiftKey && isCode(input, "Digit1", "Numpad1")) return actionForShortcut("group1", "keyboard");
  if (!input.shiftKey && isCode(input, "Digit2", "Numpad2")) return actionForShortcut("group2", "keyboard");
  if (isCode(input, "KeyX")) return actionForShortcut("skipped", "keyboard");
  if (isCode(input, "KeyU")) return actionForShortcut("undo", "keyboard");
  if (isCode(input, "KeyD")) return actionForShortcut("duplicate", "keyboard");
  if (isCode(input, "KeyR")) return actionForShortcut("rename", "keyboard");
  if (isCode(input, "KeyG")) return actionForShortcut("jump", "keyboard");
  if (isCode(input, "Slash")) return input.shiftKey
    ? actionForShortcut("show-help", "keyboard")
    : actionForShortcut("focus-search", "keyboard");
  return null;
}

function resolveWaveformAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "review" || input.targetEditable || input.targetInteractive || input.altKey || input.ctrlKey || input.metaKey) return null;
  if (input.code === "Space") {
    return actionForShortcut(input.shiftKey ? "play-pause" : "replay", "keyboard");
  }
  const edge = input.code === "BracketLeft" || input.code === "BracketRight" ? "end"
    : input.code === "Comma" || input.code === "Period" ? "start" : null;
  if (!edge) return null;
  const direction = input.code === "Comma" || input.code === "BracketLeft" ? -1 : 1;
  const amount = direction * (input.shiftKey ? 100 : 10);
  const id: ShortcutId = edge === "start"
    ? amount === -100 ? "nudge-start-coarse-back" : amount === -10 ? "nudge-start-fine-back" : amount === 10 ? "nudge-start-fine-forward" : "nudge-start-coarse-forward"
    : amount === -100 ? "nudge-end-coarse-back" : amount === -10 ? "nudge-end-fine-back" : amount === 10 ? "nudge-end-fine-forward" : "nudge-end-coarse-forward";
  return actionForShortcut(id, "keyboard");
}

function resolveExportAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "active-dialog") return null;
  if (isCode(input, "Escape")) return actionForShortcut("dialog-close", "keyboard");
  if (input.targetEditable) return null;
  if (input.metaKey && !input.ctrlKey && !input.altKey && !input.shiftKey && isCode(input, "Enter", "NumpadEnter")) {
    return actionForShortcut("export-next", "keyboard");
  }
  if (input.altKey || input.ctrlKey || input.metaKey) return null;
  if (isCode(input, "Enter", "NumpadEnter") && !input.shiftKey && !input.targetInteractive) {
    return actionForShortcut("export", "keyboard");
  }
  if (input.targetInteractive) return null;
  if (input.code === "Space") {
    return actionForShortcut(input.shiftKey ? "candidate-play-pause" : "candidate-replay", "keyboard");
  }
  if (isCode(input, "KeyQ")) {
    return actionForShortcut(input.shiftKey ? "reference-play-pause" : "reference-replay", "keyboard");
  }
  if (input.shiftKey) return null;
  if (isCode(input, "KeyA")) return actionForShortcut("export-mode-as-is", "keyboard");
  if (isCode(input, "KeyE")) return actionForShortcut("export-mode-trim-edges", "keyboard");
  if (isCode(input, "KeyT")) return actionForShortcut("export-mode-trim-all", "keyboard");
  return null;
}

function resolveDialogAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "active-dialog" || !isCode(input, "Escape")) return null;
  return actionForShortcut("dialog-close", "keyboard");
}

function isCode(input: KeyboardInput, ...codes: string[]): boolean {
  return codes.includes(input.code);
}

function contextAllowsAction(action: InputAction, context: InputContext): boolean {
  if (action.type === "deactivate-text-editing") return true;
  if (context === "text-editing" || context === "composition") return false;
  if (context === "active-dialog") return isDialogAction(action);
  return !isDialogAction(action);
}

function isDialogAction(action: InputAction): boolean {
  if (action.type === "dialog-close" || action.type === "dialog-confirm" || action.type === "dialog-back" ||
      action.type === "focus-move" || action.type === "export" || action.type === "export-mode" || action.type === "reveal-export") return true;
  return action.type === "playback" && action.target !== "clip";
}

function blocksWhileBusy(action: InputAction): boolean {
  switch (action.type) {
    case "classify":
    case "set-status":
    case "nudge":
    case "nudge-selected":
    case "undo":
    case "duplicate":
    case "rename":
    case "open-export":
    case "export":
    case "reveal-export":
      return true;
    default:
      return false;
  }
}
