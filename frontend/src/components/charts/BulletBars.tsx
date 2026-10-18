"use client";

import { useState } from "react";

export interface BulletRow {
  label: string;
  /** Fraction 0..1 drawn as the filled bar. */
  value: number;
  /** Optional fraction 0..1 drawn as a thin target tick. */
  target?: number;
  /** Text shown at the right of the row (falls back to the value as %). */
  valueText?: string;
  sublabel?: string;
}

/**
 * Horizontal bars, one hue. A target, when present, is a vertical ink tick,
 * so current vs target never depends on telling two greens apart.
 * Every row carries its number as text.
 */
export function BulletBars({ rows, max, title }: { rows: BulletRow[]; max?: number; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const scaleMax = max ?? Math.max(0.0001, ...rows.map((r) => Math.max(r.value, r.target ?? 0)));
  const hasTarget = rows.some((r) => r.target !== undefined);
  const w = (v: number) => `${Math.max(0, Math.min(1, v / scaleMax)) * 100}%`;

  return (
    <figure>
      <figcaption className="sr-only">{title}</figcaption>
      {hasTarget ? (
        <div className="mb-3 flex items-center gap-5 text-[0.9375rem] text-muted" aria-hidden>
          <span className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-4 bg-primary" /> Current
          </span>
          <span className="flex items-center gap-2">
            <span className="inline-block h-3.5 w-0.5 bg-ink" /> Target
          </span>
        </div>
      ) : null}
      <ul className="space-y-1" role="list">
        {rows.map((r, i) => (
          <li
            key={r.label}
            className={`grid grid-cols-[4.5rem_1fr_auto] items-center gap-3 py-1.5 sm:grid-cols-[6rem_1fr_7.5rem] ${hover === i ? "bg-surface" : ""}`}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="truncate text-sm font-medium text-ink" title={r.sublabel ?? r.label}>
              {r.label}
            </span>
            <span className="relative block h-3.5 bg-chart-track" aria-hidden>
              <span className="absolute inset-y-0 left-0 bg-primary transition-[width] duration-300" style={{ width: w(r.value) }} />
              {r.target !== undefined ? (
                <span className="absolute -inset-y-1 w-0.5 bg-ink" style={{ left: `calc(${w(r.target)} - 1px)` }} />
              ) : null}
            </span>
            <span className="figures text-right text-[0.9375rem] text-ink">
              {r.valueText ?? `${(r.value * 100).toFixed(1)}%`}
              {r.target !== undefined ? <span className="block text-muted sm:inline"> / {(r.target * 100).toFixed(1)}%</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
