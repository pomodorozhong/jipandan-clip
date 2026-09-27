import type { Ref } from "react";
import type { GamepadStatus } from "./gamepad";

export function gamepadStatusLabel(status: GamepadStatus): string {
  if (!status.apiSupported) return "Unavailable";
  if (status.activeController) return status.pageActive ? "Connected" : "Paused";
  if (status.unsupportedControllers.length > 0) return "Unsupported mapping";
  return "Not connected";
}

export function gamepadStatusMessage(status: GamepadStatus): string {
  if (!status.apiSupported) return "This browser does not expose the Gamepad API.";
  if (status.activeController && !status.pageActive) {
    return "A standard-mapped controller is connected, but controller input is paused while this page is unfocused or hidden.";
  }
  if (status.activeController) return "Connected. Focus this page and press a control to browse, replay, or classify clips.";
  if (status.unsupportedControllers.length > 0) {
    return "A controller is connected, but its layout is not reported as standard. Use a standard-mapped controller; custom layouts are not guessed.";
  }
  return "Connect a standard-mapped controller, focus this page, and press a button to activate controller input.";
}

export default function GamepadControls({ status, onOpenMapping, mappingButtonRef }: {
  status: GamepadStatus;
  onOpenMapping?: () => void;
  mappingButtonRef?: Ref<HTMLButtonElement>;
}) {
  return <section aria-labelledby="gamepad-controls-heading" className="mt-6 rounded-xl border line p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 id="gamepad-controls-heading" className="text-base font-semibold">Gamepad controls</h3>
      <span role="status" aria-live="polite" className="subtle text-xs">{gamepadStatusLabel(status)}</span>
    </div>
    <p className="subtle mt-2 text-sm">{gamepadStatusMessage(status)}</p>
    <p className="subtle mt-4 text-xs">Controller actions pause while typing or this tab is inactive; dialogs use D-pad/left-stick focus, A confirm, and B back. Saving blocks mutating actions while navigation remains available. After reconnecting or changing context, release a held control before pressing it again.</p>
    {onOpenMapping && <button type="button" ref={mappingButtonRef} id="gamepad-mapping-button" onClick={onOpenMapping}
      className="mt-4 rounded-lg border line px-3 py-2 text-sm font-medium hover:bg-[#354b3b]">
      Configure gamepad mapping
    </button>}
  </section>;
}
