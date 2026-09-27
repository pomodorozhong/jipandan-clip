import { GAMEPAD_BINDINGS, type GamepadStatus } from "./gamepad";

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

export default function GamepadControls({ status }: { status: GamepadStatus }) {
  return <section aria-labelledby="gamepad-controls-heading" className="mt-6 rounded-xl border line p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 id="gamepad-controls-heading" className="text-base font-semibold">Gamepad controls</h3>
      <span role="status" aria-live="polite" className="subtle text-xs">{gamepadStatusLabel(status)}</span>
    </div>
    <p className="subtle mt-2 text-sm">{gamepadStatusMessage(status)}</p>
    <div className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
      {GAMEPAD_BINDINGS.map((binding) => <div key={binding.index} className="contents">
        <kbd className="accent mono">{binding.control}</kbd><span>{binding.actionLabel}</span>
      </div>)}
    </div>
    <p className="subtle mt-4 text-xs">Controller actions pause while typing, a dialog is open, or this tab is inactive; saving blocks mutating actions while navigation remains available. After reconnecting or changing context, release a held control before pressing it again.</p>
  </section>;
}
