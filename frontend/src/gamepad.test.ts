import { describe, expect, it } from "vitest";
import {
  createGamepadAdapter,
  GAMEPAD_REPEAT_DELAY_MS,
  initialGamepadStatus,
  type GamepadStatus,
} from "./gamepad";
import type { InputAction } from "./inputActions";

type FakeButton = { pressed: boolean; value: number };

function fakeGamepad(id = "Test Pad", mapping = "standard") {
  return {
    id,
    index: 0,
    mapping,
    connected: true,
    buttons: Array.from({ length: 16 }, (): FakeButton => ({ pressed: false, value: 0 })),
  } as unknown as Gamepad & { buttons: FakeButton[] };
}

function press(gamepad: Gamepad & { buttons: FakeButton[] }, index: number, pressed: boolean) {
  gamepad.buttons[index].pressed = pressed;
  gamepad.buttons[index].value = pressed ? 1 : 0;
}

function createHarness() {
  const gamepads: (Gamepad | null)[] = [];
  const actions: InputAction[] = [];
  const statuses: GamepadStatus[] = [];
  const adapter = createGamepadAdapter({
    getGamepads: () => gamepads,
    onAction: (action) => actions.push(action),
    onStatusChange: (status) => statuses.push(status),
  });
  adapter.setPageActive(true);
  return { adapter, gamepads, actions, statuses };
}

describe("gamepad adapter", () => {
  it("starts with an explicit empty status", () => {
    expect(initialGamepadStatus()).toEqual({
      apiSupported: false,
      pageActive: false,
      activeController: null,
      unsupportedControllers: [],
    });
  });

  it("dispatches standard navigation, replay, and classification buttons", () => {
    const { adapter, gamepads, actions } = createHarness();
    const gamepad = fakeGamepad();
    gamepads.push(gamepad);
    adapter.poll(0); // Select the controller and arm release-gating.

    press(gamepad, 13, true);
    adapter.poll(1);
    press(gamepad, 13, false);
    adapter.poll(2);
    press(gamepad, 0, true);
    adapter.poll(3);
    press(gamepad, 0, false);
    adapter.poll(4);
    press(gamepad, 1, true);
    adapter.poll(5);
    press(gamepad, 1, false);
    adapter.poll(6);
    press(gamepad, 2, true);
    adapter.poll(7);
    press(gamepad, 2, false);
    adapter.poll(8);
    press(gamepad, 3, true);
    adapter.poll(9);

    expect(actions).toEqual([
      { type: "navigate", direction: "next" },
      { type: "playback", target: "clip", mode: "replay" },
      { type: "classify", status: "group1" },
      { type: "classify", status: "group2" },
      { type: "classify", status: "skipped" },
    ]);
  });

  it("repeats navigation after a delay but not one-shot actions", () => {
    const { adapter, gamepads, actions } = createHarness();
    const gamepad = fakeGamepad();
    gamepads.push(gamepad);
    adapter.poll(0);

    press(gamepad, 13, true);
    adapter.poll(1);
    adapter.poll(GAMEPAD_REPEAT_DELAY_MS - 1);
    expect(actions).toHaveLength(1);
    adapter.poll(GAMEPAD_REPEAT_DELAY_MS + 1);
    expect(actions).toHaveLength(2);
    adapter.poll(GAMEPAD_REPEAT_DELAY_MS + 120);
    expect(actions).toHaveLength(2);
    adapter.poll(GAMEPAD_REPEAT_DELAY_MS + 121);
    expect(actions).toHaveLength(3);

    press(gamepad, 13, false);
    adapter.poll(600);
    press(gamepad, 1, true);
    adapter.poll(601);
    adapter.poll(1200);
    expect(actions.filter((action) => action.type === "classify")).toHaveLength(1);
  });

  it("requires release after a context transition", () => {
    const { adapter, gamepads, actions } = createHarness();
    const gamepad = fakeGamepad();
    gamepads.push(gamepad);
    adapter.poll(0);
    press(gamepad, 13, true);
    adapter.poll(1);
    adapter.setContext("active-dialog");
    adapter.poll(2);
    adapter.setContext("review");
    adapter.poll(3);
    expect(actions).toHaveLength(1);

    press(gamepad, 13, false);
    adapter.poll(4);
    press(gamepad, 13, true);
    adapter.poll(5);
    expect(actions).toHaveLength(2);
  });

  it("resets held input on page deactivation and reconnect", () => {
    const { adapter, gamepads, actions, statuses } = createHarness();
    const gamepad = fakeGamepad();
    gamepads.push(gamepad);
    adapter.poll(0);

    press(gamepad, 0, true);
    adapter.poll(1);
    adapter.setPageActive(false);
    adapter.setPageActive(true);
    adapter.poll(2);
    expect(actions).toHaveLength(1);

    gamepads.length = 0;
    adapter.poll(3);
    const reconnected = fakeGamepad();
    gamepads.push(reconnected);
    press(reconnected, 0, true);
    adapter.poll(4);
    expect(actions).toHaveLength(1);
    press(reconnected, 0, false);
    adapter.poll(5);
    press(reconnected, 0, true);
    adapter.poll(6);
    expect(actions).toHaveLength(2);
    expect(statuses.at(-1)?.activeController?.id).toBe("Test Pad");
  });

  it("reports unsupported mappings without guessing actions", () => {
    const { adapter, gamepads, actions, statuses } = createHarness();
    const gamepad = fakeGamepad("Unknown Layout", "");
    gamepads.push(gamepad);
    press(gamepad, 0, true);
    adapter.poll(0);

    expect(actions).toHaveLength(0);
    expect(statuses.at(-1)).toMatchObject({
      apiSupported: true,
      activeController: null,
      unsupportedControllers: [{ id: "Unknown Layout", index: 0, mapping: "unknown" }],
    });
  });
});
