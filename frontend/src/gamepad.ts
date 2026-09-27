import { actionRepeatPolicy, type InputAction } from "./inputActions";

export const GAMEPAD_REPEAT_DELAY_MS = 400;
export const GAMEPAD_REPEAT_INTERVAL_MS = 120;
export const GAMEPAD_BINDINGS_STORAGE_KEY = "jipandan-gamepad-bindings";
export const GAMEPAD_BINDINGS_STORAGE_VERSION = 1;

export const GAMEPAD_BINDING_IDS = [
  "previous", "next", "replay", "group1", "group2", "skipped",
] as const;
export type GamepadBindingId = typeof GAMEPAD_BINDING_IDS[number];

// These labels follow the button indexes exposed by the browser's standard
// mapping. Mapping is intentionally limited to buttons; axes remain outside
// this first configurable slice.
export const STANDARD_GAMEPAD_CONTROL_LABELS = [
  "A", "B", "X", "Y", "Left shoulder", "Right shoulder",
  "Left trigger", "Right trigger", "Back", "Start", "Left stick",
  "Right stick", "D-pad ↑", "D-pad ↓", "D-pad ←", "D-pad →", "Home",
] as const;
export const STANDARD_GAMEPAD_BUTTON_INDEXES = STANDARD_GAMEPAD_CONTROL_LABELS.map((_, index) => index);

export type GamepadButtonBinding = {
  id: GamepadBindingId;
  index: number;
  control: string;
  actionLabel: string;
  action: InputAction;
};

export type GamepadBindingConfig = Record<GamepadBindingId, number>;

const bindingDefinitions: readonly {
  id: GamepadBindingId;
  defaultIndex: number;
  actionLabel: string;
  action: InputAction;
}[] = [
  { id: "previous", defaultIndex: 12, actionLabel: "Previous clip", action: { type: "navigate", direction: "previous" } },
  { id: "next", defaultIndex: 13, actionLabel: "Next clip", action: { type: "navigate", direction: "next" } },
  { id: "replay", defaultIndex: 0, actionLabel: "Replay clip", action: { type: "playback", target: "clip", mode: "replay" } },
  { id: "group1", defaultIndex: 1, actionLabel: "Group 1", action: { type: "classify", status: "group1" } },
  { id: "group2", defaultIndex: 2, actionLabel: "Group 2", action: { type: "classify", status: "group2" } },
  { id: "skipped", defaultIndex: 3, actionLabel: "Skip clip", action: { type: "classify", status: "skipped" } },
];

export function defaultGamepadBindingConfig(): GamepadBindingConfig {
  const config = {} as GamepadBindingConfig;
  for (const definition of bindingDefinitions) {
    config[definition.id] = definition.defaultIndex;
  }
  return config;
}

export function gamepadControlLabel(index: number): string {
  return STANDARD_GAMEPAD_CONTROL_LABELS[index] ?? `Button ${index}`;
}

export function bindingsForGamepadConfig(config: GamepadBindingConfig): readonly GamepadButtonBinding[] {
  return bindingDefinitions.map((definition) => ({
    id: definition.id,
    actionLabel: definition.actionLabel,
    action: definition.action,
    index: config[definition.id],
    control: gamepadControlLabel(config[definition.id]),
  }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isValidButtonIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) &&
    STANDARD_GAMEPAD_BUTTON_INDEXES.includes(value);
}

export function normalizeGamepadBindingConfig(value: unknown): GamepadBindingConfig {
  const fallback = defaultGamepadBindingConfig();
  let candidate: unknown = value;
  if (isRecord(value) && Object.hasOwn(value, "version")) {
    if (value.version !== GAMEPAD_BINDINGS_STORAGE_VERSION || !isRecord(value.bindings)) return fallback;
    candidate = value.bindings;
  }
  if (!isRecord(candidate) || Object.keys(candidate).length !== GAMEPAD_BINDING_IDS.length) return fallback;
  if (GAMEPAD_BINDING_IDS.some((id) => !Object.hasOwn(candidate, id) || !isValidButtonIndex(candidate[id]))) {
    return fallback;
  }
  const indexes = GAMEPAD_BINDING_IDS.map((id) => candidate[id] as number);
  if (new Set(indexes).size !== indexes.length) return fallback;
  const config = {} as GamepadBindingConfig;
  for (const id of GAMEPAD_BINDING_IDS) config[id] = candidate[id] as number;
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
  index: number,
): GamepadBindingId | null {
  return GAMEPAD_BINDING_IDS.find((id) => id !== target && config[id] === index) ?? null;
}

export type GamepadActionRequest = {
  id: number;
  clipId: string;
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
  onAction: (action: InputAction) => void;
  onStatusChange?: (status: GamepadStatus) => void;
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
      for (const index of STANDARD_GAMEPAD_BUTTON_INDEXES) awaitingRelease.add(index);
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
    const context = options.getContext?.();
    if (context !== undefined && context !== currentContext) {
      currentContext = context;
      resetInput(true);
    }
    if (!pageActive) return;
    const active = refreshStatus();
    if (!active) return;

    const pressed = new Set<number>();
    for (const index of STANDARD_GAMEPAD_BUTTON_INDEXES) {
      if (buttonIsPressed(active.buttons[index])) pressed.add(index);
    }
    for (const index of awaitingRelease) {
      if (!pressed.has(index)) awaitingRelease.delete(index);
    }

    for (const binding of bindings) {
      const isPressed = pressed.has(binding.index);
      const wasPressed = previousPressed.has(binding.index);
      if (awaitingRelease.has(binding.index)) {
        repeatStates.delete(binding.index);
        continue;
      }
      if (!isPressed) {
        repeatStates.delete(binding.index);
        continue;
      }
      if (!wasPressed) {
        options.onAction(binding.action);
        if (actionRepeatPolicy(binding.action) === "repeat") {
          repeatStates.set(binding.index, {
            action: binding.action,
            nextAt: timestamp + GAMEPAD_REPEAT_DELAY_MS,
          });
        }
      } else {
        const repeat = repeatStates.get(binding.index);
        if (repeat && timestamp >= repeat.nextAt) {
          options.onAction(repeat.action);
          // Dispatch at most one repeat per animation frame. This prevents a
          // stalled tab from producing a burst of navigation actions.
          repeat.nextAt = timestamp + GAMEPAD_REPEAT_INTERVAL_MS;
        }
      }
    }
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
