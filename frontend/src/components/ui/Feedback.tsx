import type { ReactNode } from "react";

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

const tagTones: Record<Tone, string> = {
  neutral: "border-line bg-surface text-ink",
  brand: "border-primary/30 bg-primary-soft text-primary",
  success: "border-success/30 bg-success-soft text-success",
  warning: "border-warning/30 bg-warning-soft text-warning",
  danger: "border-danger/30 bg-danger-soft text-danger",
};

/** Square status label. Always carries words, never colour alone. */
export function Tag({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex h-6 items-center border px-2 text-[12.5px] font-medium leading-none whitespace-nowrap ${tagTones[tone]} ${className}`}>
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
      className={`flex flex-wrap items-start justify-between gap-x-6 gap-y-3 border px-4 py-3 ${noticeTones[tone]} ${className}`}
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

/** Plain loading line. No spinners, no pulsing. */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="py-10 text-sm text-muted" role="status">
      {label}…
    </p>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="border border-dashed border-line px-6 py-10">
      <p className="font-medium text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-[60ch] text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
