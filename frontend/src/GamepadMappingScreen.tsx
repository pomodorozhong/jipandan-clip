import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  bindingsForGamepadConfig,
  defaultGamepadBindingConfig,
  findGamepadBindingConflict,
  gamepadControlLabel,
  type GamepadBindingConfig,
  type GamepadBindingId,
  type GamepadStatus,
  STANDARD_GAMEPAD_BUTTON_INDEXES,
} from "./gamepad";
import { ShortcutBadge, XboxButtonIcon } from "./ShortcutBadge";

type CaptureConflict = {
  target: GamepadBindingId;
  index: number;
  conflicting: GamepadBindingId;
};

function readActiveController(status: GamepadStatus): Gamepad | null {
  const descriptor = status.activeController;
  if (!descriptor || typeof navigator === "undefined" || typeof navigator.getGamepads !== "function") return null;
  try {
    return Array.from(navigator.getGamepads()).find((gamepad) => gamepad !== null &&
      gamepad.connected !== false && gamepad.index === descriptor.index && gamepad.mapping === "standard") ?? null;
  } catch {
    return null;
  }
}

function pressedButtons(gamepad: Gamepad | null): Set<number> {
  const pressed = new Set<number>();
  if (!gamepad) return pressed;
  for (const index of STANDARD_GAMEPAD_BUTTON_INDEXES) {
    const button = gamepad.buttons[index];
    if (button?.pressed || (button?.value ?? 0) >= 0.5) pressed.add(index);
  }
  return pressed;
}

function actionLabel(bindings: ReturnType<typeof bindingsForGamepadConfig>, id: GamepadBindingId): string {
  return bindings.find((binding) => binding.id === id)?.actionLabel ?? id;
}

export default function GamepadMappingScreen({ initialConfig, status, onSave, onCancel }: {
  initialConfig: GamepadBindingConfig;
  status: GamepadStatus;
  onSave: (config: GamepadBindingConfig) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<GamepadBindingConfig>(() => ({ ...initialConfig }));
  const [capturingId, setCapturingId] = useState<GamepadBindingId | null>(null);
  const [conflict, setConflict] = useState<CaptureConflict | null>(null);
  const [message, setMessage] = useState("");
  const backButtonRef = useRef<HTMLButtonElement>(null);
  const bindings = useMemo(() => bindingsForGamepadConfig(draft), [draft]);
  const activeController = status.activeController;
  const canCapture = Boolean(activeController && status.pageActive);

  useEffect(() => {
    backButtonRef.current?.focus();
  }, []);

  const capture = useCallback((id: GamepadBindingId, index: number) => {
    setCapturingId(null);
    setMessage("");
    const conflicting = findGamepadBindingConflict(draft, id, index);
    if (conflicting) {
      setConflict({ target: id, index, conflicting });
      return;
    }
    setConflict(null);
    setDraft((current) => ({ ...current, [id]: index }));
    setMessage(`${actionLabel(bindings, id)} will use ${gamepadControlLabel(index)}.`);
  }, [bindings, draft]);

  useEffect(() => {
    if (!capturingId || !activeController || !status.pageActive) return;
    const targetId = capturingId;
    let cancelled = false;
    let frameId: number | null = null;
    let armed = false;
    let previous = new Set<number>();

    function poll() {
      if (cancelled) return;
      const pressed = pressedButtons(readActiveController(status));
      // Require a completely released controller before accepting the next
      // edge. This prevents the button used to enter capture from being saved.
      if (!armed) {
        if (pressed.size === 0) armed = true;
      } else {
        const captured = STANDARD_GAMEPAD_BUTTON_INDEXES.find((index) =>
          pressed.has(index) && !previous.has(index));
        if (captured !== undefined) {
          capture(targetId, captured);
          return;
        }
      }
      previous = pressed;
      frameId = window.requestAnimationFrame(poll);
    }

    frameId = window.requestAnimationFrame(poll);
    return () => {
      cancelled = true;
      if (frameId !== null) window.cancelAnimationFrame(frameId);
    };
  }, [activeController?.id, activeController?.index, activeController?.mapping, capture, capturingId, status]);

  function beginCapture(id: GamepadBindingId) {
    setConflict(null);
    setMessage(`Release all controls, then press the control for ${actionLabel(bindings, id)}.`);
    setCapturingId(id);
  }

  function cancelCapture() {
    setCapturingId(null);
    setMessage("");
  }

  function swapConflict() {
    if (!conflict) return;
    setDraft((current) => ({
      ...current,
      [conflict.target]: conflict.index,
      [conflict.conflicting]: current[conflict.target],
    }));
    setMessage(`${gamepadControlLabel(conflict.index)} is now assigned to ${actionLabel(bindings, conflict.target)}; the previous control was moved to ${actionLabel(bindings, conflict.conflicting)}.`);
    setConflict(null);
  }

  function resetToDefaults() {
    setCapturingId(null);
    setConflict(null);
    setDraft(defaultGamepadBindingConfig());
    setMessage("Validated default bindings restored. Save to apply them.");
  }

  return <div>
    <button ref={backButtonRef} type="button" onClick={onCancel} className="accent mb-4 text-sm">
      ← Back to Settings
    </button>
    <p className="subtle text-sm">Change the controls for every registered review, trim, dialog, and export action. Changes stay local to this browser and are not applied until you save.</p>

    <section className="mt-5 rounded-xl border line p-4" aria-labelledby="active-gamepad-heading">
      <h3 id="active-gamepad-heading" className="text-base font-semibold">Active controller</h3>
      {!status.apiSupported
        ? <p className="subtle mt-2 text-sm">This browser does not expose the Gamepad API.</p>
        : activeController
          ? <p className="subtle mt-2 text-sm"><strong className="text-[#e7eee7]">{activeController.id}</strong> · standard mapping · slot {activeController.index}{status.pageActive ? "" : " · focus this page to capture"}</p>
          : <p className="subtle mt-2 text-sm">Connect and focus a standard-mapped controller to capture controls.</p>}
      {status.unsupportedControllers.length > 0 && <p className="mt-2 text-xs text-[#ead49b]">
        A connected controller uses an unsupported layout. Its controls are not guessed; use the standard-mapped controller shown above.
      </p>}
    </section>

    <section className="mt-5" aria-labelledby="gamepad-mapping-heading">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="gamepad-mapping-heading" className="text-base font-semibold">Shortcut bindings</h3>
        <span className="subtle text-xs">Standard buttons only</span>
      </div>
      <div className="mt-3 grid gap-2">
        {bindings.map((binding) => <div key={binding.id} className="flex items-center justify-between gap-3 rounded-lg border line px-3 py-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">{binding.actionLabel}</div>
            <div className="subtle mt-1 flex flex-wrap items-center gap-2 text-xs">
              <ShortcutBadge keyboard={binding.keyboard} gamepadIndex={binding.index} gamepadLabel={binding.control} />
              {binding.index === null ? <span>Unbound</span> : <XboxButtonIcon index={binding.index} label={binding.control} />}
              <span>· {binding.contexts.includes("active-dialog") ? "dialog" : "review"}</span>
              {binding.keyboard && <span>· keyboard {binding.keyboard}</span>}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {binding.index !== null && <button type="button" disabled={capturingId !== null}
              onClick={() => { setDraft((current) => ({ ...current, [binding.id]: null })); setMessage(`${binding.actionLabel} is now unbound.`); }}
              className="rounded-lg border line px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">Clear</button>}
            <button type="button" disabled={!canCapture || (capturingId !== null && capturingId !== binding.id)}
              onClick={() => capturingId === binding.id ? cancelCapture() : beginCapture(binding.id)}
              className="rounded-lg border line px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">
              {capturingId === binding.id ? "Cancel capture" : "Capture control"}
            </button>
          </div>
        </div>)}
      </div>
    </section>

    {capturingId && <p role="status" aria-live="polite" className="mt-4 rounded-lg border border-[#55744b] bg-[#24372b] p-3 text-sm">
      Release every control, then press a button for <strong>{actionLabel(bindings, capturingId)}</strong>.
    </p>}
    {conflict && <div role="alert" className="mt-4 rounded-lg border border-[#a47745] bg-[#3c3525] p-3 text-sm">
      <p><strong>{gamepadControlLabel(conflict.index)}</strong> is already assigned to {actionLabel(bindings, conflict.conflicting)} in an overlapping context.</p>
      <p className="subtle mt-1 text-xs">Swap the two actions, or reject this capture and choose another control. Reuse across separate contexts is allowed.</p>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={() => setConflict(null)} className="rounded-lg border line px-3 py-2 text-sm">Choose another</button>
        <button type="button" onClick={swapConflict} className="rounded-lg bg-[#b7d69d] px-3 py-2 text-sm font-semibold text-[#1d2d20]">Swap bindings</button>
      </div>
    </div>}
    {message && !capturingId && !conflict && <p role="status" aria-live="polite" className="subtle mt-4 text-sm">{message}</p>}

    <div className="mt-6 flex flex-wrap items-center justify-between gap-2">
      <button type="button" onClick={resetToDefaults} className="rounded-lg border line px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">Reset to defaults</button>
      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="rounded-lg border line px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">Cancel</button>
        <button type="button" disabled={conflict !== null || capturingId !== null} onClick={() => onSave(draft)} className="rounded-lg bg-[#b7d69d] px-4 py-2 text-sm font-semibold text-[#1d2d20] hover:bg-[#d4ecbe]">Save bindings</button>
      </div>
    </div>
  </div>;
}
