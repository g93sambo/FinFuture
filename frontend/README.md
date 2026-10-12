# FinFuture Advisory: frontend

Next.js 14 (App Router), TypeScript, Tailwind CSS v4. Talks to the FastAPI backend in `../backend`.

## Running it

```bash
# backend (from ../backend, in its own virtualenv)
uvicorn main:app --reload --port 8000

# frontend
npm install
npm run dev            # http://localhost:3000
```

The API address defaults to `http://localhost:8000`. Override it with `NEXT_PUBLIC_API_URL` in `.env.local`.
The backend's CORS settings only allow `http://localhost:3000` and `http://127.0.0.1:3000`.

## Pages

| Route | What it does | Backend calls |
|---|---|---|
| `/` | Public landing page | none |
| `/login`, `/register` | Sign in, open an account | `auth/login`, `auth/register`, `auth/me` |
| `/app` | Overview: account value, holdings, profile summary, recent orders | `portfolio`, `profile`, `trades` |
| `/app/advisor` | Conversation: risk profiling, then advice, trade proposals with approve / cancel | `session/start`, `ws/chat/{session}` (falls back to `chat/message`) |
| `/app/allocation` | Optimised weights, reasoning, efficient frontier, risk attribution, rebalancing orders | `allocation/recommend` |
| `/app/compare` | Six-factor fund comparison for ETFs or bond funds | `compare/etfs`, `compare/bonds` |
| `/app/trade` | Draft, review and approve orders; order history | `trade/propose`, `trade/execute`, `trades` |
| `/app/health` | Health score, alerts, drift, concentration, 60/40 comparison, rebalancing plan | `portfolio/health-report` |
| `/app/markets` | Quotes, Treasury yield curve, macro indicators | `market/quote`, `market/macro` |
| `/app/profile` | Everything the profiler recorded and derived | `profile` |
| `/app/audit` | Audit entries, chain verification, Merkle anchoring | `audit`, `audit/verify`, `audit/anchor` |
| `/app/compliance` | Live compliance rule catalogue | `compliance/rules` |

Every page under `/app` except Markets and Compliance needs a finished risk profile. Until there is one, they point to the Advisor.

## Theming

All colours and radii live in **one file: `src/theme.ts`**. Changing a value there re-skins the whole app.

How it is wired:

1. `src/theme.ts` exports `theme` (semantic tokens such as `primary`, `surface`, `ink`, `muted`, `line`, `danger`) and `themeToCss()`, which turns every token into a CSS variable on `:root` (`primaryHover` becomes `--primary-hover`).
2. `src/app/layout.tsx` injects `themeToCss()` once in `<head>` and sets the browser `themeColor` from `theme.colors.primary`.
3. `src/app/globals.css` maps each variable to a Tailwind utility inside `@theme inline`, for example `--color-primary: var(--primary);`. That produces classes such as `bg-primary`, `text-muted`, `border-line`, `bg-success-soft` and `text-on-primary`.
4. The same file clears Tailwind's default palette (`--color-*: initial`), so `bg-blue-500`, `text-gray-600` and the like do not exist in this project.

Rules for components:

- Use only the semantic classes (`bg-primary`, `text-ink`, `border-line`, `hover:bg-primary-hover`, opacity modifiers like `bg-ink/50`). SVG uses `fill-*` and `stroke-*` with the same tokens.
- No hex, `rgb()`, or Tailwind palette colours anywhere outside `theme.ts`.
- Text on a coloured background uses the matching `on-*` token (`text-on-primary` on `bg-primary`).

### Adding a colour

1. Add a camelCase key to `theme.colors` in `src/theme.ts`, named by its role (for example `highlight`, not `lightGreen`).
2. Add one line to the `@theme inline` block in `src/app/globals.css`:
   ```css
   --color-highlight: var(--highlight);
   ```
3. Use it: `bg-highlight`, `text-highlight`, `border-highlight`.

### Contrast

Checked against WCAG 2.1 AA (4.5:1 for body text) with the current values:

| Pair | Ratio |
|---|---|
| ink on background / surface / surfaceMuted | 17.7 / 16.4 / 15.4 |
| muted on background / surface / surfaceMuted | 6.8 / 6.4 / 5.9 |
| onPrimary on primary | 12.2 |
| onAccent on accent | 6.4 |
| success / warning / danger on their soft backgrounds | 4.7 / 5.6 / 5.6 |

If you change a text or background colour, recheck these pairs.

## Design rules this UI follows

- Square corners (`radius.card` 0px, `radius.control` 2px). No shadows; structure comes from hairline rules and white space.
- One brand hue (dark green) plus neutrals. Status colours (green, amber, red) only mean state, and always come with a word.
- IBM Plex Sans for text, IBM Plex Mono for figures so numbers line up. Fonts are self-hosted from `@fontsource`.
- Left-aligned layouts, ruled ledgers and tables instead of card grids. No gradients, glows, glass effects, icon tiles or pill badges.
- Charts are plain SVG in one hue. A target is drawn as an ink tick rather than a second colour, every bar carries its value as text, and line charts have a hover readout plus a table view.
