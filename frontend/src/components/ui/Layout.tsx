import type { ReactNode } from "react";

/** Page title block. Title on the left, actions on the right, the tilted green stroke underneath. */
export function PageHeader({ title, lede, actions }: { title: string; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="rise mb-9 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
      <div className="max-w-[72ch]">
        <h1 className="text-[2.5rem] font-bold leading-tight text-ink">{title}</h1>
        <span aria-hidden className="mt-3 block h-1.5 w-16 -rotate-3 rounded-full bg-primary" />
        {lede ? <p className="mt-4 text-[1.125rem] text-muted">{lede}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </header>
  );
}

/**
 * A titled block of content. Rounded, with a faint green glow that strengthens on hover,
 * and rises in on mount. `flush` removes body padding for tables that should run edge to edge.
 */
export function Panel({
  title,
  aside,
  children,
  flush,
  className = "",
  id,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`panel rise overflow-hidden rounded-card border border-line bg-background ${className}`}>
      {title || aside ? (
        <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-3.5">
          {title ? <h2 className="text-[1.1875rem] font-semibold text-ink">{title}</h2> : <span />}
          {aside ? <div className="flex items-center gap-3 text-[0.9375rem] text-muted">{aside}</div> : null}
        </div>
      ) : null}
      <div className={flush ? "" : "p-6"}>{children}</div>
    </section>
  );
}

/** Label / value pairs laid out as a ruled ledger, values right-aligned. */
export function Ledger({ rows, className = "" }: { rows: { label: ReactNode; value: ReactNode; note?: ReactNode }[]; className?: string }) {
  return (
    <dl className={`divide-y divide-line ${className}`}>
      {rows.map((r, i) => (
        <div key={i} className="flex items-baseline justify-between gap-6 py-2.5">
          <dt className="text-[1rem] text-muted">
            {r.label}
            {r.note ? <span className="mt-0.5 block text-[0.9375rem] text-muted/90">{r.note}</span> : null}
          </dt>
          <dd className="figures text-right text-[1.0625rem] text-ink">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Small heading used inside a panel to group content. */
export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="mb-3 text-sm font-semibold text-ink">{children}</h3>;
}
