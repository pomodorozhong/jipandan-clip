import { describe, expect, it } from "vitest";
import {
  actionRepeatPolicy,
  createCompositionTracker,
  getInputContext,
  isActionAvailable,
  keyboardInputFromEvent,
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
    targetTextEditing: false,
    targetInteractive: false,
    ...overrides,
  };
}

describe("input contexts", () => {
  it("does not apply a replay marker to another field", () => {
    const tracker = createCompositionTracker();
    const target = {} as EventTarget;
    const escape = {
      key: "Escape", code: "Escape", keyCode: 229, isComposing: false,
      timeStamp: 100, target,
    } as KeyboardEvent;
    expect(keyboardInputFromEvent(escape, tracker).isComposing).toBe(true);
    expect(keyboardInputFromEvent({
      ...escape, keyCode: 27, target: {} as EventTarget,
    } as KeyboardEvent, tracker).isComposing).toBe(false);
  });

  it.each(["review", "waveform", "export", "dialog"] as const)(
    "ignores Chrome's replayed Bopomofo Escape on %s after non-empty compositionend",
    (surface) => {
      const tracker = createCompositionTracker();
      const target = {} as EventTarget;
      const imeEscape = {
        key: "Escape", code: "Escape", keyCode: 229, isComposing: true,
        timeStamp: 219781, target, repeat: false,
      } as KeyboardEvent;
      const actionFor = (event: KeyboardEvent) => resolveKeyboardAction(surface, {
        ...keyboardInputFromEvent(event, tracker),
        targetEditable: true, targetTextEditing: true,
      }, "text-editing");

      // Captured in Chrome with macOS Bopomofo in the title rename field:
      // IME keydown -> compositionupdate/beforeinput -> non-empty compositionend
      // -> keyup -> a new keydown object with the original keydown timestamp.
      tracker.start(target);
      expect(actionFor(imeEscape)).toBeNull();
      tracker.start(target);
      tracker.end(target, false);
      const replay = { ...imeEscape, keyCode: 27, isComposing: false } as KeyboardEvent;
      expect(keyboardInputFromEvent(replay, tracker).isComposing).toBe(true);
      expect(actionFor(replay)).toBeNull();
      expect(actionFor({ ...replay, timeStamp: 220000 } as KeyboardEvent)).toEqual({
        type: "deactivate-text-editing",
      });
    },
  );

  it("keeps a cancelled IME Escape protected across handlers and microtasks", async () => {
    const tracker = createCompositionTracker();
    const target = {} as EventTarget;
    const escape = {
      key: "Escape", code: "Escape", keyCode: 27, repeat: false,
      isComposing: false, target,
    } as KeyboardEvent;
    tracker.start(target);
    tracker.end(target, true);

    // The field's React handler runs before the window shortcut handlers.
    expect(keyboardInputFromEvent(escape, tracker).isComposing).toBe(true);
    await Promise.resolve();
    for (const surface of ["review", "export", "dialog"] as const) {
      expect(resolveKeyboardAction(surface, {
        ...keyboardInputFromEvent(escape, tracker),
        targetEditable: true, targetTextEditing: true,
      }, "text-editing")).toBeNull();
    }

    // A separate press after cancellation must immediately be allowed to blur.
    expect(resolveKeyboardAction("review", {
      ...keyboardInputFromEvent({ ...escape } as KeyboardEvent, tracker),
      targetEditable: true, targetTextEditing: true,
    }, "text-editing")).toEqual({ type: "deactivate-text-editing" });
  });

  it.each(["review", "waveform", "export", "dialog"] as const)(
    "ignores IME boundary Escape on %s and releases focus on the next completed Escape",
    (surface) => {
      const tracker = createCompositionTracker();
      const target = {} as EventTarget;
      const event = {
        key: "Escape", code: "Escape", keyCode: 229, repeat: false,
        shiftKey: false, altKey: false, ctrlKey: false, metaKey: false,
        isComposing: false, target,
      } as KeyboardEvent;
      const actionFor = (event: KeyboardEvent) => resolveKeyboardAction(surface, {
        ...keyboardInputFromEvent(event, tracker),
        targetEditable: true,
        targetTextEditing: true,
      }, "text-editing");

      // The first IME keydown can precede compositionstart.
      expect(keyboardInputFromEvent(event, tracker).isComposing).toBe(true);
      expect(actionFor(event)).toBeNull();
      tracker.start(target);
      expect(actionFor({ ...event, keyCode: 27 } as KeyboardEvent)).toBeNull();
      // Some IMEs end composition before dispatching the key that ended it.
      tracker.end(target);
      expect(actionFor(event)).toBeNull();
      expect(actionFor({ ...event, keyCode: 27 } as KeyboardEvent)).toEqual({
        type: "deactivate-text-editing",
      });
    },
  );

  it("keeps Escape owned by the IME across composition keydown boundaries", () => {
    const tracker = createCompositionTracker();
    const target = {} as EventTarget;
    const event = {
      key: "Escape", code: "Escape", repeat: false,
      shiftKey: false, altKey: false, ctrlKey: false, metaKey: false,
      isComposing: false, target,
    } as KeyboardEvent;
    tracker.start(target);
    expect(keyboardInputFromEvent(event, tracker).isComposing).toBe(true);
    expect(resolveKeyboardAction("export", keyboardInputFromEvent(event, tracker), "active-dialog")).toBeNull();
    tracker.end(target, true);
    expect(keyboardInputFromEvent(event, tracker).isComposing).toBe(true);
    expect(resolveKeyboardAction("export", keyboardInputFromEvent(event, tracker), "active-dialog")).toBeNull();

    const ordinaryKey = { ...event, key: "j", code: "KeyJ" } as KeyboardEvent;
    expect(keyboardInputFromEvent(ordinaryKey, tracker).isComposing).toBe(false);

    const completedTracker = createCompositionTracker();
    completedTracker.start(target);
    completedTracker.end(target);
    expect(keyboardInputFromEvent(event, completedTracker).isComposing).toBe(false);
  });

  it("keeps Escape owned when cancellation is signaled before compositionend", () => {
    const tracker = createCompositionTracker();
    const target = {} as EventTarget;
    const escape = {
      key: "Escape", code: "Escape", keyCode: 27, repeat: false,
      shiftKey: false, altKey: false, ctrlKey: false, metaKey: false,
      isComposing: false, target,
    } as KeyboardEvent;

    tracker.start(target);
    tracker.cancel(target);
    tracker.end(target, false);

    expect(keyboardInputFromEvent(escape, tracker).isComposing).toBe(true);
    expect(resolveKeyboardAction("export", {
      ...keyboardInputFromEvent(escape, tracker),
      targetEditable: true,
      targetTextEditing: true,
    }, "text-editing")).toBeNull();
  });

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

  it("deactivates text editing without closing its parent context", () => {
    const escape = input({ key: "Escape", targetEditable: true, targetTextEditing: true });
    expect(resolveKeyboardAction("review", escape, "text-editing")).toEqual({ type: "deactivate-text-editing" });
    expect(resolveKeyboardAction("export", escape, "active-dialog")).toEqual({ type: "deactivate-text-editing" });
    expect(resolveKeyboardAction("dialog", escape, "active-dialog")).toEqual({ type: "deactivate-text-editing" });
    expect(resolveKeyboardAction("export", { ...escape, isComposing: true }, "active-dialog")).toBeNull();
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
