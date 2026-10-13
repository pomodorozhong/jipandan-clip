import { bindingsForGamepadConfig, publishGamepadBindings, type GamepadBindingConfig } from "./gamepad";
import { CHEATSHEET_SECTIONS, cheatsheetKeyboard } from "./cheatsheet";
import { XboxButtonIcon } from "./ShortcutBadge";

/**
 * Keyboard help grouped by screen. Keyboard and controller badges sit in fixed
 * columns, so a row without one of them keeps an empty cell instead of shifting.
 */
export default function ShortcutCheatsheet({ config }: { config: GamepadBindingConfig }) {
  const reviewBindings = bindingsForGamepadConfig(config);
  const publishBindings = publishGamepadBindings(config);
  return <div className="space-y-5">
    {CHEATSHEET_SECTIONS.map((section) => {
      const bindings = section.id === "publish" ? publishBindings : reviewBindings;
      const rows = section.rows.map((row) => ({
        ...row,
        keyboard: cheatsheetKeyboard(row),
        index: bindings.find((binding) => binding.id === row.id)?.index ?? null,
      })).filter((row) => row.keyboard || row.index !== null);
      return <section key={section.id} aria-labelledby={`shortcuts-${section.id}`}>
        <h3 id={`shortcuts-${section.id}`} className="subtle mb-2 text-[11px] font-bold uppercase tracking-[.15em]">{section.title}</h3>
        <table className="w-full table-fixed text-sm">
          <colgroup><col /><col className="w-28" /><col className="w-12" /></colgroup>
          <thead className="sr-only"><tr><th>Action</th><th>Keyboard</th><th>Controller</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={row.id}>
              <td className="py-1 pr-2">{row.label}</td>
              <td className="py-1">{row.keyboard && <kbd className="shortcut-key" aria-label={`Keyboard shortcut ${row.keyboard}`}>{row.keyboard}</kbd>}</td>
              <td className="py-1">{row.index !== null && <kbd className="shortcut-key shortcut-gamepad">
                <XboxButtonIcon index={row.index} />
              </kbd>}</td>
            </tr>)}
          </tbody>
        </table>
        {section.note && <p className="subtle mt-1 text-xs">{section.note}</p>}
      </section>;
    })}
  </div>;
}
