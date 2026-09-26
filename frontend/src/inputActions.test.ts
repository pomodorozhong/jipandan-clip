import { describe, expect, it } from "vitest";
import {
  actionRepeatPolicy,
  getInputContext,
  isActionAvailable,
  resolveKeyboardAction,
  shouldDispatchAction,
  type InputAction,
  type KeyboardInput,
} from "./inputActions";

function input(overrides: Partial<KeyboardInput> = {}): KeyboardInput {
  return {
    key: "",
    code: "",
    repeat: false,
    shiftKey: false,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    isComposing: false,
    targetEditable: false,
    targetInteractive: false,
    ...overrides,
  };
}

describe("input contexts", () => {
  it("gives an active dialog priority over review shortcuts", () => {
    expect(getInputContext({ activeDialog: true, textEditing: true })).toBe("active-dialog");
    expect(resolveKeyboardAction("review", input({ key: "j" }), "active-dialog")).toBeNull();
  });

  it("protects text editing and composition from review actions", () => {
    expect(resolveKeyboardAction("review", input({ key: "1" }), "text-editing")).toBeNull();
    expect(resolveKeyboardAction("review", input({ key: "1", isComposing: true }), "review")).toBeNull();
    expect(resolveKeyboardAction("review", input({ key: "1", targetEditable: true }), "review")).toBeNull();
  });

  it("preserves browser modifier shortcuts", () => {
    expect(resolveKeyboardAction("review", input({ key: "e", metaKey: true }), "review")).toBeNull();
    expect(resolveKeyboardAction("review", input({ key: "u", ctrlKey: true }), "review")).toBeNull();
  });
});

describe("keyboard action routing", () => {
  it("maps review actions to shared action objects", () => {
    expect(resolveKeyboardAction("review", input({ key: "j" }), "review")).toEqual({
      type: "navigate", direction: "next",
    });
    expect(resolveKeyboardAction("review", input({ key: "2" }), "review")).toEqual({
      type: "classify", status: "group2",
    });
    expect(resolveKeyboardAction("waveform", input({ code: "BracketLeft" }), "review")).toEqual({
      type: "nudge", edge: "end", amount: -10, source: "keyboard",
    });
  });

  it("keeps export Enter out of editable fields", () => {
    expect(resolveKeyboardAction("export", input({ key: "Enter", targetEditable: true }), "active-dialog")).toBeNull();
    expect(resolveKeyboardAction("export", input({ key: "Enter" }), "active-dialog")).toEqual({
      type: "export", advance: false,
    });
    expect(resolveKeyboardAction("export", input({ key: "Enter", metaKey: true, targetEditable: true }), "active-dialog")).toBeNull();
    expect(resolveKeyboardAction("export", input({ code: "Space", targetInteractive: true }), "active-dialog")).toBeNull();
  });

  it("routes dialog actions without leaking them into review", () => {
    expect(resolveKeyboardAction("dialog", input({ key: "Escape" }), "active-dialog")).toEqual({ type: "dialog-close" });
    expect(resolveKeyboardAction("export", input({ key: "Escape", isComposing: true }), "active-dialog")).toBeNull();
  });
});

describe("repeat and availability policy", () => {
  const navigation: InputAction = { type: "navigate", direction: "next" };
  const duplicate: InputAction = { type: "duplicate" };
  const nudge: InputAction = { type: "nudge", edge: "start", amount: 10, source: "keyboard" };

  it("repeats navigation and nudges but not mutations", () => {
    expect(actionRepeatPolicy(navigation)).toBe("repeat");
    expect(actionRepeatPolicy(nudge)).toBe("repeat");
    expect(actionRepeatPolicy(duplicate)).toBe("once");
    expect(shouldDispatchAction(navigation, { repeat: true })).toBe(true);
    expect(shouldDispatchAction(duplicate, { repeat: true })).toBe(false);
  });

  it("blocks conflicting actions while saving", () => {
    expect(isActionAvailable({ type: "classify", status: "group1" }, {
      context: "review", hasSelection: true, busy: true,
    })).toBe(false);
    expect(isActionAvailable(navigation, { context: "review", busy: true })).toBe(true);
    expect(isActionAvailable({ type: "export", advance: false }, {
      context: "active-dialog", candidateReady: true, busy: true,
    })).toBe(false);
  });
});
