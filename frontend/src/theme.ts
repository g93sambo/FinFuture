/**
 * theme.ts: the single source of truth for every colour and radius in the app.
 *
 * Brand rule
 *   One brand hue: dark green, used against plenty of white space. Everything
 *   else is a shade or tint of that green, a neutral, or a standard status
 *   colour (green / amber / red). Status colours are reserved for state and are
 *   never used for decoration or as a chart series.
 *
 * How tokens reach the UI
 *   themeToCss() turns every token into a CSS custom property on :root
 *   (camelCase -> kebab-case, e.g. primaryHover -> --primary-hover). The root
 *   layout injects that once, and globals.css maps each variable to a Tailwind
 *   utility (bg-primary, text-muted, border-line, bg-success-soft ...).
 *   Changing a value here re-skins the whole app. Components never hard-code
 *   a colour.
 *
 * Adding a colour
 *   1. Add a camelCase key to `colors` below (name it by role, never by hue).
 *   2. Add one line to the `@theme inline` block in src/app/globals.css:
 *        --color-<kebab-name>: var(--<kebab-name>);
 *   3. Use it as bg-<kebab-name>, text-<kebab-name>, border-<kebab-name>, ...
 *
 * Contrast (WCAG 2.1, checked with values below)
 *   ink on background 17.7:1, on surface 16.4:1, on surfaceMuted 15.4:1
 *   muted on background 6.8:1, on surface 6.4:1, on surfaceMuted 5.9:1
 *   onPrimary on primary 12.2:1, onAccent on accent 6.4:1
 *   success / warning / danger on their *Soft backgrounds: 4.7 / 5.6 / 5.6:1
 */

export const theme = {
  colors: {
    // Brand
    primary: "#0F3D2E",
    primaryHover: "#0A2D21",
    primarySoft: "#E3EDE7",
    onPrimary: "#FFFFFF",
    accent: "#2D6A4F",
    accentHover: "#245840",
    accentSoft: "#EEF4F0",
    onAccent: "#FFFFFF",

    // Surfaces and text
    background: "#FFFFFF",
    surface: "#F5F7F6",
    surfaceMuted: "#EBF0ED",
    ink: "#0E1B16",
    muted: "#4F5E57",
    line: "#D3DCD7",

    // Status
    success: "#1F7A3A",
    successSoft: "#E5F2E8",
    warning: "#8A5300",
    warningSoft: "#FBF0DC",
    danger: "#B42318",
    dangerSoft: "#FBE9E7",

    // App-specific
    chartTrack: "#EBF0ED", // empty part of a bar / bullet chart
    chartGrid: "#E2E8E5", // gridlines inside charts
    focus: "#2D6A4F", // keyboard focus ring
  },
  radius: {
    card: "0px",
    control: "2px",
  },
  motion: {
    durInstant: "80ms",
    durFast: "140ms",
    durBase: "200ms",
    durSlow: "320ms",
    easeOut: "cubic-bezier(0.2, 0, 0, 1)",
    easeIn: "cubic-bezier(0.4, 0, 1, 1)",
    easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    pressScale: "0.97",
    liftShadow: "0 4px 14px rgba(15, 61, 46, 0.12)",
  },
} as const;

export type ThemeColor = keyof typeof theme.colors;

const kebab = (key: string) => key.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);

export function themeToCss(): string {
  const colorVars = Object.entries(theme.colors).map(([k, v]) => `--${kebab(k)}:${v};`);
  const radiusVars = Object.entries(theme.radius).map(([k, v]) => `--radius-${kebab(k)}:${v};`);
  const motionVars = Object.entries(theme.motion).map(([k, v]) => `--${kebab(k)}:${v};`);
  return `:root{${[...colorVars, ...radiusVars, ...motionVars].join("")}}`;
}
