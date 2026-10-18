"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Tone = "solid" | "outline" | "soft";

interface Feature {
  label: string;
  detail: string;
  /** Small resting offset (px) so the cloud looks scattered rather than gridded. */
  ox: number;
  oy: number;
  size: "lg" | "md" | "sm";
  tone: Tone;
  /** Float cycle length in seconds; different values keep the chips out of step. */
  dur: number;
}

const features: Feature[] = [
  { label: "Learns your goals", detail: "A short chat about your life, income and plans shapes every suggestion.", ox: -14, oy: 4, size: "lg", tone: "solid", dur: 7 },
  { label: "Real market data", detail: "Live prices and economic figures, never guesses or hype.", ox: 10, oy: -6, size: "md", tone: "outline", dur: 9 },
  { label: "Simple advice", detail: "Every recommendation comes with a clear reason you can follow.", ox: 6, oy: 8, size: "md", tone: "soft", dur: 8 },
  { label: "You approve every trade", detail: "Nothing is bought or sold until you say yes.", ox: -8, oy: -4, size: "lg", tone: "solid", dur: 10 },
  { label: "Spots emotional decisions", detail: "Notices panic or hype in what you say and suggests a pause.", ox: 12, oy: 6, size: "md", tone: "outline", dur: 7.5 },
  { label: "Compares funds for you", detail: "Ranks funds on cost, size and track record, then tells you which fits.", ox: -10, oy: -8, size: "sm", tone: "soft", dur: 8.5 },
  { label: "Builds your portfolio", detail: "Spreads your money sensibly, based on how much risk suits you.", ox: 4, oy: 6, size: "lg", tone: "soft", dur: 9.5 },
  { label: "Safety checks every step", detail: "Twelve written rules are checked before you see any advice.", ox: -6, oy: -2, size: "md", tone: "solid", dur: 7 },
  { label: "No hype, just facts", detail: "Growth plans built on real numbers, never pressure to act fast.", ox: 14, oy: 4, size: "md", tone: "outline", dur: 8 },
  { label: "Every action recorded", detail: "A permanent record of every decision, so nothing happens behind your back.", ox: -4, oy: -6, size: "sm", tone: "soft", dur: 9 },
];

const sizeClass: Record<Feature["size"], string> = {
  lg: "px-5 py-2.5 text-[1.125rem]",
  md: "px-4 py-2 text-[1rem]",
  sm: "px-3.5 py-2 text-[0.9375rem]",
};

const toneClass: Record<Tone, string> = {
  solid: "bg-primary text-on-primary",
  outline: "bg-background text-primary ring-2 ring-primary/50",
  soft: "bg-primary-soft text-primary",
};

const PUSH_RADIUS = 170; // px: how close the pointer must be to nudge a chip
const PUSH_MAX = 26; // px: furthest a chip moves away from the pointer

export function FeatureCloud() {
  const [active, setActive] = useState<number | null>(null);
  const cloudRef = useRef<HTMLDivElement>(null);
  const chipRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const frame = useRef<number | null>(null);
  const reduceMotion = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reduceMotion.current = mq.matches;
    const onChange = (e: MediaQueryListEvent) => (reduceMotion.current = e.matches);
    mq.addEventListener("change", onChange);
    return () => {
      mq.removeEventListener("change", onChange);
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, []);

  // Chips drift away from the pointer, strongest when it is closest.
  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (reduceMotion.current || e.pointerType === "touch") return;
    const px = e.clientX;
    const py = e.clientY;
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      chipRefs.current.forEach((el) => {
        if (!el) return;
        const r = el.getBoundingClientRect();
        const dx = r.left + r.width / 2 - px;
        const dy = r.top + r.height / 2 - py;
        const dist = Math.hypot(dx, dy) || 1;
        const strength = Math.max(0, 1 - dist / PUSH_RADIUS);
        el.style.setProperty("--push-x", `${((dx / dist) * PUSH_MAX * strength).toFixed(1)}px`);
        el.style.setProperty("--push-y", `${((dy / dist) * PUSH_MAX * strength).toFixed(1)}px`);
      });
    });
  }, []);

  const onPointerLeave = useCallback(() => {
    if (frame.current) cancelAnimationFrame(frame.current);
    chipRefs.current.forEach((el) => {
      el?.style.setProperty("--push-x", "0px");
      el?.style.setProperty("--push-y", "0px");
    });
    setActive(null);
  }, []);

  const current = active !== null ? features[active] : null;

  return (
    <div>
      <div
        ref={cloudRef}
        onPointerMove={onPointerMove}
        onPointerLeave={onPointerLeave}
        className="flex flex-wrap items-center justify-center gap-x-6 gap-y-9 py-4 lg:gap-y-6"
        role="list"
        aria-label="What FinFuture does for you"
      >
        {features.map((f, i) => (
          <span
            key={f.label}
            ref={(el) => {
              chipRefs.current[i] = el;
            }}
            role="listitem"
            className="feature-chip"
            style={{ "--ox": `${f.ox}px`, "--oy": `${f.oy}px`, "--dur": `${f.dur}s`, "--delay": `${-i * 0.9}s` } as React.CSSProperties}
          >
            <button
              type="button"
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onClick={() => setActive(i)}
              aria-describedby={active === i ? "feature-cloud-detail" : undefined}
              aria-pressed={active === i}
              className={`feature-chip__body rounded-feature font-bold whitespace-nowrap outline-none ${sizeClass[f.size]} ${toneClass[f.tone]} ${
                active === i ? "is-active" : ""
              }`}
            >
              {f.label}
            </button>
          </span>
        ))}
      </div>

      <p id="feature-cloud-detail" aria-live="polite" className="mt-4 min-h-[3.5rem] max-w-[44ch] text-[1.125rem] text-ink">
        {current ? (
          <>
            <span className="font-bold text-primary">{current.label}.</span> {current.detail}
          </>
        ) : (
          <span className="text-muted">Point at or tap any feature to see what it means for you.</span>
        )}
      </p>
    </div>
  );
}
