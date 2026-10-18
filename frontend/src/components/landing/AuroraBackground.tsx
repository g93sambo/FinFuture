/**
 * Animated abstract background in shades of the primary green.
 * Purely decorative: hidden from screen readers, ignores pointer events,
 * and holds still when the visitor has "reduce motion" switched on.
 * Colours and motion live in globals.css (.aurora*) and theme.ts.
 */

/** A wave that repeats every 600 units, so a 2400-wide strip can loop seamlessly. */
function wavePath(y: number, amp: number, phase: number): string {
  const period = 600;
  let d = `M ${-phase} ${y}`;
  for (let x = -phase; x < 2400 + period; x += period) {
    d += ` C ${x + period * 0.25} ${y - amp}, ${x + period * 0.25} ${y - amp}, ${x + period * 0.5} ${y}`;
    d += ` S ${x + period * 0.75} ${y + amp}, ${x + period} ${y}`;
  }
  return d;
}

const fastLines = [
  { y: 120, amp: 38, phase: 0 },
  { y: 190, amp: 52, phase: 80 },
  { y: 270, amp: 30, phase: 160 },
  { y: 360, amp: 60, phase: 40 },
  { y: 450, amp: 42, phase: 220 },
];
const slowLines = [
  { y: 80, amp: 70, phase: 300 },
  { y: 300, amp: 90, phase: 120 },
  { y: 520, amp: 75, phase: 420 },
];

function Lines({ lines, slow }: { lines: { y: number; amp: number; phase: number }[]; slow?: boolean }) {
  return (
    <svg
      className={`aurora__lines ${slow ? "aurora__lines--slow" : ""}`}
      viewBox="0 0 2400 600"
      preserveAspectRatio="none"
      aria-hidden
      focusable="false"
    >
      {lines.map((l) => (
        <path key={`${l.y}-${l.phase}`} d={wavePath(l.y, l.amp, l.phase)} fill="none" stroke="currentColor" strokeWidth={slow ? 1.5 : 1} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}

export function AuroraBackground() {
  return (
    <div className="aurora" aria-hidden>
      <span className="aurora__blob aurora__blob--deep" />
      <span className="aurora__blob aurora__blob--mid" />
      <span className="aurora__blob aurora__blob--accent" />
      <span className="aurora__blob aurora__blob--highlight" />
      <span className="aurora__blob aurora__blob--light" />
      <span className="aurora__swirl" />
      <Lines lines={slowLines} slow />
      <Lines lines={fastLines} />
      <span className="aurora__veil" />
      <span className="aurora__grain" />
    </div>
  );
}
