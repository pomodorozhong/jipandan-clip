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

function gamepadStatusDotColor(status: GamepadStatus): string {
  if (status.activeController) return status.pageActive ? "#6fcf8b" : "#d8d19c";
  if (status.apiSupported && status.unsupportedControllers.length > 0) return "#d8d19c";
  return "#66756e";
}

export function GamepadStatusBadge({ status }: { status: GamepadStatus }) {
  return <span role="status" aria-live="polite" className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#d6e0da]">
    <span aria-hidden="true" className="status-dot" style={{ background: gamepadStatusDotColor(status) }} />
    {gamepadStatusLabel(status)}
  </span>;
}

// One line for dialogs outside Settings; the full controller options live in Settings > Controller.
export default function GamepadStatusLine({ status, onOpenSettings }: {
  status: GamepadStatus;
  onOpenSettings: () => void;
}) {
  return <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t line pt-3">
    <span className="inline-flex items-center gap-2 text-sm">
      <span className="subtle">Controller</span><GamepadStatusBadge status={status} />
    </span>
    <button type="button" onClick={onOpenSettings} className="btn btn-quiet">Controller settings →</button>
  </div>;
}
