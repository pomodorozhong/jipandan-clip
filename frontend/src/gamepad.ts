import {
  actionForShortcut,
  actionRepeatPolicy,
  SHORTCUT_DEFINITIONS,
  type InputAction,
  type InputContext,
  type ShortcutDefinition,
  type ShortcutId,
} from "./inputActions";

export const GAMEPAD_REPEAT_DELAY_MS = 400;
export const GAMEPAD_REPEAT_DELAY_MIN_MS = 100;
export const GAMEPAD_REPEAT_DELAY_MAX_MS = 1000;
export const GAMEPAD_REPEAT_DELAY_STEP_MS = 50;
export const GAMEPAD_REPEAT_INTERVAL_MS = 120;
export const GAMEPAD_BINDINGS_STORAGE_KEY = "jipandan-gamepad-bindings";
export const GAMEPAD_BINDINGS_STORAGE_VERSION = 2;

export const GAMEPAD_BINDING_IDS = SHORTCUT_DEFINITIONS.map((definition) => definition.id) as readonly ShortcutId[];
export type GamepadBindingId = ShortcutId;

export function normalizeGamepadRepeatDelay(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return GAMEPAD_REPEAT_DELAY_MS;
  const stepped = Math.round(value / GAMEPAD_REPEAT_DELAY_STEP_MS) * GAMEPAD_REPEAT_DELAY_STEP_MS;
  return Math.max(GAMEPAD_REPEAT_DELAY_MIN_MS, Math.min(GAMEPAD_REPEAT_DELAY_MAX_MS, stepped));
}

// These labels follow the button indexes exposed by the browser's standard
// mapping. Stick directions use virtual indexes so they can share the same
// persisted binding and conflict model as buttons.
export const STANDARD_GAMEPAD_CONTROL_LABELS = [
  "A", "B", "X", "Y", "Left shoulder", "Right shoulder",
  "Left trigger", "Right trigger", "View", "Menu", "Left stick",
  "Right stick", "D-pad ↑", "D-pad ↓", "D-pad ←", "D-pad →", "Home",
] as const;
export const STANDARD_GAMEPAD_BUTTON_INDEXES = STANDARD_GAMEPAD_CONTROL_LABELS.map((_, index) => index);
export const STANDARD_GAMEPAD_AXIS_CONTROL_LABELS = [
  "Left stick ↑", "Left stick ↓", "Left stick ←", "Left stick →",
  "Right stick ↑", "Right stick ↓", "Right stick ←", "Right stick →",
] as const;
export const STANDARD_GAMEPAD_AXIS_CONTROL_INDEXES = STANDARD_GAMEPAD_AXIS_CONTROL_LABELS.map((_, index) => index + 100);
export const STANDARD_GAMEPAD_CONTROL_INDEXES = [
  ...STANDARD_GAMEPAD_BUTTON_INDEXES,
  ...STANDARD_GAMEPAD_AXIS_CONTROL_INDEXES,
] as const;

export type GamepadButtonBinding = {
  id: GamepadBindingId;
  index: number | null;
  control: string;
  actionLabel: string;
  keyboard?: string;
  action: InputAction;
  contexts: readonly InputContext[];
};

export type GamepadBindingConfig = Record<GamepadBindingId, number | null>;

const bindingDefinitions: readonly ShortcutDefinition[] = SHORTCUT_DEFINITIONS;

export function defaultGamepadBindingConfig(): GamepadBindingConfig {
  const config = {} as GamepadBindingConfig;
  for (const definition of bindingDefinitions) {
    config[definition.id] = definition.defaultGamepadIndex ?? null;
  }
  return config;
}

export function gamepadControlLabel(index: number | null): string {
  if (index === null) return "Unbound";
  const axisLabel = STANDARD_GAMEPAD_AXIS_CONTROL_LABELS[index - 100];
  if (axisLabel) return axisLabel;
  return STANDARD_GAMEPAD_CONTROL_LABELS[index] ?? `Button ${index}`;
}

export function bindingsForGamepadConfig(config: GamepadBindingConfig): readonly GamepadButtonBinding[] {
  return bindingDefinitions.map((definition) => ({
    id: definition.id,
    actionLabel: definition.label,
    keyboard: definition.keyboard,
    action: actionForShortcut(definition.id),
    index: config[definition.id],
    control: gamepadControlLabel(config[definition.id]),
    contexts: definition.contexts,
  }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isValidControlIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) &&
    STANDARD_GAMEPAD_CONTROL_INDEXES.includes(value);
}

function isValidBindingValue(value: unknown): value is number | null {
  return value === null || isValidControlIndex(value);
}

function contextsOverlap(left: readonly InputContext[], right: readonly InputContext[]): boolean {
  return left.some((context) => right.includes(context));
}

function hasOverlappingConflict(config: GamepadBindingConfig): boolean {
  const bindings = bindingsForGamepadConfig(config);
  return bindings.some((binding, index) => binding.index !== null && bindings.slice(index + 1).some((other) =>
    other.index === binding.index && contextsOverlap(binding.contexts, other.contexts)));
}

export function normalizeGamepadBindingConfig(value: unknown): GamepadBindingConfig {
  const fallback = defaultGamepadBindingConfig();
  let candidate: unknown = value;
  if (isRecord(value) && Object.hasOwn(value, "version")) {
    if ((value.version !== GAMEPAD_BINDINGS_STORAGE_VERSION && value.version !== 1) || !isRecord(value.bindings)) return fallback;
    candidate = value.bindings;
  }
  const config = {} as GamepadBindingConfig;
  if (!isRecord(candidate)) return fallback;
  for (const definition of bindingDefinitions) {
    const stored = candidate[definition.id];
    config[definition.id] = Object.hasOwn(candidate, definition.id) && isValidBindingValue(stored)
      ? stored : (definition.defaultGamepadIndex ?? null);
  }
  if (hasOverlappingConflict(config)) return fallback;
  return config;
}

type GamepadStorage = Pick<Storage, "getItem" | "setItem">;

function browserStorage(): GamepadStorage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

export function loadGamepadBindingConfig(storage: GamepadStorage = browserStorage()!): GamepadBindingConfig {
  const fallback = defaultGamepadBindingConfig();
  if (!storage) return fallback;
  try {
    const stored = storage.getItem(GAMEPAD_BINDINGS_STORAGE_KEY);
    return stored ? normalizeGamepadBindingConfig(JSON.parse(stored) as unknown) : fallback;
  } catch {
    return fallback;
  }
}

export function saveGamepadBindingConfig(config: GamepadBindingConfig, storage: GamepadStorage = browserStorage()!): void {
  if (!storage) return;
  try {
    storage.setItem(GAMEPAD_BINDINGS_STORAGE_KEY, JSON.stringify({
      version: GAMEPAD_BINDINGS_STORAGE_VERSION,
      bindings: normalizeGamepadBindingConfig(config),
    }));
  } catch {
    // The bindings still apply for this browser session when storage is unavailable.
  }
}

export function findGamepadBindingConflict(
  config: GamepadBindingConfig,
  target: GamepadBindingId,
  index: number | null,
): GamepadBindingId | null {
  if (index === null) return null;
  const targetDefinition = bindingDefinitions.find((definition) => definition.id === target);
  if (!targetDefinition) return null;
  return GAMEPAD_BINDING_IDS.find((id) => id !== target && config[id] === index &&
    contextsOverlap(targetDefinition.contexts, bindingDefinitions.find((definition) => definition.id === id)?.contexts ?? [])) ?? null;
}

export type GamepadActionRequest = {
  id: number;
  clipId?: string;
  action: InputAction;
};

// The defaults preserve the validated review mapping. Custom layouts are
// deliberately ignored until a separate mapping design is validated.
export const GAMEPAD_BINDINGS: readonly GamepadButtonBinding[] = bindingsForGamepadConfig(defaultGamepadBindingConfig());

export type GamepadDescriptor = {
  id: string;
  index: number;
  mapping: string;
};

export type GamepadStatus = {
  apiSupported: boolean;
  pageActive: boolean;
  activeController: GamepadDescriptor | null;
  unsupportedControllers: readonly GamepadDescriptor[];
};

export function initialGamepadStatus(apiSupported = false): GamepadStatus {
  return {
    apiSupported,
    pageActive: false,
    activeController: null,
    unsupportedControllers: [],
  };
}

type GamepadFrameCallback = (timestamp: number) => void;

export type GamepadAdapterOptions = {
  getGamepads?: () => readonly (Gamepad | null)[];
  getBindings?: () => readonly GamepadButtonBinding[];
  getRepeatDelayMs?: () => number;
  isInputSuppressed?: () => boolean;
  onAction: (action: InputAction) => void;
  onStatusChange?: (status: GamepadStatus) => void;
  onInputTypeChange?: (inputType: "keyboard" | "xbox") => void;
  getContext?: () => string;
  now?: () => number;
  requestFrame?: (callback: GamepadFrameCallback) => number;
  cancelFrame?: (frameId: number) => void;
  isPageActive?: () => boolean;
};

export type GamepadAdapter = {
  start(): void;
  stop(): void;
  poll(timestamp?: number): void;
  setContext(context: string): void;
  setPageActive(active: boolean): void;
  getStatus(): GamepadStatus;
};

type RepeatState = { action: InputAction; nextAt: number };

function defaultPageActive(): boolean {
  if (typeof document === "undefined") return true;
  if (document.visibilityState === "hidden") return false;
  return typeof document.hasFocus !== "function" || document.hasFocus();
}

function gamepadKey(gamepad: Gamepad): string {
  return `${gamepad.index}:${gamepad.id}`;
}

function descriptorFor(gamepad: Gamepad): GamepadDescriptor {
  return {
    id: gamepad.id || "Unknown controller",
    index: gamepad.index,
    mapping: gamepad.mapping || "unknown",
  };
}

function isConnected(gamepad: Gamepad | null): gamepad is Gamepad {
  return gamepad !== null && gamepad.connected !== false;
}

function buttonIsPressed(button: GamepadButton | undefined): boolean {
  return Boolean(button?.pressed) || (button?.value ?? 0) >= 0.5;
}

function sameDescriptor(left: GamepadDescriptor, right: GamepadDescriptor): boolean {
  return left.id === right.id && left.index === right.index && left.mapping === right.mapping;
}

function sameStatus(left: GamepadStatus, right: GamepadStatus): boolean {
  return left.apiSupported === right.apiSupported &&
    left.pageActive === right.pageActive &&
    (left.activeController === null
      ? right.activeController === null
      : right.activeController !== null && sameDescriptor(left.activeController, right.activeController)) &&
    left.unsupportedControllers.length === right.unsupportedControllers.length &&
    left.unsupportedControllers.every((controller, index) => sameDescriptor(controller, right.unsupportedControllers[index]));
}

function bindingsSignature(bindings: readonly GamepadButtonBinding[]): string {
  return bindings.map((binding) => `${binding.id}:${binding.index}`).join("|");
}

function fixedDialogBindings(): readonly { index: number; action: InputAction }[] {
  return [
    { index: 12, action: { type: "focus-move", direction: "up" } },
    { index: 13, action: { type: "focus-move", direction: "down" } },
    { index: 14, action: { type: "focus-move", direction: "left" } },
    { index: 15, action: { type: "focus-move", direction: "right" } },
    { index: 0, action: { type: "dialog-confirm" } },
    { index: 1, action: { type: "dialog-back" } },
    { index: 100, action: { type: "focus-move", direction: "up" } },
    { index: 101, action: { type: "focus-move", direction: "down" } },
    { index: 102, action: { type: "focus-move", direction: "left" } },
    { index: 103, action: { type: "focus-move", direction: "right" } },
  ];
}

function axisIsPressed(value: number, positive: boolean, wasPressed: boolean): boolean {
  const threshold = wasPressed ? 0.45 : 0.6;
  return positive ? value >= threshold : value <= -threshold;
}

export function readGamepadPressedControls(
  gamepad: Gamepad | null,
  previousPressed: ReadonlySet<number> = new Set(),
): Set<number> {
  const pressed = new Set<number>();
  if (!gamepad) return pressed;
  for (const index of STANDARD_GAMEPAD_BUTTON_INDEXES) {
    if (buttonIsPressed(gamepad.buttons[index])) pressed.add(index);
  }
  const axes = gamepad.axes ?? [];
  const axisControls: readonly { index: number; axis: number; positive: boolean }[] = [
    { index: 100, axis: 1, positive: false },
    { index: 101, axis: 1, positive: true },
    { index: 102, axis: 0, positive: false },
    { index: 103, axis: 0, positive: true },
    { index: 104, axis: 3, positive: false },
    { index: 105, axis: 3, positive: true },
    { index: 106, axis: 2, positive: false },
    { index: 107, axis: 2, positive: true },
  ];
  for (const control of axisControls) {
    if (axisIsPressed(axes[control.axis] ?? 0, control.positive, previousPressed.has(control.index))) {
      pressed.add(control.index);
    }
  }
  return pressed;
}

export function createGamepadAdapter(options: GamepadAdapterOptions): GamepadAdapter {
  const getGamepads = options.getGamepads;
  const now = options.now ?? (() => typeof performance === "undefined" ? Date.now() : performance.now());
  const requestFrame = options.requestFrame ?? (
    typeof window === "undefined" ? undefined : (callback: GamepadFrameCallback) => window.requestAnimationFrame(callback)
  );
  const cancelFrame = options.cancelFrame ?? (
    typeof window === "undefined" ? undefined : (frameId: number) => window.cancelAnimationFrame(frameId)
  );
  const eventTarget = typeof window === "undefined" ? null : window;
  const visibilityTarget = typeof document === "undefined" ? null : document;

  let status = initialGamepadStatus(Boolean(getGamepads));
  let activeControllerKey: string | null = null;
  let currentContext: string | undefined;
  let pageActive = options.isPageActive?.() ?? defaultPageActive();
  let started = false;
  let frameId: number | null = null;
  let activeBindings = options.getBindings?.() ?? GAMEPAD_BINDINGS;
  let activeBindingsSignature = bindingsSignature(activeBindings);
  const previousPressed = new Set<number>();
  const awaitingRelease = new Set<number>();
  const repeatStates = new Map<number, RepeatState>();

  function emitStatus(next: GamepadStatus) {
    if (sameStatus(status, next)) return;
    status = next;
    options.onStatusChange?.(next);
  }

  function readGamepads(): Gamepad[] {
    if (!getGamepads) return [];
    try {
      return Array.from(getGamepads()).filter(isConnected);
    } catch {
      return [];
    }
  }

  function resetInput(blockAllButtons = false) {
    for (const index of previousPressed) awaitingRelease.add(index);
    if (blockAllButtons) {
      for (const index of STANDARD_GAMEPAD_CONTROL_INDEXES) awaitingRelease.add(index);
    }
    previousPressed.clear();
    repeatStates.clear();
  }

  function selectController(gamepads: readonly Gamepad[]): {
    active: Gamepad | null;
    unsupported: Gamepad[];
  } {
    const connected = [...gamepads].sort((left, right) => left.index - right.index);
    const standard = connected.filter((gamepad) => gamepad.mapping === "standard");
    const active = standard.find((gamepad) => gamepadKey(gamepad) === activeControllerKey) ?? standard[0] ?? null;
    return {
      active,
      unsupported: connected.filter((gamepad) => gamepad.mapping !== "standard"),
    };
  }

  function refreshStatus(gamepads = readGamepads()): Gamepad | null {
    const selection = selectController(gamepads);
    const nextKey = selection.active ? gamepadKey(selection.active) : null;
    if (nextKey !== activeControllerKey) {
      resetInput(Boolean(selection.active));
      activeControllerKey = nextKey;
      options.onInputTypeChange?.(selection.active ? "xbox" : "keyboard");
    }
    emitStatus({
      apiSupported: Boolean(getGamepads),
      pageActive,
      activeController: selection.active ? descriptorFor(selection.active) : null,
      unsupportedControllers: selection.unsupported.map(descriptorFor),
    });
    return selection.active;
  }

  function syncBindings(): readonly GamepadButtonBinding[] {
    const next = options.getBindings?.() ?? GAMEPAD_BINDINGS;
    const nextSignature = bindingsSignature(next);
    if (nextSignature !== activeBindingsSignature) {
      activeBindings = next;
      activeBindingsSignature = nextSignature;
      resetInput(true);
    }
    return activeBindings;
  }

  function scheduleFrame() {
    if (!started || !pageActive || frameId !== null || !requestFrame) return;
    frameId = requestFrame((timestamp) => {
      frameId = null;
      if (!started || !pageActive) return;
      poll(timestamp);
      scheduleFrame();
    });
  }

  function cancelScheduledFrame() {
    if (frameId === null) return;
    cancelFrame?.(frameId);
    frameId = null;
  }

  function syncPageActivity() {
    setPageActive(options.isPageActive?.() ?? defaultPageActive());
  }

  function onGamepadConnected() {
    refreshStatus();
    scheduleFrame();
  }

  function onGamepadDisconnected() {
    resetInput(true);
    refreshStatus();
  }

  function onWindowBlur() {
    setPageActive(false);
  }

  function start() {
    if (started) return;
    started = true;
    eventTarget?.addEventListener("gamepadconnected", onGamepadConnected);
    eventTarget?.addEventListener("gamepaddisconnected", onGamepadDisconnected);
    eventTarget?.addEventListener("focus", syncPageActivity);
    eventTarget?.addEventListener("blur", onWindowBlur);
    visibilityTarget?.addEventListener("visibilitychange", syncPageActivity);
    pageActive = options.isPageActive?.() ?? defaultPageActive();
    refreshStatus();
    scheduleFrame();
  }

  function stop() {
    if (!started) return;
    started = false;
    cancelScheduledFrame();
    eventTarget?.removeEventListener("gamepadconnected", onGamepadConnected);
    eventTarget?.removeEventListener("gamepaddisconnected", onGamepadDisconnected);
    eventTarget?.removeEventListener("focus", syncPageActivity);
    eventTarget?.removeEventListener("blur", onWindowBlur);
    visibilityTarget?.removeEventListener("visibilitychange", syncPageActivity);
    resetInput(true);
  }

  function poll(timestamp = now()) {
    const bindings = syncBindings();
    const context = options.getContext?.() ?? currentContext;
    if (context !== undefined && context !== currentContext) {
      currentContext = context;
      resetInput(true);
    }
    if (!pageActive) return;
    const active = refreshStatus();
    if (!active) return;
    if (options.isInputSuppressed?.()) {
      // Mapping capture reads the same controller directly. Do not let the
      // control being captured move dialog focus or trigger another action.
      // Keep every control release-armed until capture is finished.
      resetInput(true);
      return;
    }

    const pressed = readGamepadPressedControls(active, previousPressed);
    for (const index of awaitingRelease) {
      if (!pressed.has(index)) awaitingRelease.delete(index);
    }

    const fixed = context === "active-dialog" ? fixedDialogBindings() : [];
    const fixedIndexes = new Set(fixed.map((binding) => binding.index));

    function dispatchBinding(index: number, action: InputAction) {
      const isPressed = pressed.has(index);
      const wasPressed = previousPressed.has(index);
      if (awaitingRelease.has(index)) {
        repeatStates.delete(index);
        return;
      }
      if (!isPressed) {
        repeatStates.delete(index);
        return;
      }
      options.onInputTypeChange?.("xbox");
      if (!wasPressed) {
        options.onAction(action);
        if (actionRepeatPolicy(action) === "repeat") {
          repeatStates.set(index, {
            action,
            nextAt: timestamp + normalizeGamepadRepeatDelay(options.getRepeatDelayMs?.()),
          });
        }
      } else {
        const repeat = repeatStates.get(index);
        if (repeat && timestamp >= repeat.nextAt) {
          options.onAction(repeat.action);
          // Dispatch at most one repeat per animation frame. This prevents a
          // stalled tab from producing a burst of navigation actions.
          repeat.nextAt = timestamp + GAMEPAD_REPEAT_INTERVAL_MS;
        }
      }
    }

    for (const binding of bindings) {
      if (binding.index === null || fixedIndexes.has(binding.index)) continue;
      dispatchBinding(binding.index, binding.action);
    }
    for (const binding of fixed) dispatchBinding(binding.index, binding.action);
    previousPressed.clear();
    for (const index of pressed) previousPressed.add(index);
  }

  function setContext(context: string) {
    if (context === currentContext) return;
    currentContext = context;
    resetInput(true);
  }

  function setPageActive(active: boolean) {
    if (active === pageActive) {
      if (active) scheduleFrame();
      return;
    }
    pageActive = active;
    if (!active) {
      resetInput();
      cancelScheduledFrame();
    } else {
      // A button may have been pressed while this tab was inactive. Require a
      // fresh release even when the browser reports the same controller.
      resetInput(true);
    }
    refreshStatus();
    if (active) {
      poll();
      scheduleFrame();
    }
  }

  return { start, stop, poll, setContext, setPageActive, getStatus: () => status };
}
