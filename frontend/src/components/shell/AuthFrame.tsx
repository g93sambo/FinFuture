import type { ReactNode } from "react";
import { AuthShowcase } from "./AuthShowcase";

/**
 * Shared frame for sign-in and registration.
 * Large screens: moving green showcase on the left half, white form half on the right.
 * Small screens: the showcase becomes a band above the form.
 */
export function AuthFrame({
  title,
  lede,
  children,
  points,
  pointsTitle,
}: {
  title: string;
  lede: ReactNode;
  children: ReactNode;
  points: string[];
  pointsTitle: string;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <AuthShowcase points={points} pointsTitle={pointsTitle} />

      <main className="relative isolate flex overflow-hidden px-6 py-12 sm:px-10 lg:px-16 lg:py-16">
        <span className="auth-ghost" aria-hidden>
          FinFuture
        </span>
        <div className="relative z-10 m-auto w-full max-w-[34rem]">
          <h1 className="auth-rise text-[2.75rem] leading-tight font-bold text-ink sm:text-[3.25rem]" style={{ "--d": 0 } as React.CSSProperties}>
            {title}
          </h1>
          <p className="auth-rise mt-3 text-[1.1875rem] text-muted" style={{ "--d": 1 } as React.CSSProperties}>
            {lede}
          </p>
          <div className="auth-rise mt-9" style={{ "--d": 2 } as React.CSSProperties}>
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
