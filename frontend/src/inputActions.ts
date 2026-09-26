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

export function keyboardInputFromEvent(event: KeyboardEvent): KeyboardInput {
  return {
    key: event.key,
    code: event.code,
    repeat: event.repeat,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    isComposing: event.isComposing || event.key === "Process",
    targetEditable: isEditableTarget(event.target),
    targetInteractive: isInteractiveTarget(event.target),
  };
}

export function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("input, textarea, select, [contenteditable='true']") !== null;
}

export function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("button, a, [role='button']") !== null;
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
  const key = input.key.toLowerCase();
  if (key === "e") return { type: "open-export" };
  if (key === "j" || key === "arrowdown") return { type: "navigate", direction: "next" };
  if (key === "k" || key === "arrowup") return { type: "navigate", direction: "previous" };
  if (key === "1") return { type: "classify", status: "group1" };
  if (key === "2") return { type: "classify", status: "group2" };
  if (key === "x") return { type: "classify", status: "skipped" };
  if (key === "u") return { type: "undo" };
  if (key === "d") return { type: "duplicate" };
  if (key === "r") return { type: "rename" };
  if (key === "g") return { type: "jump" };
  if (key === "/") return { type: "focus-search" };
  if (key === "?") return { type: "show-help" };
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
  if (input.key === "Escape") return { type: "dialog-close" };
  if (input.targetEditable) return null;
  if (input.metaKey && !input.ctrlKey && !input.altKey && !input.shiftKey && input.key === "Enter") {
    return { type: "export", advance: true };
  }
  if (input.altKey || input.ctrlKey || input.metaKey) return null;
  if (input.key === "Enter" && !input.shiftKey && !input.targetInteractive) {
    return { type: "export", advance: false };
  }
  if (input.targetInteractive) return null;
  if (input.code === "Space") {
    return { type: "playback", target: "candidate", mode: input.shiftKey ? "toggle" : "replay" };
  }
  if (input.code === "KeyQ") {
    return { type: "playback", target: "reference", mode: input.shiftKey ? "toggle" : "replay" };
  }
  if (input.shiftKey) return null;
  const key = input.key.toLowerCase();
  if (key === "a") return { type: "export-mode", mode: "as_is" };
  if (key === "e") return { type: "export-mode", mode: "trim_edges" };
  if (key === "t") return { type: "export-mode", mode: "trim_all" };
  return null;
}

function resolveDialogAction(input: KeyboardInput, context: InputContext): InputAction | null {
  if (context !== "active-dialog" || input.key !== "Escape") return null;
  return { type: "dialog-close" };
}

function contextAllowsAction(action: InputAction, context: InputContext): boolean {
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
