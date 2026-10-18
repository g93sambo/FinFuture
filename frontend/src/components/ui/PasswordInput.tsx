"use client";

import { forwardRef, useState, type ComponentProps } from "react";
import { Input } from "./Field";

/** Password field with an eye button that shows or hides what was typed. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<ComponentProps<"input">, "type">>(function PasswordInput(
  { className = "", ...rest },
  ref,
) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="relative block">
      <Input ref={ref} type={visible ? "text" : "password"} className={`pr-14 ${className}`} {...rest} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="absolute top-1/2 right-1.5 grid h-9 w-10 -translate-y-1/2 place-items-center rounded-button text-muted transition-colors hover:bg-surface hover:text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {visible ? null : <path d="M3 3l18 18" />}
        </svg>
      </button>
    </span>
  );
});
