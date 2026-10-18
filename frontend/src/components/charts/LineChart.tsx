"use client";

import { useMemo, useState } from "react";

export interface LinePoint {
  x: number;
  y: number;
  label: string;
  /** Extra line for the hover readout. */
  detail?: string;
}

interface Props {
  points: LinePoint[];
  title: string;
  xLabel: string;
  yLabel: string;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  /** Index of a point to mark (e.g. the recommended portfolio). */
  highlight?: number;
  highlightLabel?: string;
  /** Draw markers on every point (frontier) or only on hover (curve). */
  markers?: boolean;
  /** Use point labels as x tick labels (categorical spacing). */
  categoricalX?: boolean;
  height?: number;
}

const W = 640;
const PAD = { top: 16, right: 20, bottom: 40, left: 56 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min];
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? step0;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

/** Single-series line with a crosshair readout. One axis, recessive grid, 2px line. */
export function LineChart({
  points,
  title,
  xLabel,
  yLabel,
  formatX,
  formatY,
  highlight,
  highlightLabel,
  markers,
  categoricalX,
  height = 260,
}: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const H = height;
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;

  const geo = useMemo(() => {
    const xs = categoricalX ? points.map((_, i) => i) : points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    let yMin = Math.min(...ys);
    let yMax = Math.max(...ys);
    const padY = (yMax - yMin || Math.abs(yMax) || 1) * 0.12;
    yMin -= padY;
    yMax += padY;
    const sx = (v: number) => PAD.left + ((v - xMin) / (xMax - xMin || 1)) * iw;
    const sy = (v: number) => PAD.top + ih - ((v - yMin) / (yMax - yMin || 1)) * ih;
    const coords = points.map((p, i) => ({ cx: sx(categoricalX ? i : p.x), cy: sy(p.y) }));
    return { coords, sy, sx, yTicks: niceTicks(yMin, yMax), xTicks: categoricalX ? [] : niceTicks(xMin, xMax, 5) };
  }, [points, categoricalX, iw, ih]);

  if (points.length === 0) return null;
  const path = geo.coords.map((c, i) => `${i ? "L" : "M"}${c.cx.toFixed(1)},${c.cy.toFixed(1)}`).join("");

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * iw + PAD.left;
    let best = 0;
    geo.coords.forEach((c, i) => {
      if (Math.abs(c.cx - x) < Math.abs(geo.coords[best].cx - x)) best = i;
    });
    setHover(best);
  };

  const hp = hover !== null ? points[hover] : null;
  const hc = hover !== null ? geo.coords[hover] : null;

  return (
    <figure className="relative">
      <figcaption className="sr-only">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={title}>
        {geo.yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PAD.left} x2={W - PAD.right} y1={geo.sy(t)} y2={geo.sy(t)} className="stroke-chart-grid" strokeWidth={1} />
            <text x={PAD.left - 8} y={geo.sy(t)} dy="0.32em" textAnchor="end" className="fill-muted figures text-[0.8125rem]">
              {formatY(t)}
            </text>
          </g>
        ))}
        {categoricalX
          ? points.map((p, i) => (
              <text key={p.label} x={geo.coords[i].cx} y={H - PAD.bottom + 18} textAnchor="middle" className="fill-muted figures text-[0.8125rem]">
                {p.label}
              </text>
            ))
          : geo.xTicks.map((t) => (
              <text key={`x${t}`} x={geo.sx(t)} y={H - PAD.bottom + 18} textAnchor="middle" className="fill-muted figures text-[0.8125rem]">
                {formatX(t)}
              </text>
            ))}
        <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top + ih} y2={PAD.top + ih} className="stroke-ink/40" strokeWidth={1} />
        <text x={PAD.left + iw / 2} y={H - 4} textAnchor="middle" className="fill-muted text-[0.8125rem]">
          {xLabel}
        </text>
        <text transform={`translate(12 ${PAD.top + ih / 2}) rotate(-90)`} textAnchor="middle" className="fill-muted text-[0.8125rem]">
          {yLabel}
        </text>

        <path d={path} fill="none" className="stroke-primary" strokeWidth={2} strokeLinejoin="round" />
        {markers
          ? geo.coords.map((c, i) => <circle key={i} cx={c.cx} cy={c.cy} r={4} className="fill-primary stroke-background" strokeWidth={2} />)
          : null}
        {highlight !== undefined && geo.coords[highlight] ? (
          <g>
            <rect
              x={geo.coords[highlight].cx - 6}
              y={geo.coords[highlight].cy - 6}
              width={12}
              height={12}
              className="fill-background stroke-ink"
              strokeWidth={2}
            />
            {highlightLabel ? (
              <text x={geo.coords[highlight].cx + 10} y={geo.coords[highlight].cy - 10} className="fill-ink text-[0.8125rem] font-medium">
                {highlightLabel}
              </text>
            ) : null}
          </g>
        ) : null}

        {hc ? (
          <g pointerEvents="none">
            <line x1={hc.cx} x2={hc.cx} y1={PAD.top} y2={PAD.top + ih} className="stroke-ink/50" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hc.cx} cy={hc.cy} r={5} className="fill-primary stroke-background" strokeWidth={2} />
          </g>
        ) : null}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={iw}
          height={ih}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          style={{ touchAction: "none" }}
        />
      </svg>
      {hp && hc ? (
        <div
          className="pointer-events-none absolute z-10 border border-ink bg-background px-2.5 py-1.5 text-[0.875rem] text-ink"
          style={{
            left: `${(hc.cx / W) * 100}%`,
            top: `${(hc.cy / H) * 100}%`,
            transform: `translate(${hc.cx > W * 0.65 ? "calc(-100% - 12px)" : "12px"}, -50%)`,
          }}
        >
          <p className="font-medium">{hp.label}</p>
          <p className="figures text-muted">
            {yLabel}: {formatY(hp.y)}
          </p>
          {!categoricalX ? (
            <p className="figures text-muted">
              {xLabel}: {formatX(hp.x)}
            </p>
          ) : null}
          {hp.detail ? <p className="text-muted">{hp.detail}</p> : null}
        </div>
      ) : null}
    </figure>
  );
}
