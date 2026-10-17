import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { theme, themeToCss } from "@/theme";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

// Self-hosted IBM Plex (from @fontsource), so builds need no network access.
const body = localFont({
  src: [
    { path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2", weight: "600", style: "normal" },
    { path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-body",
  display: "swap",
});

const figures = localFont({
  src: [
    { path: "../../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-figures",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Equify · Intelligent Wealth & Investment Dashboard", template: "%s · Equify" },
  description: "Risk profiling, product comparison, allocation and paper-trade execution with a compliance check on every step.",
};

export const viewport: Viewport = {
  themeColor: theme.colors.primary,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${body.variable} ${figures.variable}`}>
      <head>
        <style dangerouslySetInnerHTML={{ __html: themeToCss() }} />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
