import type { ExportMode, Status } from "./api";

export type InputSurface = "review" | "waveform" | "export" | "dialog";
export type InputContext = "review" | "active-dialog" | "text-editing" | "composition";
export type PlaybackTarget = "clip" | "candidate" | "reference";
export type ClassificationStatus = Extract<Status, "group1" | "group2" | "skipped">;

export type InputAction =
  | { type: "navigate"; direction: "next" | "previous" }
  | { type: "playback"; target: PlaybackTarget; mode: "replay" | "toggle" | "audition-start" | "audition-end" }
  | { type: "classify"; status: ClassificationStatus }
  | { type: "set-status"; status: Status }
  | { type: "nudge"; edge: "start" | "end"; amount: number; source: "keyboard" | "pointer" }
  | { type: "undo" }
  | { type: "duplicate" }
  | { type: "rename" }
  | { type: "jump" }
  | { type: "focus-search" }
  | { type: "show-help" }
  | { type: "open-export" }
  | { type: "deactivate-text-editing" }
  | { type: "dialog-close" }
  | { type: "export"; advance: boolean }
  | { type: "export-mode"; mode: ExportMode }
  | { type: "reveal-export" };

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
  if (isCode(input, "KeyE")) return { type: "open-export" };
  if (isCode(input, "KeyJ", "ArrowDown")) return { type: "navigate", direction: "next" };
  if (isCode(input, "KeyK", "ArrowUp")) return { type: "navigate", direction: "previous" };
  if (!input.shiftKey && isCode(input, "Digit1", "Numpad1")) return { type: "classify", status: "group1" };
  if (!input.shiftKey && isCode(input, "Digit2", "Numpad2")) return { type: "classify", status: "group2" };
  if (isCode(input, "KeyX")) return { type: "classify", status: "skipped" };
  if (isCode(input, "KeyU")) return { type: "undo" };
  if (isCode(input, "KeyD")) return { type: "duplicate" };
  if (isCode(input, "KeyR")) return { type: "rename" };
  if (isCode(input, "KeyG")) return { type: "jump" };
  if (isCode(input, "Slash")) return input.shiftKey
    ? { type: "show-help" }
    : { type: "focus-search" };
  return null;
}

function resolveWaveformAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "review" || input.targetEditable || input.targetInteractive || input.altKey || input.ctrlKey || input.metaKey) return null;
  if (input.code === "Space") {
    return { type: "playback", target: "clip", mode: input.shiftKey ? "toggle" : "replay" };
  }
  const edge = input.code === "BracketLeft" || input.code === "BracketRight" ? "end"
    : input.code === "Comma" || input.code === "Period" ? "start" : null;
  if (!edge) return null;
  const direction = input.code === "Comma" || input.code === "BracketLeft" ? -1 : 1;
  return { type: "nudge", edge, amount: direction * (input.shiftKey ? 100 : 10), source: "keyboard" };
}

function resolveExportAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "active-dialog") return null;
  if (isCode(input, "Escape")) return { type: "dialog-close" };
  if (input.targetEditable) return null;
  if (input.metaKey && !input.ctrlKey && !input.altKey && !input.shiftKey && isCode(input, "Enter", "NumpadEnter")) {
    return { type: "export", advance: true };
  }
  if (input.altKey || input.ctrlKey || input.metaKey) return null;
  if (isCode(input, "Enter", "NumpadEnter") && !input.shiftKey && !input.targetInteractive) {
    return { type: "export", advance: false };
  }
  if (input.targetInteractive) return null;
  if (input.code === "Space") {
    return { type: "playback", target: "candidate", mode: input.shiftKey ? "toggle" : "replay" };
  }
  if (isCode(input, "KeyQ")) {
    return { type: "playback", target: "reference", mode: input.shiftKey ? "toggle" : "replay" };
  }
  if (input.shiftKey) return null;
  if (isCode(input, "KeyA")) return { type: "export-mode", mode: "as_is" };
  if (isCode(input, "KeyE")) return { type: "export-mode", mode: "trim_edges" };
  if (isCode(input, "KeyT")) return { type: "export-mode", mode: "trim_all" };
  return null;
}

function resolveDialogAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "active-dialog" || !isCode(input, "Escape")) return null;
  return { type: "dialog-close" };
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
  if (action.type === "dialog-close" || action.type === "export" || action.type === "export-mode" || action.type === "reveal-export") return true;
  return action.type === "playback" && action.target !== "clip";
}

function blocksWhileBusy(action: InputAction): boolean {
  switch (action.type) {
    case "classify":
    case "set-status":
    case "nudge":
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
