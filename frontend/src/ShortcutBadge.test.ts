import { describe, expect, it } from "vitest";
import { resolveShortcutBadge } from "./ShortcutBadge";

describe("shortcut badge selection", () => {
  it("starts with Xbox badges in auto mode when a controller is active", () => {
    expect(resolveShortcutBadge({
      mode: "auto", inputType: "xbox", unboundBehavior: "hide", keyboard: "J", gamepadIndex: 13, mapped: true,
    })).toEqual({ kind: "xbox", index: 13 });
  });

  it("switches auto mode back to keyboard after keyboard input", () => {
    expect(resolveShortcutBadge({
      mode: "auto", inputType: "keyboard", unboundBehavior: "hide", keyboard: "J", gamepadIndex: 13, mapped: true,
    })).toEqual({ kind: "keyboard", label: "J" });
  });

  it("honors forced modes and the unbound fallback preference", () => {
    expect(resolveShortcutBadge({
      mode: "keyboard", inputType: "xbox", unboundBehavior: "hide", keyboard: "J", gamepadIndex: 13, mapped: true,
    })).toEqual({ kind: "keyboard", label: "J" });
    expect(resolveShortcutBadge({
      mode: "xbox", inputType: "keyboard", unboundBehavior: "hide", keyboard: "J", gamepadIndex: null, mapped: true,
    })).toBeNull();
    expect(resolveShortcutBadge({
      mode: "xbox", inputType: "keyboard", unboundBehavior: "keyboard", keyboard: "J", gamepadIndex: null, mapped: true,
    })).toEqual({ kind: "keyboard", label: "J" });
  });

  it("shows keyboard badges for actions without a controller button when keyboard badges are showing", () => {
    expect(resolveShortcutBadge({
      mode: "keyboard", inputType: "keyboard", unboundBehavior: "hide", keyboard: "U", gamepadIndex: null, mapped: true,
    })).toEqual({ kind: "keyboard", label: "U" });
    expect(resolveShortcutBadge({
      mode: "auto", inputType: "keyboard", unboundBehavior: "hide", keyboard: "U", gamepadIndex: null, mapped: true,
    })).toEqual({ kind: "keyboard", label: "U" });
    expect(resolveShortcutBadge({
      mode: "auto", inputType: "xbox", unboundBehavior: "hide", keyboard: "U", gamepadIndex: null, mapped: true,
    })).toBeNull();
  });
});
