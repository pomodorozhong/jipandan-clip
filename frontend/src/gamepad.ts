import { actionRepeatPolicy, type InputAction } from "./inputActions";

export const GAMEPAD_REPEAT_DELAY_MS = 400;
export const GAMEPAD_REPEAT_INTERVAL_MS = 120;

export type GamepadButtonBinding = {
  index: number;
  control: string;
  actionLabel: string;
  action: InputAction;
};

export type GamepadActionRequest = {
  id: number;
  clipId: string;
  action: InputAction;
};

// These are the buttons exposed by the browser's standard mapping. Custom
// layouts are deliberately ignored until the mapping screen is implemented.
export const GAMEPAD_BINDINGS: readonly GamepadButtonBinding[] = [
  { index: 12, control: "D-pad ↑", actionLabel: "Previous clip", action: { type: "navigate", direction: "previous" } },
  { index: 13, control: "D-pad ↓", actionLabel: "Next clip", action: { type: "navigate", direction: "next" } },
  { index: 0, control: "A", actionLabel: "Replay clip", action: { type: "playback", target: "clip", mode: "replay" } },
  { index: 1, control: "B", actionLabel: "Group 1", action: { type: "classify", status: "group1" } },
  { index: 2, control: "X", actionLabel: "Group 2", action: { type: "classify", status: "group2" } },
  { index: 3, control: "Y", actionLabel: "Skip clip", action: { type: "classify", status: "skipped" } },
];

const mappedButtonIndexes = GAMEPAD_BINDINGS.map((binding) => binding.index);

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
      for (const index of mappedButtonIndexes) awaitingRelease.add(index);
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
    const context = options.getContext?.();
    if (context !== undefined && context !== currentContext) {
      currentContext = context;
      resetInput();
    }
    if (!pageActive) return;
    const active = refreshStatus();
    if (!active) return;

    const pressed = new Set<number>();
    for (const index of mappedButtonIndexes) {
      if (buttonIsPressed(active.buttons[index])) pressed.add(index);
    }
    for (const index of awaitingRelease) {
      if (!pressed.has(index)) awaitingRelease.delete(index);
    }

    for (const binding of GAMEPAD_BINDINGS) {
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
    resetInput();
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
