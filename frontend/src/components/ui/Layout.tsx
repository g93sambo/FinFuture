import type { ReactNode } from "react";

/** Page title block. Title on the left, actions on the right, a subtle rule underneath. */
export function PageHeader({ title, lede, actions }: { title: string; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-7 flex flex-wrap items-center justify-between gap-x-8 gap-y-4 border-b border-line pb-5">
      <div className="max-w-[64ch]">
        <h1 className="text-[22px] font-bold tracking-tight text-ink sm:text-[25px]">{title}</h1>
        {lede ? <p className="mt-1 text-sm text-muted">{lede}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </header>
  );
}

/**
 * A titled block of content with rounded corners and soft Equify card styling.
 * `flush` removes body padding for tables that should run edge to edge.
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
    <section
      id={id}
      className={`overflow-hidden rounded-card border border-line bg-background shadow-[0_2px_12px_rgba(15,41,34,0.03)] ${className}`}
    >
      {title || aside ? (
        <div className="flex min-h-12 flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          {title ? <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2> : <span />}
          {aside ? <div className="flex items-center gap-3 text-xs text-muted">{aside}</div> : null}
        </div>
      ) : null}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

/** Label / value pairs laid out as a ruled ledger, values right-aligned. */
export function Ledger({ rows, className = "" }: { rows: { label: ReactNode; value: ReactNode; note?: ReactNode }[]; className?: string }) {
  return (
    <dl className={`divide-y divide-line/80 ${className}`}>
      {rows.map((r, i) => (
        <div key={i} className="flex items-baseline justify-between gap-6 py-2.5">
          <dt className="text-sm text-muted">
            {r.label}
            {r.note ? <span className="mt-0.5 block text-[12px] text-muted/85">{r.note}</span> : null}
          </dt>
          <dd className="figures text-right text-[14.5px] font-medium text-ink">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Small heading used inside a panel to group content. */
export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="mb-3 text-sm font-semibold text-ink">{children}</h3>;
}

