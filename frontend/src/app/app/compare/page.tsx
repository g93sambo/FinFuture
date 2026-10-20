"use client";

import { Fragment, useMemo, useState } from "react";
import { SECURITIES_DIRECTORY } from "@/components/domain/TickerAutocomplete";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ErrorNotice, Tag } from "@/components/ui/Feedback";
import { Segmented } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { Markdown } from "@/components/ui/Markdown";
import { api } from "@/lib/api";
import { fixed, pct } from "@/lib/format";
import type { ComparedProduct, CompareResponse } from "@/lib/types";
import { useAction } from "@/lib/useRequest";
import { useStoredState } from "@/lib/useStoredState";

type Kind = "etfs" | "bonds";

interface PresetTheme {
  id: string;
  name: string;
  desc: string;
  symbols: string[];
  icon: string;
  tag: string;
}

const STRATEGY_PRESETS: Record<Kind, PresetTheme[]> = {
  etfs: [
    {
      id: "us_growth",
      name: "US Growth & Tech Leaders",
      desc: "S&P 500, broad total market & Nasdaq 100 technology index",
      symbols: ["SPY", "VTI", "QQQ"],
      icon: "🚀",
      tag: "Core Equity",
    },
    {
      id: "global",
      name: "Global Total Market",
      desc: "Broad US equities paired with international developed & emerging markets",
      symbols: ["VTI", "VXUS", "SPY"],
      icon: "🌍",
      tag: "Global Diversified",
    },
    {
      id: "all_weather",
      name: "All-Weather Multi-Asset",
      desc: "Equities, physical gold bullion, and commercial real estate REITs",
      symbols: ["SPY", "VTI", "GLD", "VNQ"],
      icon: "🛡️",
      tag: "Multi-Asset",
    },
  ],
  bonds: [
    {
      id: "us_aggregate",
      name: "US Aggregate Core Debt",
      desc: "Total US investment-grade bonds & cash-equivalent short safety",
      symbols: ["BND", "AGG", "SHY"],
      icon: "🏛️",
      tag: "Core Fixed Income",
    },
    {
      id: "treasuries",
      name: "Treasury Curve & Inflation",
      desc: "Intermediate 7-10Y, 20Y+ long duration, and TIPS inflation protection",
      symbols: ["IEF", "TLT", "TIP"],
      icon: "📈",
      tag: "Treasury Curve",
    },
    {
      id: "credit",
      name: "Corporate & High Yield Credit",
      desc: "Investment-grade corporate debt and diversified high-yield credit notes",
      symbols: ["LQD", "HYG", "BND"],
      icon: "💼",
      tag: "Corporate Credit",
    },
  ],
};

const POPULAR_CATALOG: Record<Kind, { symbol: string; name: string; tag: string }[]> = {
  etfs: [
    { symbol: "SPY", name: "SPDR S&P 500 ETF", tag: "Large Cap" },
    { symbol: "QQQ", name: "Invesco QQQ (Nasdaq 100)", tag: "Tech Growth" },
    { symbol: "VTI", name: "Vanguard Total Stock Market", tag: "Broad US" },
    { symbol: "VOO", name: "Vanguard S&P 500 ETF", tag: "Large Cap" },
    { symbol: "VXUS", name: "Total International Stock", tag: "Global" },
    { symbol: "IWM", name: "iShares Russell 2000", tag: "Small Cap" },
    { symbol: "GLD", name: "SPDR Gold Shares", tag: "Commodity" },
    { symbol: "VNQ", name: "Vanguard Real Estate REITs", tag: "Real Estate" },
  ],
  bonds: [
    { symbol: "BND", name: "Vanguard Total Bond Market", tag: "Aggregate" },
    { symbol: "AGG", name: "iShares Core US Aggregate", tag: "Aggregate" },
    { symbol: "SHY", name: "1-3 Year Treasury Bond", tag: "Short Term" },
    { symbol: "IEF", name: "7-10 Year Treasury Bond", tag: "Intermediate" },
    { symbol: "TLT", name: "20+ Year Treasury Bond", tag: "Long Term" },
    { symbol: "TIP", name: "iShares TIPS Inflation Bond", tag: "Inflation" },
    { symbol: "LQD", name: "Investment Grade Corporate", tag: "Corporate" },
    { symbol: "HYG", name: "High Yield Corporate Bond", tag: "High Yield" },
  ],
};

function getFundName(symbol: string): string {
  const match = SECURITIES_DIRECTORY.find((s) => s.symbol.toUpperCase() === symbol.toUpperCase());
  return match?.name ?? symbol;
}

const factors: [keyof ComparedProduct["factor_breakdown"], string, string][] = [
  ["expense_ratio_score", "Cost", "30%"],
  ["tracking_error_score", "Tracking", "15%"],
  ["liquidity_score", "Liquidity", "20%"],
  ["aum_scale_score", "Size", "10%"],
  ["historical_return_score", "Return", "15%"],
  ["reputation_score", "Manager", "10%"],
];

function ProductDetail({ p }: { p: ComparedProduct }) {
  const r = p.factor_breakdown.raw_metrics ?? {};
  return (
    <div className="sticky left-0 grid max-w-3xl gap-6 bg-surface px-5 py-4 text-sm md:grid-cols-[1fr_1fr_auto]">
      <div>
        <p className="mb-1.5 font-medium text-ink">Strengths</p>
        {p.key_advantages.length ? (
          <ul className="list-inside list-disc space-y-1 text-ink marker:text-muted">
            {p.key_advantages.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">None stood out.</p>
        )}
      </div>
      <div>
        <p className="mb-1.5 font-medium text-ink">Risks</p>
        {p.key_risks.length ? (
          <ul className="list-inside list-disc space-y-1 text-ink marker:text-muted">
            {p.key_risks.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">None flagged.</p>
        )}
      </div>
      <dl className="figures grid w-fit grid-cols-[auto_auto] content-start gap-x-6 gap-y-1 text-[0.9375rem]">
        <dt className="font-sans text-muted">Expense ratio</dt>
        <dd className="text-right">{pct(r.expense_ratio, 2)}</dd>
        <dt className="font-sans text-muted">Tracking error</dt>
        <dd className="text-right">{pct(r.tracking_error, 2)}</dd>
        <dt className="font-sans text-muted">Bid-ask spread</dt>
        <dd className="text-right">{pct(r.spread_pct, 3)}</dd>
        <dt className="font-sans text-muted">Assets</dt>
        <dd className="text-right">${fixed(r.aum_billions, 1)}bn</dd>
        <dt className="font-sans text-muted">1-year return</dt>
        <dd className="text-right">{pct(r.return_1y)}</dd>
        <dt className="font-sans text-muted">30-day yield</dt>
        <dd className="text-right">{pct(r.yield_30d, 2)}</dd>
      </dl>
    </div>
  );
}

function formatSuitabilityReason(reason: string | null | undefined, clientTier?: number): string {
  if (!reason) return "Outside of your personal risk suitability threshold.";
  const match = reason.match(/Product risk level \((\d+)\) exceeds client maximum allowed risk tier \((\d+)\)/i);
  if (match) {
    return `Fund risk level (${match[1]}/5) exceeds your personal suitability limit (Tier ${match[2] ?? clientTier ?? 1}/5).`;
  }
  return reason.replace(/\s*per\s+SUIT-\d+/gi, "").replace(/SUIT-\d+/gi, "").trim();
}

function Results({
  res,
  kind,
  onSwitchToBonds,
}: {
  res: CompareResponse;
  kind: Kind;
  onSwitchToBonds?: () => void;
}) {
  const [open, setOpen] = useState<string | null>(res.ranked_products[0]?.symbol ?? null);
  const [explainMode, setExplainMode] = useState<"novice" | "quant">("novice");
  const winner = res.ranked_products[0];
  const clientTier = res.report?.client_risk_tier ?? 1;

  const sanitizedRationale = (res.rationale || "")
    .replace(/\s*per\s+SUIT-\d+/gi, "")
    .replace(/SUIT-\d+/gi, "")
    .replace(/[ \t]+/g, " ")
    .trim();

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        {winner ? (
          <div className="rounded-r-xl border-l-3 border-accent bg-accent-soft/40 py-2 pl-5 pr-4">
            <div className="flex items-center gap-2">
              <p className="text-sm text-muted">Best fit for your profile</p>
            </div>
            <p className="mt-1 text-[1.5rem] font-semibold text-ink">
              {winner.symbol} <span className="font-normal text-muted">· {winner.name}</span>
            </p>
            <p className="figures mt-1 text-sm text-ink">Composite score {fixed(winner.composite_score)} out of 10</p>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Tag tone="warning">Investor Suitability Filter Active</Tag>
            <span className="text-xs text-muted">Your Profile Risk Tier: {clientTier} of 5</span>
          </div>
        )}
        <Segmented
          label="Comparison explanation mode"
          value={explainMode}
          onChange={setExplainMode}
          options={[
            { value: "novice", label: "Plain English" },
            { value: "quant", label: "6-Factor Breakdown" },
          ]}
        />
      </div>

      {res.ranked_products.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface/80 p-6 space-y-4 shadow-xs">
          <div className="flex items-start gap-3.5">
            <span className="text-3xl">🛡️</span>
            <div>
              <h3 className="text-base font-bold text-ink">
                Fiduciary Safeguard: All candidate funds exceed your risk tier ({clientTier}/5)
              </h3>
              <p className="mt-1 text-sm text-muted max-w-[70ch] leading-relaxed">
                Your portfolio is currently configured for <strong>Conservative Capital Preservation (Tier {clientTier} of 5)</strong>. To protect you from unexpected market volatility and drawdowns, the suitability engine has withheld high-volatility equity and multi-asset ETFs from ranking.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-line/60 pt-4">
            {kind === "etfs" && onSwitchToBonds ? (
              <Button variant="primary" size="md" onClick={onSwitchToBonds}>
                Switch to Bond & Cash Funds (Recommended for Tier {clientTier}) →
              </Button>
            ) : null}
            <ButtonLink href="/app/profile" variant="secondary" size="md">
              Update Investment Horizon & Risk Tolerance
            </ButtonLink>
          </div>
        </div>
      ) : null}

      {explainMode === "novice" && winner ? (
        <Panel title="Plain-English Fund Translation" aside={<Tag tone="success">Plain English Mode</Tag>}>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-line bg-surface/70 p-4">
              <p className="text-xs font-semibold tracking-wider text-muted uppercase">1. Fee Drag (Cost 30%)</p>
              <p className="mt-1 text-sm font-medium text-ink">
                {winner.symbol} charges {pct(winner.factor_breakdown.raw_metrics?.expense_ratio, 2)} per year
              </p>
              <p className="mt-1.5 text-xs text-muted">
                Like a highway toll: on every $10,000 invested, you pay only about $
                {fixed((winner.factor_breakdown.raw_metrics?.expense_ratio ?? 0.0005) * 10000, 1)} annually to the fund manager.
              </p>
            </div>
            <div className="rounded-xl border border-line bg-surface/70 p-4">
              <p className="text-xs font-semibold tracking-wider text-muted uppercase">2. Ease of Trading (Liquidity 20%)</p>
              <p className="mt-1 text-sm font-medium text-ink">
                Bid-ask spread of {pct(winner.factor_breakdown.raw_metrics?.spread_pct, 3)}
              </p>
              <p className="mt-1.5 text-xs text-muted">
                Measures how easily you can enter or exit without price slippage—like exchanging major currencies at wholesale rates.
              </p>
            </div>
            <div className="rounded-xl border border-line bg-surface/70 p-4">
              <p className="text-xs font-semibold tracking-wider text-muted uppercase">3. Suitability Guardrail</p>
              <p className="mt-1 text-sm font-medium text-ink">
                Risk Level {winner.risk_level}/5 vs. Your Tier {clientTier}/5
              </p>
              <p className="mt-1.5 text-xs text-muted">
                {res.unsuitable_products.length > 0
                  ? `${res.unsuitable_products.length} fund(s) were automatically filtered out before ranking because their volatility exceeds your sleep-at-night threshold.`
                  : "All compared funds sit safely inside your personal risk ceiling."}
              </p>
            </div>
          </div>
        </Panel>
      ) : null}

      {res.ranked_products.length > 0 && (
        <Panel title="Ranking" aside={<span>Factor scores out of 10, weights in brackets</span>} flush>
          <Table caption="Ranked products">
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Fund</Th>
                <Th numeric>Risk</Th>
                <Th numeric>Score</Th>
                {factors.map(([k, label, w]) => (
                  <Th key={k} numeric>
                    {label} <span className="font-normal">({w})</span>
                  </Th>
                ))}
                <Th />
              </tr>
            </thead>
            <tbody>
              {res.ranked_products.map((p) => (
                <Fragment key={p.symbol}>
                  <Tr>
                    <Td numeric className="text-muted">
                      {p.rank}
                    </Td>
                    <Td>
                      <span className="font-semibold">{p.symbol}</span>
                      <span className="block max-w-[26ch] truncate text-[0.9375rem] text-muted" title={p.name}>
                        {p.name}
                      </span>
                    </Td>
                    <Td numeric>{p.risk_level}/5</Td>
                    <Td numeric className="font-semibold">
                      {fixed(p.composite_score)}
                    </Td>
                    {factors.map(([k]) => (
                      <Td key={k} numeric>
                        {fixed(p.factor_breakdown[k] as number, 1)}
                      </Td>
                    ))}
                    <Td className="text-right">
                      <button
                        onClick={() => setOpen(open === p.symbol ? null : p.symbol)}
                        aria-expanded={open === p.symbol}
                        className="text-sm whitespace-nowrap text-primary underline decoration-primary/30 underline-offset-4"
                      >
                        {open === p.symbol ? "Hide" : "Details"}
                      </button>
                    </Td>
                  </Tr>
                  {open === p.symbol ? (
                    <tr>
                      <td colSpan={5 + factors.length} className="border-b border-line p-0">
                        <ProductDetail p={p} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </Table>
        </Panel>
      )}

      {res.unsuitable_products.length ? (
        <Panel title="Set aside by Suitability Safeguards">
          <ul className="divide-y divide-line">
            {res.unsuitable_products.map((p) => (
              <li key={p.symbol} className="grid gap-1 py-3 text-sm sm:grid-cols-[8rem_1fr_auto] sm:gap-4 items-center">
                <span className="font-bold text-ink">{p.symbol}</span>
                <span className="text-ink">{formatSuitabilityReason(p.suitability_reason, clientTier)}</span>
                <Tag tone="warning">Outside Tier</Tag>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel title="Fiduciary Summary">
        <Markdown className="max-w-[72ch]" text={sanitizedRationale} />
        <p className="mt-4 text-[0.9375rem] text-muted">
          Method: {res.report?.methodology}. Your risk tier for products is {clientTier} of 5.
        </p>
      </Panel>
    </div>
  );
}

function Compare({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<Kind>("etfs");
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(STRATEGY_PRESETS.etfs[0].symbols);
  const [activePresetId, setActivePresetId] = useState<string | null>(STRATEGY_PRESETS.etfs[0].id);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  // Kept across page changes so the last comparison is still here when the client comes back
  const [res, setRes] = useStoredState<CompareResponse>(`compare.${clientId}`);

  const tooFew = selectedSymbols.length < 2;
  const tooMany = selectedSymbols.length > 15;

  const { run, pending, error } = useAction(async (k: Kind, syms: string[]) => {
    setRes(await api.compare(k, clientId, syms));
  });

  // Filtered search results from SECURITIES_DIRECTORY
  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase().trim();
    return SECURITIES_DIRECTORY.filter(
      (s) =>
        (s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || s.category.toLowerCase().includes(q)) &&
        !selectedSymbols.includes(s.symbol)
    ).slice(0, 8);
  }, [searchQuery, selectedSymbols]);

  function handleSelectPreset(preset: PresetTheme) {
    setSelectedSymbols(preset.symbols);
    setActivePresetId(preset.id);
    setRes(null);
  }

  function handleToggleFund(sym: string) {
    setActivePresetId(null);
    setRes(null);
    setSelectedSymbols((prev) => {
      if (prev.includes(sym)) {
        return prev.filter((s) => s !== sym);
      }
      if (prev.length >= 15) return prev;
      return [...prev, sym];
    });
  }

  function handleAddFund(sym: string) {
    if (selectedSymbols.includes(sym) || selectedSymbols.length >= 15) return;
    setActivePresetId(null);
    setRes(null);
    setSelectedSymbols((prev) => [...prev, sym]);
    setSearchQuery("");
    setSearchOpen(false);
  }

  function handleRemoveFund(sym: string) {
    setActivePresetId(null);
    setRes(null);
    setSelectedSymbols((prev) => prev.filter((s) => s !== sym));
  }

  function handleClearAll() {
    setSelectedSymbols([]);
    setActivePresetId(null);
    setRes(null);
  }

  return (
    <div className="space-y-8">
      {/* Main Interactive Configuration Card */}
      <div className="rounded-card border border-line bg-surface/70 p-5 shadow-[0_2px_12px_rgba(15,41,34,0.03)] space-y-6">
        {/* Row 1: Fund Type Selector + Preset Themes Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line/70 pb-4">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">Step 1: Choose Fund Category</span>
            <div className="mt-1">
              <Segmented
                label="Fund Category"
                value={kind}
                onChange={(k) => {
                  setKind(k);
                  setSelectedSymbols(STRATEGY_PRESETS[k][0].symbols);
                  setActivePresetId(STRATEGY_PRESETS[k][0].id);
                  setRes(null);
                }}
                options={[
                  { value: "etfs", label: "Equity & Multi-Asset ETFs" },
                  { value: "bonds", label: "Bond & Fixed Income Funds" },
                ]}
              />
            </div>
          </div>

          <div className="text-right">
            <span className="figures text-xs font-semibold text-ink">
              {selectedSymbols.length} / 15 funds selected
            </span>
            <p className="text-[11px] text-muted">Minimum 2 funds required to rank</p>
          </div>
        </div>

        {/* Row 2: Strategy Baskets (1-Click Presets) */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Step 2: Pick a Ready-Made Strategy Basket or Mix Your Own
            </p>
            {activePresetId ? (
              <span className="text-[11px] font-medium text-accent">Active Preset Loaded</span>
            ) : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {STRATEGY_PRESETS[kind].map((preset) => {
              const isActive = activePresetId === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => handleSelectPreset(preset)}
                  className={`flex flex-col justify-between rounded-xl border p-3.5 text-left transition-all cursor-pointer ${
                    isActive
                      ? "border-accent bg-accent-soft/70 shadow-xs ring-1 ring-accent"
                      : "border-line bg-background hover:border-accent/40 hover:bg-surface"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="text-base">{preset.icon}</span>
                      <span className="rounded-full bg-surface border border-line px-2 py-0.5 text-[10px] font-medium text-muted">
                        {preset.tag}
                      </span>
                    </div>
                    <p className="mt-2 text-xs font-bold text-ink">{preset.name}</p>
                    <p className="mt-1 text-[11px] leading-snug text-muted line-clamp-2">{preset.desc}</p>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-1 border-t border-line/60 pt-2">
                    {preset.symbols.map((sym) => (
                      <span key={sym} className="figures rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-semibold text-ink">
                        {sym}
                      </span>
                    ))}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Row 3: Currently Selected Funds Tray */}
        <div className="rounded-xl border border-line bg-background p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-ink">Selected Funds for Comparison</span>
              <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-bold text-accent">
                {selectedSymbols.length}
              </span>
            </div>

            {selectedSymbols.length > 0 && (
              <button
                type="button"
                onClick={handleClearAll}
                className="text-xs font-medium text-muted hover:text-danger transition-colors cursor-pointer"
              >
                Clear all
              </button>
            )}
          </div>

          {selectedSymbols.length === 0 ? (
            <p className="py-2 text-center text-xs text-muted">
              No funds selected yet. Tap any fund chip below or click a Strategy Basket above to begin.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {selectedSymbols.map((sym) => {
                const name = getFundName(sym);
                return (
                  <div
                    key={sym}
                    className="inline-flex items-center gap-2 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1.5 text-xs text-ink shadow-2xs animate-fade-in"
                  >
                    <span className="font-bold text-accent">{sym}</span>
                    <span className="max-w-[140px] truncate text-[11px] text-muted sm:max-w-[200px]" title={name}>
                      {name}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveFund(sym)}
                      className="ml-1 grid h-4 w-4 place-items-center rounded-full text-muted hover:bg-danger/20 hover:text-danger text-[11px] font-bold transition-colors cursor-pointer"
                      title={`Remove ${sym}`}
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Row 4: 1-Click Quick-Add Catalog + Search Bar */}
        <div className="grid gap-5 lg:grid-cols-12 items-start">
          {/* Quick-Add Chips */}
          <div className="space-y-2 lg:col-span-8">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Tap to Add / Remove Popular Funds
            </p>
            <div className="flex flex-wrap gap-1.5">
              {POPULAR_CATALOG[kind].map((item) => {
                const isSelected = selectedSymbols.includes(item.symbol);
                return (
                  <button
                    key={item.symbol}
                    type="button"
                    onClick={() => handleToggleFund(item.symbol)}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-all cursor-pointer ${
                      isSelected
                        ? "border-accent bg-accent text-on-accent font-semibold shadow-2xs"
                        : "border-line bg-background text-ink hover:border-accent hover:bg-surface"
                    }`}
                  >
                    <span>{isSelected ? "✓" : "+"}</span>
                    <span>{item.symbol}</span>
                    <span className={`text-[10px] ${isSelected ? "text-on-accent/80" : "text-muted"}`}>
                      ({item.tag})
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Search Dropdown to Add Any Other Security */}
          <div className="relative space-y-2 lg:col-span-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Or Search by Name / Ticker
            </p>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onFocus={() => setSearchOpen(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setSearchOpen(true);
                }}
                placeholder="Search e.g. Apple, Gold, Vanguard..."
                className="w-full rounded-xl border border-line bg-background px-3 py-1.5 text-xs text-ink placeholder:text-muted focus:border-accent focus:outline-hidden"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2.5 top-2 text-xs text-muted hover:text-ink cursor-pointer"
                >
                  ✕
                </button>
              )}
            </div>

            {searchOpen && searchResults.length > 0 && (
              <div className="absolute left-0 top-16 z-30 w-full rounded-xl border border-line bg-background p-1.5 shadow-lg animate-fade-in max-h-56 overflow-y-auto">
                {searchResults.map((s) => (
                  <div
                    key={s.symbol}
                    onClick={() => handleAddFund(s.symbol)}
                    className="flex items-center justify-between rounded-lg px-2.5 py-1.5 text-xs hover:bg-surface cursor-pointer"
                  >
                    <div>
                      <span className="font-bold text-ink pr-1.5">{s.symbol}</span>
                      <span className="text-[11px] text-muted truncate">{s.name}</span>
                    </div>
                    <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[9px] text-muted">
                      + Add
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Row 5: Action Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line/70 pt-4">
          <div>
            {tooFew ? (
              <p className="text-xs text-warning font-medium">
                ⚠️ Select at least 2 funds to run multi-factor quantitative comparison.
              </p>
            ) : tooMany ? (
              <p className="text-xs text-danger font-medium">
                ⚠️ Maximum 15 funds can be compared simultaneously.
              </p>
            ) : (
              <p className="text-xs text-muted">
                Ready: Analyzing {selectedSymbols.length} funds across 6 risk, return, and expense factors.
              </p>
            )}
          </div>

          <Button
            onClick={() => void run(kind, selectedSymbols)}
            pending={pending}
            disabled={tooFew || tooMany}
            size="md"
            className="w-full sm:w-auto"
          >
            {pending ? "Analyzing Factors…" : `Compare ${selectedSymbols.length} Funds →`}
          </Button>
        </div>
      </div>

      <ErrorNotice error={error} />

      {pending && (
        <div className="rounded-xl border border-dashed border-line bg-surface/50 p-8 text-center animate-fadeIn my-6">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-accent">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          </div>
          <p className="mt-3 text-sm font-semibold text-ink">Analyzing & Scoring Funds…</p>
          <p className="mt-1 text-xs text-muted max-w-[50ch] mx-auto">
            Computing 6-factor quantitative matrix: expense ratios, tracking errors, liquidity buffers, and manager suitability.
          </p>
        </div>
      )}

      {res ? (
        <div className={pending ? "opacity-40 pointer-events-none transition-opacity" : "opacity-100 transition-opacity"}>
          <Results
            res={res}
            kind={kind}
            onSwitchToBonds={() => {
              setKind("bonds");
              setSelectedSymbols(STRATEGY_PRESETS.bonds[0].symbols);
              setActivePresetId(STRATEGY_PRESETS.bonds[0].id);
              void run("bonds", STRATEGY_PRESETS.bonds[0].symbols);
            }}
          />
        </div>
      ) : null}
      {!res && !pending ? (
        <p className="max-w-[70ch] text-sm text-muted">
          Each fund is scored on six factors and combined with fixed weights. Funds above your risk tier are listed separately with the reason;
          they are never ranked.{kind === "bonds" ? " Bond funds are also checked for duration against your horizon." : ""}
        </p>
      ) : null}
    </div>
  );
}

export default function ComparePage() {
  return (
    <>
      <PageHeader title="Compare funds" lede="Score funds against each other and against your profile." />
      <RequireProfile>{(id) => <Compare clientId={id} />}</RequireProfile>
    </>
  );
}
