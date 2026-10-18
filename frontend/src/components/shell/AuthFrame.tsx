import type { ReactNode } from "react";
import { RevealOnScroll } from "@/components/landing/Reveal";
import { AuthShowcase } from "./AuthShowcase";

/**
 * Shared frame for sign-in and registration.
 * Large screens: moving green showcase on the left half, white form half on the right.
 * Small screens: the showcase becomes a band above the form.
 * Entrance animations use the same data-reveal system as the homepage.
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
      <RevealOnScroll />
      <AuthShowcase points={points} pointsTitle={pointsTitle} />

      <main className="relative isolate flex overflow-hidden px-6 py-12 sm:px-10 lg:px-16 lg:py-16">
        <span className="auth-ghost" data-reveal="drift" style={{ "--d": 4 } as React.CSSProperties} aria-hidden>
          FinFuture
        </span>
        <div className="relative z-10 m-auto w-full max-w-[34rem]">
          <h1 className="text-[2.75rem] leading-tight font-bold text-ink sm:text-[3.25rem]">
            {title.split(" ").map((w, i) => (
              <span key={i} data-reveal="tilt" className="mr-[0.25em] inline-block" style={{ "--d": 2 + i } as React.CSSProperties}>
                {w}
              </span>
            ))}
          </h1>
          <p data-reveal="up" className="mt-3 text-[1.1875rem] text-muted" style={{ "--d": 4 } as React.CSSProperties}>
            {lede}
          </p>
          <div data-reveal="fields" className="mt-9">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}

