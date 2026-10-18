import { forwardRef, useId, type ComponentProps, type ReactNode } from "react";

const control =
  "block w-full rounded-control border border-ink/25 bg-background px-4 text-[1.0625rem] text-ink placeholder:text-muted/80 transition-all duration-140 ease-out hover:border-ink/45 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none aria-[invalid=true]:border-danger";

interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
  className?: string;
}

/** Label above, hint or error below. The control is passed in as a render function. */
export function Field({ label, hint, error, children, className = "" }: FieldProps) {
  const id = useId();
  const describedBy = error || hint ? `${id}-note` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-2 block text-[1.0625rem] font-medium text-ink">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {error ? (
        <p id={describedBy} className="mt-1.5 text-[0.9375rem] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={describedBy} className="mt-1.5 text-[0.9375rem] text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, ComponentProps<"input">>(function Input({ className = "", ...rest }, ref) {
  return <input ref={ref} className={`${control} h-12 ${className}`} {...rest} />;
});

export function Select({ className = "", children, ...rest }: ComponentProps<"select">) {
  return (
    <span className="relative block">
      <select className={`${control} h-12 appearance-none pr-9 ${className}`} {...rest}>
        {children}
      </select>
      <svg aria-hidden viewBox="0 0 10 6" className="pointer-events-none absolute top-1/2 right-3 h-1.5 w-2.5 -translate-y-1/2 text-muted">
        <path d="M0 0l5 6 5-6z" fill="currentColor" />
      </svg>
    </span>
  );
}

export const Textarea = forwardRef<HTMLTextAreaElement, ComponentProps<"textarea">>(function Textarea({ className = "", ...rest }, ref) {
  return <textarea ref={ref} className={`${control} py-2.5 ${className}`} {...rest} />;
});

/** Pill-style segmented toggle matching the Equify navigation and filter pills. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full border border-line bg-surface p-1 gap-1">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`h-9 min-w-20 rounded-full px-4 text-sm font-medium transition-all ${
              on ? "bg-primary text-on-primary shadow-xs" : "text-muted hover:text-ink hover:bg-surface-muted"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

