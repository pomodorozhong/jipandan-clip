import type { ReactNode, Ref } from "react";
import type { Status } from "./api";
import { ShortcutBadge } from "./ShortcutBadge";

// Shared pieces from the approved step 2 mockup (doc/mockups/step-2-ui):
// one panel, one section header, three button weights, badges, and one stage layout.

export const statusLabels: Record<Status, string> = {
  pending: "Unsorted", group1: "Group 1", group2: "Group 2",
  exported: "Exported", rejected: "Rejected", unsure: "Unsure",
};

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

export function Button({ children, onClick, disabled, variant = "secondary", title, shortcut, shortcutId, buttonRef,
  className = "", ariaLabel, ...rest }: {
  children?: ReactNode; onClick: () => void; disabled?: boolean; variant?: ButtonVariant;
  title?: string; shortcut?: string; shortcutId?: string; buttonRef?: Ref<HTMLButtonElement>;
  className?: string; ariaLabel?: string;
} & Pick<React.ButtonHTMLAttributes<HTMLButtonElement>, "aria-expanded" | "aria-haspopup" | "aria-pressed">) {
  return <button ref={buttonRef} type="button" title={title} disabled={disabled} onClick={onClick} aria-label={ariaLabel}
    className={`btn btn-${variant} ${className}`} {...rest}>
    {children}<ShortcutBadge keyboard={shortcut} bindingId={shortcutId} />
  </button>;
}

export function CountBadge({ children, label }: { children: ReactNode; label?: string }) {
  return <span className="count-badge" aria-label={label}>{children}</span>;
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`clip-tag clip-tag-${status}`}>{statusLabels[status]}</span>;
}

/** A section header strip: a caps title on the left, counts or actions on the right. */
export function SectionHeader({ title, aside, as: Heading = "h2" }: {
  title: ReactNode; aside?: ReactNode; as?: "h1" | "h2" | "h3";
}) {
  return <div className="panel-head">
    <Heading className="eyebrow">{title}</Heading>
    {aside}
  </div>;
}

/** Every surface is this panel; pass `title` for a header strip. */
export function Panel({ title, aside, children, className = "", ariaLabel, headingLevel, panelRef }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; ariaLabel?: string;
  headingLevel?: "h1" | "h2" | "h3"; panelRef?: Ref<HTMLElement>;
}) {
  return <section ref={panelRef} aria-label={ariaLabel} className={`panel ${className}`}>
    {title !== undefined && <SectionHeader title={title} aside={aside} as={headingLevel} />}
    {children}
  </section>;
}

/**
 * The list-plus-main layout shared by Triage, Polish, and Publish: a 300–340 px
 * list column beside a main column that fills the rest, stacked below 900 px.
 * `fill` keeps the layout to the window height so each column scrolls on its own;
 * below 900 px it expects only one column to be visible at a time.
 */
export function StageLayout({ label, list, main, fill = false }: {
  label: string; list: ReactNode; main: ReactNode; fill?: boolean;
}) {
  return <main aria-label={label} className={`grid grid-cols-1 gap-4 p-4 md:gap-5 md:p-5 min-[900px]:grid-cols-[minmax(300px,340px)_minmax(0,1fr)] ${
    fill ? "min-h-0 flex-1 grid-rows-[minmax(0,1fr)] overflow-hidden" : "flex-1 items-start"}`}>
    {list}
    {main}
  </main>;
}
