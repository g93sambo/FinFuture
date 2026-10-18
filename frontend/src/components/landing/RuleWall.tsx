"use client";

import { useEffect, useRef } from "react";

type Tone = "solid" | "soft" | "outline" | "accent";

interface Rule {
  big: string;
  line: string;
  tone: Tone;
  /** Resting tilt in degrees. */
  tilt: number;


}

/** The twelve compliance rules, in plain words. */
const rules: Rule[] = [
  { big: "Your call", line: "Nothing is bought or sold until you say yes. Not one dollar.", tone: "solid", tilt: -2 },
  { big: "Bad day?", line: "One bad day can't sink you. No single company ever holds more than 15% of your money.", tone: "soft", tilt: 1.5 },
  { big: "Still standing", line: "We make sure you're still standing financially at all times. No one industry gets more than 30%.", tone: "outline", tilt: -1 },
  { big: "Real growth", line: "We aim to grow your money steadily, using real numbers, not wishful thinking.", tone: "accent", tilt: 2 },
  { big: "Your pace", line: "We never push more risk than you told us you can live with.", tone: "outline", tilt: 1.5 },
  { big: "3 years", line: "Need the money sooner than that? We keep it safer.", tone: "solid", tilt: -2 },
  { big: "15 min", line: "Your yes expires, so an old decision can't slip through later.", tone: "soft", tilt: 1 },
  { big: "On record", line: "Every decision is saved. Look back at any of it, any time.", tone: "accent", tilt: -1.5 },
];

const toneClass: Record<Tone, string> = {
  solid: "bg-primary text-on-primary",
  soft: "bg-primary-soft text-primary",
  outline: "bg-background text-primary ring-[3px] ring-primary",
  accent: "bg-accent text-on-accent",
};

const never = ["Never trades without you", "Never hides a decision", "Never rushes you"];

export function RuleWall() {
  const wallRef = useRef<HTMLUListElement>(null);

  // Cards fly in, spinning into their tilt, as they scroll into view.
  useEffect(() => {
    const cards = wallRef.current?.querySelectorAll<HTMLElement>(".rule-card");
    if (!cards?.length) return;
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.15 },
    );
    cards.forEach((c) => io.observe(c));
    return () => io.disconnect();
  }, []);

  // 3D tilt that follows the pointer while hovering a card.
  const onMove = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType === "touch") return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--ry", `${(x * 8).toFixed(1)}deg`);
    el.style.setProperty("--rx", `${(-y * 8).toFixed(1)}deg`);
  };
  const onLeave = (e: React.PointerEvent<HTMLElement>) => {
    e.currentTarget.style.setProperty("--rx", "0deg");
    e.currentTarget.style.setProperty("--ry", "0deg");
  };

  const tape = [...never, ...never, ...never, ...never];

  return (
    <div>
      <div className="rule-tape" aria-hidden>
        <div className="rule-tape__track">
          {tape.map((t, i) => (
            <span key={i} className="flex items-center gap-8 px-4">
              {t}
              <span className="text-[1.5em] leading-none">✕</span>
            </span>
          ))}
        </div>
      </div>
      <p className="sr-only">{never.join(". ")}.</p>

      <ul ref={wallRef} className="mx-auto mt-10 grid max-w-[110rem] grid-cols-1 gap-x-7 gap-y-8 px-6 py-10 sm:grid-cols-2 sm:px-10 lg:px-16 xl:grid-cols-4">
        {rules.map((r, i) => (
          <li
            key={r.line}
            tabIndex={0}
            onPointerMove={onMove}
            onPointerLeave={onLeave}
            className={`rule-card @container rounded-feature p-7 outline-none ${toneClass[r.tone]}`}
            style={{ "--tilt": `${r.tilt}deg`, "--i": i } as React.CSSProperties}
          >
            {/* Sized to the card's own width, so it never spills out. */}
            <p className={`leading-[0.95] font-bold tracking-tight ${r.big.length <= 4 ? "text-[clamp(3rem,34cqi,6rem)] whitespace-nowrap" : "text-[clamp(1.75rem,18cqi,4.25rem)]"}`}>{r.big}</p>
            <p className="mt-4 text-[1.0625rem] leading-snug font-medium opacity-90">{r.line}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
