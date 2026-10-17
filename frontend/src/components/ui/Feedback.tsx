import type { ReactNode } from "react";

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

const tagTones: Record<Tone, string> = {
  neutral: "border-line bg-surface text-ink",
  brand: "border-primary/30 bg-primary-soft text-primary",
  success: "border-success/30 bg-success-soft text-success",
  warning: "border-warning/30 bg-warning-soft text-warning",
  danger: "border-danger/30 bg-danger-soft text-danger",
};

/** Pill status label. Always carries words, never colour alone. */
export function Tag({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex h-6 items-center rounded-full border px-2.5 text-[11.5px] font-medium leading-none whitespace-nowrap ${tagTones[tone]} ${className}`}>
      {children}
    </span>
  );
}

const noticeTones: Record<Tone, string> = {
  neutral: "border-line bg-surface",
  brand: "border-primary/25 bg-primary-soft",
  success: "border-success/30 bg-success-soft",
  warning: "border-warning/30 bg-warning-soft",
  danger: "border-danger/30 bg-danger-soft",
};
const noticeTitle: Record<Tone, string> = {
  neutral: "text-ink",
  brand: "text-primary",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export function Notice({
  tone = "neutral",
  title,
  children,
  action,
  className = "",
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={`flex flex-wrap items-start justify-between gap-x-6 gap-y-3 rounded-card border px-4 py-3.5 ${noticeTones[tone]} ${className}`}
    >
      <div className="min-w-0 max-w-[70ch]">
        {title ? <p className={`text-sm font-semibold ${noticeTitle[tone]}`}>{title}</p> : null}
        {children ? <div className="text-sm text-ink">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <Notice
      tone="danger"
      title="That did not work"
      action={
        onRetry ? (
          <button onClick={onRetry} className="text-sm font-medium text-danger underline underline-offset-4">
            Try again
          </button>
        ) : null
      }
    >
      {error}
    </Notice>
  );
}

/** Skeleton block that matches content layout to eliminate layout shift */
export function Skeleton({
  className = "",
  rounded = "rounded-control",
  width,
  height,
  style,
}: {
  className?: string;
  rounded?: string;
  width?: string | number;
  height?: string | number;
  style?: import("react").CSSProperties;
}) {
  const customStyle: import("react").CSSProperties = {
    ...(width !== undefined ? { width } : {}),
    ...(height !== undefined ? { height } : {}),
    ...style,
  };
  return (
    <div
      aria-hidden
      className={`skeleton-shimmer ${rounded} ${!height && !customStyle.height ? "h-4" : ""} ${
        !width && !customStyle.width ? "w-full" : ""
      } ${className}`}
      style={customStyle}
    />
  );
}

export function TableSkeleton({
  rows = 4,
  cols = 4,
  columns,
}: {
  rows?: number;
  cols?: number;
  columns?: number;
}) {
  const count = columns ?? cols;
  return (
    <div className="space-y-3 p-5" aria-busy="true" aria-label="Loading content">
      <Skeleton className="h-6 w-1/3" />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-4">
            {Array.from({ length: count }).map((_, c) => (
              <Skeleton key={c} className="h-5 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Plain loading line with subtle spinner and stage indication */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-sm text-muted animate-fade-in" role="status">
      <svg className="h-4 w-4 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <span>{label}…</span>
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-card border border-dashed border-line bg-surface/40 px-6 py-10">
      <p className="font-semibold text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-[60ch] text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

