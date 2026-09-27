import { createContext, useContext, type ReactNode } from "react";

export type BadgeMode = "auto" | "keyboard" | "xbox";
export type DisplayInputType = "keyboard" | "xbox";
export type UnboundBadgeBehavior = "hide" | "keyboard";

type BindingLookup = { id: string; index: number | null };

type ShortcutDisplaySettings = {
  mode: BadgeMode;
  inputType: DisplayInputType;
  unboundBehavior: UnboundBadgeBehavior;
  bindings: readonly BindingLookup[];
};

export type ResolvedBadge =
  | { kind: "keyboard"; label: string }
  | { kind: "xbox"; index: number }
  | null;

export function resolveShortcutBadge({ mode, inputType, unboundBehavior, keyboard, gamepadIndex, mapped }: {
  mode: BadgeMode;
  inputType: DisplayInputType;
  unboundBehavior: UnboundBadgeBehavior;
  keyboard?: string;
  gamepadIndex?: number | null;
  mapped: boolean;
}): ResolvedBadge {
  const bound = gamepadIndex !== null && gamepadIndex !== undefined;
  const showXbox = mode === "xbox" || (mode === "auto" && inputType === "xbox");
  if (showXbox && bound) return { kind: "xbox", index: gamepadIndex };
  if (keyboard && (!mapped || bound || unboundBehavior === "keyboard")) {
    return { kind: "keyboard", label: keyboard };
  }
  return null;
}

const defaultSettings: ShortcutDisplaySettings = {
  mode: "keyboard",
  inputType: "keyboard",
  unboundBehavior: "hide",
  bindings: [],
};

const ShortcutDisplayContext = createContext<ShortcutDisplaySettings>(defaultSettings);

export function ShortcutDisplayProvider({ mode, inputType, unboundBehavior, bindings, children }: ShortcutDisplaySettings & { children: ReactNode }) {
  return <ShortcutDisplayContext.Provider value={{ mode, inputType, unboundBehavior, bindings }}>
    {children}
  </ShortcutDisplayContext.Provider>;
}

export function useShortcutDisplay(): ShortcutDisplaySettings {
  return useContext(ShortcutDisplayContext);
}

const controlLabels = [
  "A", "B", "X", "Y", "Left shoulder", "Right shoulder",
  "Left trigger", "Right trigger", "Back", "Start", "Left stick",
  "Right stick", "D-pad up", "D-pad down", "D-pad left", "D-pad right", "Home",
];

function controlLabel(index: number): string {
  return controlLabels[index] ?? `Button ${index}`;
}

export function XboxButtonIcon({ index, label }: { index: number; label?: string }) {
  const name = label ?? controlLabel(index);
  const face = index >= 0 && index <= 3 ? controlLabels[index] : null;
  const shoulder = index === 4 ? "LB" : index === 5 ? "RB" : index === 6 ? "LT" : index === 7 ? "RT" : null;
  const isDpad = index >= 12 && index <= 15;
  const isStick = index === 10 || index === 11;
  return <svg width="22" height="22" viewBox="0 0 22 22" role="img" aria-label={name}
    className="inline-block align-text-bottom" focusable="false">
    {face && <>
      <circle cx="11" cy="11" r="9" fill="currentColor" opacity=".18" stroke="currentColor" />
      <text x="11" y="15" textAnchor="middle" fontSize="9" fontWeight="700" fill="currentColor">{face}</text>
    </>}
    {shoulder && <>
      <rect x="1.5" y="5" width="19" height="12" rx="4" fill="currentColor" opacity=".18" stroke="currentColor" />
      <text x="11" y="14" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor">{shoulder}</text>
    </>}
    {isDpad && <>
      <path d="M8 2h6v6h6v6h-6v6H8v-6H2V8h6z" fill="currentColor" opacity=".18" stroke="currentColor" strokeLinejoin="round" />
      <path d={index === 12 ? "M11 5l-2 3h4z" : index === 13 ? "M9 14h4l-2 3z" : index === 14 ? "M5 11l3-2v4z" : "M17 11l-3-2v4z"} fill="currentColor" />
    </>}
    {isStick && <>
      <circle cx="11" cy="11" r="8" fill="currentColor" opacity=".18" stroke="currentColor" />
      <circle cx="11" cy="11" r="3" fill="currentColor" />
    </>}
    {!face && !shoulder && !isDpad && !isStick && <>
      <rect x="2" y="4" width="18" height="14" rx="4" fill="currentColor" opacity=".18" stroke="currentColor" />
      <text x="11" y="14" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor">{index === 8 ? "VIEW" : index === 9 ? "MENU" : "•"}</text>
    </>}
  </svg>;
}

export function ShortcutBadge({ keyboard, bindingId, gamepadIndex, gamepadLabel }: {
  keyboard?: string;
  bindingId?: string;
  gamepadIndex?: number | null;
  gamepadLabel?: string;
}) {
  const settings = useShortcutDisplay();
  const isMapped = bindingId !== undefined || gamepadIndex !== undefined;
  const mappedIndex = bindingId
    ? settings.bindings.find((binding) => binding.id === bindingId)?.index
    : gamepadIndex;
  const index = mappedIndex === undefined ? null : mappedIndex;
  const resolved = resolveShortcutBadge({
    mode: settings.mode,
    inputType: settings.inputType,
    unboundBehavior: settings.unboundBehavior,
    keyboard,
    gamepadIndex: index,
    mapped: isMapped,
  });
  if (resolved?.kind === "xbox") {
    const label = gamepadLabel ?? controlLabel(resolved.index);
    return <kbd className="shortcut-key shortcut-gamepad" aria-label={`${label} controller shortcut`}>
      <XboxButtonIcon index={resolved.index} label={label} />
    </kbd>;
  }
  if (resolved?.kind === "keyboard") {
    return <kbd className="shortcut-key" aria-label={`Keyboard shortcut ${resolved.label}`}>{resolved.label}</kbd>;
  }
  return null;
}
