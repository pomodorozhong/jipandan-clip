import { describe, expect, it } from "vitest";
import { actionForShortcut, resolveKeyboardAction, type KeyboardInput } from "./inputActions";
import { CHEATSHEET_SECTIONS, cheatsheetKeyboard } from "./cheatsheet";

const namedCodes: Record<string, string> = {
  Space: "Space", Enter: "Enter", Esc: "Escape", "↑": "ArrowUp", "↓": "ArrowDown",
  ",": "Comma", ".": "Period", "[": "BracketLeft", "]": "BracketRight", "/": "Slash",
};

/** Turns a cheatsheet label such as "Shift+," or "⌘ Enter" into the key press it describes. */
function keyPress(label: string): KeyboardInput {
  let key = label;
  let shiftKey = false;
  let metaKey = false;
  if (key.startsWith("Shift+")) { shiftKey = true; key = key.slice("Shift+".length); }
  if (key.startsWith("⌘ ")) { metaKey = true; key = key.slice("⌘ ".length); }
  if (key === "?") { shiftKey = true; key = "/"; }
  const code = namedCodes[key] ?? (/^[A-Z]$/.test(key) ? `Key${key}` : /^[0-9]$/.test(key) ? `Digit${key}` : null);
  if (!code) throw new Error(`No key code for cheatsheet label ${label}`);
  return {
    key, code, repeat: false, shiftKey, altKey: false, ctrlKey: false, metaKey, isComposing: false,
    targetEditable: false, targetTextEditing: false, targetInteractive: false,
  };
}

// "K / ↑" lists two keys; the "/" key itself is written without spaces.
function keyLabels(keyboard: string): string[] {
  return keyboard.split(" / ");
}

describe("shortcut cheatsheet", () => {
  for (const section of CHEATSHEET_SECTIONS) {
    describe(section.title, () => {
      for (const row of section.rows) {
        const keyboard = cheatsheetKeyboard(row);
        if (!keyboard) continue;
        for (const label of keyLabels(keyboard)) {
          it(`${label} resolves to ${row.label}`, () => {
            const resolved = section.resolvers
              .map(({ surface, context }) => resolveKeyboardAction(surface, keyPress(label), context))
              .filter((action) => action !== null);
            expect(resolved).toContainEqual(actionForShortcut(row.id, "keyboard"));
          });
        }
      }

      it("lists each key and action once", () => {
        const labels = section.rows.flatMap((row) => keyLabels(cheatsheetKeyboard(row) ?? "")).filter(Boolean);
        expect(new Set(labels).size).toBe(labels.length);
        expect(new Set(section.rows.map((row) => row.id)).size).toBe(section.rows.length);
      });
    });
  }
});
