import GamepadControls from "./GamepadControls";
import type { GamepadStatus } from "./gamepad";

export default function SettingsScreen({ detectLeadingSilence, showOriginalStart,
  gamepadStatus, onDetectLeadingSilenceChange, onShowOriginalStartChange }: {
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  gamepadStatus: GamepadStatus;
  onDetectLeadingSilenceChange: (enabled: boolean) => void;
  onShowOriginalStartChange: (enabled: boolean) => void;
}) {
  return <div>
    <p className="subtle mb-5 text-sm">These settings are saved in this browser.</p>
    <section>
      <h3 className="mb-4 text-base font-semibold">Clip timing</h3>
      <label className="flex cursor-pointer items-start gap-3 border-b line pb-4">
        <input type="checkbox" checked={detectLeadingSilence}
          onChange={(event) => onDetectLeadingSilenceChange(event.target.checked)} className="mt-1" />
        <span>
          <strong className="block text-sm">Detect leading silence</strong>
          <span className="subtle mt-1 block text-sm">Analyze clips that still use their SRT start in the background and move them to the first sustained audio activity. You can restore the SRT start from the nudging screen.</span>
        </span>
      </label>
      <label className="flex cursor-pointer items-start gap-3 pt-4">
        <input type="checkbox" checked={showOriginalStart}
          onChange={(event) => onShowOriginalStartChange(event.target.checked)} className="mt-1" />
        <span>
          <strong className="block text-sm">Show original start time on waveform</strong>
          <span className="subtle mt-1 block text-sm">Draw the SRT start as a separate marker in the waveform views.</span>
        </span>
      </label>
    </section>
    <GamepadControls status={gamepadStatus} />
  </div>;
}
