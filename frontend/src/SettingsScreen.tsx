import type { Ref } from "react";
import GamepadControls from "./GamepadControls";
import {
  GAMEPAD_REPEAT_DELAY_MAX_MS,
  GAMEPAD_REPEAT_DELAY_MIN_MS,
  GAMEPAD_REPEAT_DELAY_STEP_MS,
  type GamepadButtonBinding,
  type GamepadStatus,
} from "./gamepad";
import type { BadgeMode, UnboundBadgeBehavior } from "./ShortcutBadge";

export default function SettingsScreen({ detectLeadingSilence, showOriginalStart,
  gamepadStatus, gamepadBindings, gamepadMappingButtonRef, onOpenGamepadMapping,
  onDetectLeadingSilenceChange, onShowOriginalStartChange, badgeMode, unboundBadgeBehavior,
  onBadgeModeChange, onUnboundBadgeBehaviorChange, gamepadRepeatDelayMs,
  onGamepadRepeatDelayChange }: {
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  gamepadStatus: GamepadStatus;
  gamepadBindings: readonly GamepadButtonBinding[];
  gamepadMappingButtonRef?: Ref<HTMLButtonElement>;
  onOpenGamepadMapping: () => void;
  onDetectLeadingSilenceChange: (enabled: boolean) => void;
  onShowOriginalStartChange: (enabled: boolean) => void;
  badgeMode: BadgeMode;
  unboundBadgeBehavior: UnboundBadgeBehavior;
  onBadgeModeChange: (mode: BadgeMode) => void;
  onUnboundBadgeBehaviorChange: (behavior: UnboundBadgeBehavior) => void;
  gamepadRepeatDelayMs: number;
  onGamepadRepeatDelayChange: (delayMs: number) => void;
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
    <section className="mt-6 border-t line pt-5">
      <h3 className="mb-4 text-base font-semibold">Controller input</h3>
      <label className="block text-sm">
        <span className="flex items-center justify-between gap-3 font-medium">
          <span>Debounce time</span>
          <output className="mono subtle" aria-live="polite">{gamepadRepeatDelayMs} ms</output>
        </span>
        <input type="range" min={GAMEPAD_REPEAT_DELAY_MIN_MS} max={GAMEPAD_REPEAT_DELAY_MAX_MS}
          step={GAMEPAD_REPEAT_DELAY_STEP_MS} value={gamepadRepeatDelayMs}
          onChange={(event) => onGamepadRepeatDelayChange(Number(event.target.value))}
          className="mt-3 w-full accent-[#b7d69d]" />
        <span className="subtle mt-1 block text-xs">Delay before a held navigation or stick control repeats. Lower values respond faster; higher values filter accidental holds.</span>
      </label>
    </section>
    <section className="mt-6 border-t line pt-5">
      <h3 className="mb-4 text-base font-semibold">Shortcut badges</h3>
      <label className="mb-4 block text-sm">
        <span className="font-medium">Badge display</span>
        <select value={badgeMode} onChange={(event) => onBadgeModeChange(event.target.value as BadgeMode)}
          className="mt-1 block w-full rounded-lg border line bg-[#101816] px-3 py-2">
          <option value="auto">Auto — last used input</option>
          <option value="keyboard">Keyboard</option>
          <option value="xbox">Xbox controller</option>
        </select>
        <span className="subtle mt-1 block text-xs">Auto starts with Xbox badges when a standard controller is connected, then follows the last meaningful input.</span>
      </label>
      <label className="block text-sm">
        <span className="font-medium">Unbound shortcut badges</span>
        <select value={unboundBadgeBehavior} onChange={(event) => onUnboundBadgeBehaviorChange(event.target.value as UnboundBadgeBehavior)}
          className="mt-1 block w-full rounded-lg border line bg-[#101816] px-3 py-2">
          <option value="hide">Hide the badge</option>
          <option value="keyboard">Fall back to keyboard shortcut</option>
        </select>
        <span className="subtle mt-1 block text-xs">New actions remain unbound until you capture a controller button.</span>
      </label>
    </section>
    <GamepadControls status={gamepadStatus} bindings={gamepadBindings}
      mappingButtonRef={gamepadMappingButtonRef} onOpenMapping={onOpenGamepadMapping} />
  </div>;
}
