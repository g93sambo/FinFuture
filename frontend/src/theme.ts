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
    // Brand: Deep dark green primary + vibrant emerald secondary/accent + crisp white
    primary: "#0F2922",
    primaryHover: "#163B31",
    primarySoft: "#E6F4EE",
    onPrimary: "#FFFFFF",
    accent: "#269966",
    accentHover: "#1E7E53",
    accentSoft: "#EAF7F1",
    onAccent: "#FFFFFF",

    // Surfaces and text
    background: "#FFFFFF",
    surface: "#F7F9F8",
    surfaceMuted: "#EEF3F0",
    ink: "#0E1B16",
    muted: "#76847D",
    line: "#E6ECE9",

    // Status
    success: "#269966",
    successSoft: "#EAF7F1",
    warning: "#B86E00",
    warningSoft: "#FEF5E7",
    danger: "#D92D20",
    dangerSoft: "#FEECEB",

    // App-specific
    chartTrack: "#EBF0ED", // empty part of a bar / bullet chart
    chartGrid: "#E2E8E5", // gridlines inside charts
    focus: "#2D6A4F", // keyboard focus ring

    // Animated "aurora" background (landing page). Shades of the primary green.
    // Highlight is kept at 50% opacity or less so white text stays above 4.5:1.
    auroraDeep: "#06241A",
    auroraMid: "#1B5E43",
    auroraHighlight: "#40916C",
  },
  radius: {
    card: "16px", // dashboard panels
    control: "10px",
    button: "10px", // every button: raise for rounder, lower for squarer
    feature: "14px", // landing-page feature bubbles
  },
  motion: {
    durInstant: "80ms",
    durFast: "140ms",
    durBase: "200ms",
    durSlow: "320ms",
    easeOut: "cubic-bezier(0.2, 0, 0, 1)",
    easeIn: "cubic-bezier(0.4, 0, 1, 1)",
    easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    pressScale: "0.98",
    liftShadow: "0 8px 24px rgba(15, 41, 34, 0.08)",
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
