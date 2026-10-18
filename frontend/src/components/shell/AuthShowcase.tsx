"use client";

import { useEffect, useRef, useState } from "react";
import { AuroraBackground } from "@/components/landing/AuroraBackground";
import { Wordmark } from "./Wordmark";

const DEFAULT_WORDS = ["growing.", "protected.", "explained.", "in your hands."];
const TILTS = [-3, 2.5, -1.5, 3, -2.5];

/**
 * Green half of the sign-in and registration pages: moving aurora, a cursor spotlight,
 * a headline whose last word keeps changing, and floating glass cards.
 * On small screens it becomes a band above the form and the cards turn into a swipeable row.
 */
export function AuthShowcase({ points, pointsTitle, words = DEFAULT_WORDS }: { points: string[]; pointsTitle: string; words?: string[] }) {
  const [index, setIndex] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % words.length), 2600);
    return () => window.clearInterval(id);
  }, [words.length]);

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = panelRef.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };

  return (
    <div
      ref={panelRef}
      onPointerMove={onMove}
      className="relative isolate flex flex-col overflow-hidden bg-primary px-6 pt-6 pb-8 text-on-primary sm:px-10 lg:min-h-screen lg:px-14 lg:py-10"
    >
      <AuroraBackground />
      <div className="auth-spotlight" aria-hidden />

      <div data-reveal="down" className="relative z-10">
        <Wordmark inverted />
      </div>

      <div className="relative z-10 mt-8 lg:my-auto lg:py-8">
        <p className="text-[2.5rem] leading-[1.02] font-medium sm:text-[3.25rem] lg:text-[3rem] xl:text-[3.75rem]">
          <span data-reveal="tilt" className="mr-[0.25em] inline-block" style={{ "--d": 1 } as React.CSSProperties}>
            Your
          </span>
          <span data-reveal="tilt" className="inline-block" style={{ "--d": 2 } as React.CSSProperties}>
            money,
          </span>
          <br />
          <span data-reveal="pop" className="inline-block" style={{ "--d": 3.5 } as React.CSSProperties}>
            <span key={index} className="auth-word font-bold">
              {words[index]}
            </span>
          </span>
        </p>

        <div className="mt-8 lg:mt-10">
          <p data-reveal="up" style={{ "--d": 5 } as React.CSSProperties} className="text-[0.9375rem] font-semibold tracking-wide text-on-primary/75 uppercase">
            {pointsTitle}
          </p>
          <ul className="-mx-6 mt-4 flex snap-x snap-mandatory scroll-px-6 gap-4 overflow-x-auto px-6 pb-2 [scrollbar-width:none] sm:-mx-10 sm:scroll-px-10 sm:px-10 lg:mx-0 lg:block lg:space-y-5 lg:overflow-visible lg:px-0 lg:pb-0">
            {points.map((p, i) => (
              <li
                key={p}
                data-reveal="right"
                className="w-[16rem] shrink-0 snap-start lg:w-auto lg:max-w-[30rem] lg:odd:ml-0 lg:even:ml-12"
                style={{ "--d": 6 + i } as React.CSSProperties}
              >
                <div
                  className="glass-card rounded-feature px-5 py-4 text-[1.0625rem] leading-snug font-medium lg:py-3 lg:text-[1rem]"
                  style={{ "--tilt": `${TILTS[i % TILTS.length]}deg`, "--dur": `${7 + (i % 3)}s`, "--delay": `${-i * 1.3}s` } as React.CSSProperties}
                >
                  <span className="mr-3 font-bold text-on-primary/60">{i + 1}</span>
                  {p}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
