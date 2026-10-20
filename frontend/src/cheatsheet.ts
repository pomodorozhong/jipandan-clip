import { shortcutDefinition, type InputContext, type InputSurface, type ShortcutId } from "./inputActions";

export type CheatsheetSectionId = "triage" | "polish" | "publish" | "dialogs";

export type CheatsheetRow = {
  id: ShortcutId;
  /** The label the screen itself shows for this control. */
  label: string;
};

export type CheatsheetSection = {
  id: CheatsheetSectionId;
  title: string;
  note?: string;
  /** The keyboard handlers active on this screen, used to check every listed key. */
  resolvers: readonly { surface: InputSurface; context: InputContext }[];
  rows: readonly CheatsheetRow[];
};

const nudgeRows: readonly CheatsheetRow[] = [
  { id: "nudge-start-fine-back", label: "Start −10 ms" },
  { id: "nudge-start-fine-forward", label: "Start +10 ms" },
  { id: "nudge-start-coarse-back", label: "Start −100 ms" },
  { id: "nudge-start-coarse-forward", label: "Start +100 ms" },
  { id: "nudge-end-fine-back", label: "End −10 ms" },
  { id: "nudge-end-fine-forward", label: "End +10 ms" },
  { id: "nudge-end-coarse-back", label: "End −100 ms" },
  { id: "nudge-end-coarse-forward", label: "End +100 ms" },
];

const snapRows: readonly CheatsheetRow[] = [
  { id: "snap-start-back", label: "Start to previous word" },
  { id: "snap-start-forward", label: "Start to next word" },
  { id: "snap-end-back", label: "End to previous speech end" },
  { id: "snap-end-forward", label: "End to next speech end" },
];

// Controller-only boundary controls; the cheatsheet lists them only when bound.
const selectedBoundaryRows: readonly CheatsheetRow[] = [
  { id: "trim-select-start", label: "Select start boundary" },
  { id: "trim-select-end", label: "Select end boundary" },
  { id: "trim-nudge-fine-back", label: "Selected boundary −10 ms" },
  { id: "trim-nudge-fine-forward", label: "Selected boundary +10 ms" },
  { id: "trim-nudge-coarse-back", label: "Selected boundary −100 ms" },
  { id: "trim-nudge-coarse-forward", label: "Selected boundary +100 ms" },
];

export const CHEATSHEET_SECTIONS: readonly CheatsheetSection[] = [
  {
    id: "triage",
    title: "Triage",
    resolvers: [{ surface: "review", context: "review" }, { surface: "waveform", context: "review" }],
    rows: [
      { id: "replay", label: "Replay" },
      { id: "play-pause", label: "Play / pause" },
      { id: "group1", label: "Needs work" },
      { id: "group2", label: "Ready" },
      { id: "rejected", label: "Reject" },
      { id: "previous", label: "Back" },
      { id: "next", label: "Pass" },
      { id: "undo", label: "Undo" },
      { id: "show-help", label: "Shortcuts" },
    ],
  },
  {
    id: "polish",
    title: "Polish",
    resolvers: [{ surface: "review", context: "review" }, { surface: "waveform", context: "review" }],
    rows: [
      { id: "previous", label: "Previous clip" },
      { id: "next", label: "Next clip" },
      { id: "replay", label: "Replay from start" },
      { id: "play-pause", label: "Play / pause" },
      { id: "rename", label: "Edit title" },
      { id: "group2", label: "Ready for Publish" },
      { id: "rejected", label: "Reject" },
      ...nudgeRows,
      ...snapRows,
      ...selectedBoundaryRows,
      { id: "trim-snap-back", label: "Selected boundary to previous snap" },
      { id: "trim-snap-forward", label: "Selected boundary to next snap" },
      { id: "open-export", label: "Preview export" },
      { id: "duplicate", label: "Duplicate" },
      { id: "focus-search", label: "Search titles" },
      { id: "jump", label: "Go to #" },
      { id: "undo", label: "Undo" },
      { id: "show-help", label: "Shortcuts" },
    ],
  },
  {
    id: "publish",
    title: "Publish",
    resolvers: [
      { surface: "review", context: "review" },
      { surface: "waveform", context: "review" },
      { surface: "export", context: "active-dialog" },
    ],
    rows: [
      { id: "previous", label: "Previous clip" },
      { id: "next", label: "Next clip" },
      { id: "reference-replay", label: "Replay As is" },
      { id: "reference-play-pause", label: "Play / pause As is" },
      { id: "candidate-replay", label: "Replay candidate" },
      { id: "candidate-play-pause", label: "Play / pause candidate" },
      { id: "export-mode-as-is", label: "As is" },
      { id: "export-mode-trim-edges", label: "Trim edges" },
      { id: "export-mode-trim-all", label: "Trim all" },
      ...nudgeRows,
      ...selectedBoundaryRows,
      { id: "export", label: "Export" },
      { id: "export-next", label: "Export & Next" },
      { id: "reveal-export", label: "Reveal file" },
      { id: "jump", label: "Go to #" },
      { id: "undo", label: "Undo" },
      { id: "show-help", label: "Shortcuts" },
    ],
  },
  {
    id: "dialogs",
    title: "Dialogs",
    note: "Preview export in Polish uses the Publish keys for playback, export mode, and export.",
    resolvers: [{ surface: "dialog", context: "active-dialog" }],
    rows: [{ id: "dialog-close", label: "Close dialog" }],
  },
];

export function cheatsheetKeyboard(row: CheatsheetRow): string | undefined {
  return shortcutDefinition(row.id).keyboard;
}
