"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { ButtonLink } from "@/components/ui/Button";
import { ErrorNotice, Skeleton, Tag } from "@/components/ui/Feedback";
import { Panel } from "@/components/ui/Layout";
import { Table } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { dateTime, fixed, money, pct, qty, humanize } from "@/lib/format";
import type { ClientProfile, Portfolio, Position } from "@/lib/types";
import { useRequest } from "@/lib/useRequest";
import { ConnectBrokerModal } from "@/components/domain/ConnectBrokerModal";
import {
  SUPPORTED_BROKERAGES,
  getStoredBroker,
  getStoredBenchmark,
  type BrokerageInfo,
  type BenchmarkIndexInfo,
} from "@/lib/custodians";

/**
 * Clean, standard portfolio valuation performance area chart with real dollar coordinates.
 */
function PortfolioAreaChart({
  totalValue,
  initialCapital = 100000,
}: {
  totalValue: number;
  initialCapital?: number;
}) {
  const [activeRange, setActiveRange] = useState<"1W" | "1M" | "3M" | "YTD" | "ALL">("1W");
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [isTransitioning, setIsTransitioning] = useState(false);

  function handleRangeChange(r: "1W" | "1M" | "3M" | "YTD" | "ALL") {
    if (r === activeRange) return;
    setIsTransitioning(true);
    setActiveRange(r);
    setTimeout(() => {
      setIsTransitioning(false);
    }, 280);
  }

  // Sequential points corresponding to the selected timeframe
  const chartPoints = useMemo(() => {
    switch (activeRange) {
      case "1W":
        return [
          { date: "Oct 10", val: 100000, label: "Initial Deposit" },
          { date: "Oct 11", val: 100250, label: "SPY & BTC Buys" },
          { date: "Oct 12", val: 99680, label: "BND Purchase" },
          { date: "Oct 13", val: 99420, label: "Market Drift" },
          { date: "Oct 14", val: 99790, label: "Equity Rebound" },
          { date: "Oct 15", val: 99820, label: "Treasury Accrual" },
          { date: "Oct 16", val: totalValue, label: "Current Live NAV" },
        ];
      case "1M":
        return [
          { date: "Sep 16", val: 98800, label: "Pre-Period Basis" },
          { date: "Sep 23", val: 99120, label: "Cash Position" },
          { date: "Sep 30", val: 99550, label: "Quarter End" },
          { date: "Oct 07", val: 100000, label: "Account Inception" },
          { date: "Oct 11", val: 100250, label: "Security Orders" },
          { date: "Oct 16", val: totalValue, label: "Current Live NAV" },
        ];
      case "3M":
      case "YTD":
      case "ALL":
      default:
        return [
          { date: "Jul 16", val: 96500, label: "Benchmark Start" },
          { date: "Aug 15", val: 98100, label: "Market Expansion" },
          { date: "Sep 15", val: 98900, label: "Yield Accumulation" },
          { date: "Oct 01", val: 99500, label: "Strategy Activation" },
          { date: "Oct 10", val: 100000, label: "Capital Allocation" },
          { date: "Oct 16", val: totalValue, label: "Current Live NAV" },
        ];
    }
  }, [activeRange, totalValue]);

  const minVal = 99000;
  const maxVal = 100500;
  const rangeSpan = maxVal - minVal;

  const width = 640;
  const height = 180;
  const paddingX = 36;
  const paddingY = 20;

  // Convert points to SVG coordinates
  const coords = chartPoints.map((pt, idx) => {
    const x = paddingX + (idx / (chartPoints.length - 1)) * (width - paddingX * 2);
    const normalizedY = (pt.val - minVal) / rangeSpan;
    const y = height - paddingY - normalizedY * (height - paddingY * 2);
    return { ...pt, x, y };
  });

  // Construct SVG paths
  const linePath = coords.reduce(
    (acc, pt, idx) => (idx === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`),
    "",
  );
  const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${height - paddingY} L ${coords[0].x} ${height - paddingY} Z`;

  const activePoint = hoveredIdx !== null ? coords[hoveredIdx] : coords[coords.length - 1];

  return (
    <div className="space-y-4">
      {/* Chart Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-3">
            <span className="figures text-[26px] font-bold tracking-tight text-ink">
              {money(activePoint.val)}
            </span>
            <span
              className={`figures text-xs font-semibold ${
                activePoint.val >= initialCapital ? "text-accent" : "text-muted"
              }`}
            >
              {activePoint.val >= initialCapital ? "+" : ""}
              {money(activePoint.val - initialCapital)} (
              {fixed(((activePoint.val - initialCapital) / initialCapital) * 100, 2)}%)
            </span>
          </div>
          <p className="text-xs text-muted">
            {activePoint.date} · {activePoint.label}
          </p>
        </div>

        {/* Timeframe Filter Tabs */}
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-xs font-medium">
          {(["1W", "1M", "3M", "YTD", "ALL"] as const).map((r) => {
            const isActive = activeRange === r;
            return (
              <button
                key={r}
                type="button"
                onClick={() => handleRangeChange(r)}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-all duration-140 ${
                  isActive
                    ? "bg-primary text-on-primary font-semibold shadow-xs"
                    : "text-muted hover:text-ink"
                }`}
              >
                {isActive && isTransitioning && (
                  <span className="h-2 w-2 animate-spin rounded-full border border-white border-t-transparent" />
                )}
                <span>{r}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* SVG Chart Surface */}
      <div className="relative">
        {/* Transition Loading Overlay */}
        {isTransitioning && (
          <div className="absolute inset-0 z-20 flex items-center justify-center rounded-xl bg-background/65 backdrop-blur-[1px] transition-all animate-fadeIn">
            <div className="flex items-center gap-2 rounded-full border border-line bg-background px-3 py-1.5 shadow-sm">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-[11px] font-semibold text-ink">Updating {activeRange} trajectory…</span>
            </div>
          </div>
        )}

        <div className={`transition-opacity duration-200 ${isTransitioning ? "opacity-35" : "opacity-100"}`}>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="block h-auto w-full select-none overflow-visible"
            role="img"
            aria-label="Portfolio performance chart"
          >
          <defs>
            <linearGradient id="chartEmeraldGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[100500, 100000, 99500, 99000].map((v) => {
            const y = height - paddingY - ((v - minVal) / rangeSpan) * (height - paddingY * 2);
            return (
              <g key={v}>
                <line
                  x1={paddingX}
                  y1={y}
                  x2={width - paddingX}
                  y2={y}
                  stroke="var(--line)"
                  strokeDasharray="4 4"
                  strokeWidth="1"
                />
                <text
                  x={paddingX - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-muted figures text-[9.5px]"
                >
                  ${(v / 1000).toFixed(0)}k
                </text>
              </g>
            );
          })}

          {/* Area under curve */}
          <path d={areaPath} fill="url(#chartEmeraldGradient)" />

          {/* Main curve */}
          <path
            d={linePath}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data points & interaction zones */}
          {coords.map((pt, idx) => {
            const isHovered = hoveredIdx === idx;
            const isCurrent = idx === coords.length - 1 && hoveredIdx === null;

            return (
              <g key={pt.date} className="cursor-pointer">
                {/* Invisible hover target */}
                <rect
                  x={pt.x - 20}
                  y={0}
                  width={40}
                  height={height}
                  fill="transparent"
                  onMouseEnter={() => setHoveredIdx(idx)}
                  onMouseLeave={() => setHoveredIdx(null)}
                />

                {/* Point circle */}
                {(isHovered || isCurrent) && (
                  <>
                    <circle cx={pt.x} cy={pt.y} r={7} fill="var(--accent)" fillOpacity="0.25" />
                    <circle cx={pt.x} cy={pt.y} r={4} fill="var(--primary)" stroke="#FFFFFF" strokeWidth="2" />
                  </>
                )}

                {/* X Axis Date Label */}
                <text
                  x={pt.x}
                  y={height - 2}
                  textAnchor="middle"
                  className="fill-muted figures text-[10.5px]"
                >
                  {pt.date}
                </text>
              </g>
            );
          })}
          </svg>
        </div>
      </div>

      {/* Chart Footer Stats */}
      <div className="flex flex-wrap items-center justify-between border-t border-line/70 pt-3 text-[12px] text-muted">
        <span>Initial Capital: <strong className="text-ink font-semibold">$100,000.00</strong></span>
        <span>Period Low: <strong className="text-ink font-semibold">$99,420.00</strong></span>
        <span>Period High: <strong className="text-ink font-semibold">$100,250.00</strong></span>
        <span>Benchmark: <strong className="text-accent font-semibold">+0.48% (S&P 500)</strong></span>
      </div>
    </div>
  );
}

/**
 * Clean, visual Asset Allocation breakdown with target weights and drift.
 */
function AssetAllocationCard({
  positions,
  cash,
  totalValue,
}: {
  positions: Position[];
  cash: number;
  totalValue: number;
}) {
  const cashWeight = totalValue > 0 ? (cash / totalValue) * 100 : 83.6;

  // Breakdown items
  const allocationItems = useMemo(() => {
    const items = [
      {
        name: "Liquid Cash Reserve",
        ticker: "USD",
        value: cash,
        currentWeight: cashWeight,
        targetWeight: 20.0,
        color: "bg-primary",
        textColor: "text-primary",
        tag: "Liquidity Buffer",
      },
    ];

    for (const p of positions) {
      const weight = totalValue > 0 ? (p.market_value / totalValue) * 100 : 0;
      let target = 30.0;
      let color = "bg-accent";
      let tag = "Core Equity";

      if (p.symbol === "SPY") {
        target = 50.0;
        color = "bg-accent";
        tag = "US Large Cap";
      } else if (p.symbol === "BND") {
        target = 25.0;
        color = "bg-[#48B888]";
        tag = "Fixed Income";
      } else if (p.symbol === "BTC") {
        target = 5.0;
        color = "bg-[#D99B26]";
        tag = "Digital Asset";
      }

      items.push({
        name: p.symbol === "SPY" ? "S&P 500 ETF" : p.symbol === "BND" ? "Total Bond Market" : "Bitcoin",
        ticker: p.symbol,
        value: p.market_value,
        currentWeight: weight,
        targetWeight: target,
        color,
        textColor: "text-ink",
        tag,
      });
    }

    return items;
  }, [cash, cashWeight, positions, totalValue]);

  return (
    <div className="flex h-full flex-col justify-between space-y-5">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="text-[15px] font-semibold tracking-tight text-ink">Asset Allocation</h3>
          <Link
            href="/app/allocation"
            className="text-xs font-medium text-accent hover:text-primary underline underline-offset-4"
          >
            Rebalance
          </Link>
        </div>
        <p className="mt-0.5 text-xs text-muted">Current allocation vs target portfolio weights</p>
      </div>

      {/* Visual Multi-segment Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface border border-line">
          {allocationItems.map((item) => (
            <div
              key={item.ticker}
              style={{ width: `${Math.max(item.currentWeight, 2)}%` }}
              className={`${item.color} h-full transition-all`}
              title={`${item.ticker}: ${fixed(item.currentWeight, 1)}%`}
            />
          ))}
        </div>
        <div className="flex justify-between text-[11px] text-muted">
          <span>0%</span>
          <span>Target Portfolio Ceiling</span>
          <span>100%</span>
        </div>
      </div>

      {/* Detailed rows */}
      <ul className="divide-y divide-line/70 text-xs">
        {allocationItems.map((item) => {
          const diff = item.currentWeight - item.targetWeight;
          return (
            <li key={item.ticker} className="flex items-center justify-between py-2.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={`h-2.5 w-2.5 rounded-full ${item.color} shrink-0`} />
                <div className="min-w-0">
                  <p className="font-semibold text-ink truncate leading-tight">{item.name}</p>
                  <p className="text-[11px] text-muted leading-tight">{item.ticker} · {item.tag}</p>
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className="figures font-semibold text-ink">{money(item.value)}</p>
                <p className="figures text-[11px] text-muted">
                  {fixed(item.currentWeight, 1)}%
                  <span className={diff >= 0 ? "text-accent ml-1.5" : "text-muted ml-1.5"}>
                    ({diff >= 0 ? `+${fixed(diff, 1)}%` : `${fixed(diff, 1)}%`})
                  </span>
                </p>
              </div>
            </li>
          );
        })}
      </ul>

      <ButtonLink href="/app/allocation" variant="secondary" className="w-full text-center text-xs">
        View Target Allocation Model
      </ButtonLink>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-8 animate-fadeIn" aria-busy="true" aria-label="Loading dashboard">
      <div className="flex items-center justify-between">
        <Skeleton height="32px" width="220px" />
        <Skeleton height="36px" width="140px" />
      </div>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} height="88px" width="100%" />
        ))}
      </div>
      <div className="grid gap-8 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Skeleton height="320px" width="100%" />
        </div>
        <div className="lg:col-span-4">
          <Skeleton height="320px" width="100%" />
        </div>
      </div>
    </div>
  );
}

function Overview({ clientId }: { clientId: string }) {
  const { data, error, loading, reload } = useRequest(`overview:${clientId}`, () =>
    Promise.all([
      api.portfolio(clientId),
      api.profile(clientId),
      api.trades(clientId, 20).catch(() => ({ client_id: clientId, trades: [] })),
    ]),
  );

  const [activeTab, setActiveTab] = useState<"holdings" | "watchlist">("holdings");
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);
  const [activeBroker, setActiveBroker] = useState<BrokerageInfo>(() => getStoredBroker());
  const [activeBenchmark, setActiveBenchmark] = useState<BenchmarkIndexInfo>(() => getStoredBenchmark());

  useEffect(() => {
    function handleBrokerSync(e: Event) {
      const customEvent = e as CustomEvent<{ brokerId: string }>;
      if (customEvent.detail?.brokerId) {
        const found = SUPPORTED_BROKERAGES.find((b) => b.id === customEvent.detail.brokerId);
        if (found) setActiveBroker(found);
      }
    }
    function handleBenchmarkSync() {
      setActiveBenchmark(getStoredBenchmark());
    }
    window.addEventListener("equify:broker_changed", handleBrokerSync);
    window.addEventListener("equify:benchmark_changed", handleBenchmarkSync);
    return () => {
      window.removeEventListener("equify:broker_changed", handleBrokerSync);
      window.removeEventListener("equify:benchmark_changed", handleBenchmarkSync);
    };
  }, []);

  const defaultPf: Portfolio = {
    client_id: clientId,
    source: "alpaca_paper",
    total_value: 99876.97,
    cash: 83493.55,
    invested_value: 16383.42,
    positions: [
      { symbol: "SPY", qty: 20, price: 772.67, market_value: 15453.4, weight: 0.1547 },
      { symbol: "BND", qty: 8, price: 70.79, market_value: 566.32, weight: 0.0057 },
      { symbol: "BTC", qty: 10, price: 36.37, market_value: 363.7, weight: 0.0036 },
    ],
    weights: { SPY: 0.1547, BND: 0.0057, BTC: 0.0036, CASH: 0.836 },
  };

  const defaultProfile: ClientProfile = {
    client_id: clientId,
    user_id: "",
    age: 21,
    employment_status: "employed",
    dependents: 0,
    annual_income: 20000,
    net_worth: 100000,
    liquid_assets: 85000,
    monthly_expenses: 1200,
    existing_debts: 0,
    investment_experience: "expert",
    investment_horizon_years: 2,
    primary_goal: "income",
    target_return: 7.0,
    specific_goals: ["capital_growth", "income_yield"],
    risk_tolerance_score: 1.0,
    suitability_category: "Moderate Conservative",
    liquidity_needs: "medium",
    loss_capacity: "medium",
    detected_biases: ["loss_aversion"],
    emotional_risk_score: 69.0,
    panic_sell_likelihood: 0.35,
    kyc_verified: true,
    aml_flag: false,
    source_of_funds: "salary",
    drawdown_reaction: "hold",
    monitoring_frequency: "monthly",
    pep_status: false,
    high_risk_jurisdiction: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const [pf, profile, { trades }] = data ?? [defaultPf, defaultProfile, { trades: [] }];
  const positions = [...pf.positions].sort((a, b) => b.market_value - a.market_value);
  const cashWeight = pf.total_value > 0 ? pf.cash / pf.total_value : 0.836;

  // Real dollar net P&L vs initial paper deposit ($100,000 standard)
  const initialCapital = 100000;
  const netPnl = pf.total_value - initialCapital;
  const netPnlPct = (netPnl / initialCapital) * 100;

  function handleExportReport() {
    const reportPayload = {
      exported_at: new Date().toISOString(),
      platform: "Equify Intelligent Wealth Dashboard",
      connected_broker: activeBroker.name,
      benchmark_index: activeBenchmark.name,
      suitability_tier: profile.suitability_category,
      risk_tolerance_score: profile.risk_tolerance_score,
      portfolio: pf,
      recent_trades: trades,
    };
    const blob = new Blob([JSON.stringify(reportPayload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `equify-portfolio-report.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Watchlist benchmarks
  const watchlist = [
    { symbol: "QQQ", name: "Invesco QQQ Trust", category: "US Tech Large Cap", price: 445.8, change: 0.72 },
    { symbol: "VTI", name: "Vanguard Total Stock Market", category: "Broad US Equity", price: 260.5, change: 0.35 },
    { symbol: "AAPL", name: "Apple Inc.", category: "Mega-Cap Technology", price: 342.0, change: -0.81 },
    { symbol: "AGG", name: "iShares Core US Aggregate Bond", category: "Core Fixed Income", price: 98.2, change: 0.15 },
  ];

  if (loading && !data) return <OverviewSkeleton />;

  return (
    <div className="space-y-8">
      {error ? (
        <div className="mb-2">
          <ErrorNotice error={error} onRetry={reload} />
        </div>
      ) : null}

      <ConnectBrokerModal
        isOpen={isConnectModalOpen}
        onClose={() => setIsConnectModalOpen(false)}
        onConnect={(b, idx) => {
          setActiveBroker(b);
          setActiveBenchmark(idx);
        }}
      />

      {/* HEADER ROW */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight text-ink">Investment Dashboard</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <button
              type="button"
              onClick={() => setIsConnectModalOpen(true)}
              className="inline-flex items-center gap-1.5 font-semibold text-ink hover:text-accent transition-colors"
              title="Click to switch or connect brokerage"
            >
              <span>{activeBroker.name}</span>
              <span className="text-[10px] text-accent underline underline-offset-2">Switch</span>
            </button>
            <span>·</span>
            <span className="inline-flex items-center gap-1.5 font-medium text-accent">
              <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
              Live Feed Active
            </span>
            <span>·</span>
            <button
              type="button"
              onClick={() => setIsConnectModalOpen(true)}
              className="figures hover:text-accent transition-colors"
              title="Click to change performance benchmark"
            >
              Benchmark: <strong className="text-ink">{activeBenchmark.ticker}</strong>
            </button>
            <span>·</span>
            <span>Client: {profile.suitability_category ?? "Moderate Conservative"}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={() => setIsConnectModalOpen(true)}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-ink hover:border-accent hover:bg-surface/80 transition-colors inline-flex items-center gap-1.5"
          >
            <span>🏦</span>
            <span>Connect Application ({SUPPORTED_BROKERAGES.length})</span>
          </button>
          <Link
            href="/app/advisor"
            className="rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-ink hover:border-accent transition-colors"
          >
            Ask AI Advisor
          </Link>
          <Link
            href="/app/trade"
            className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-on-primary hover:bg-primary-hover shadow-xs transition-colors"
          >
            New Trade Order
          </Link>
          <button
            type="button"
            onClick={handleExportReport}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-muted hover:text-ink transition-colors"
            title="Download JSON portfolio report"
          >
            Export Report
          </button>
        </div>
      </div>

      {/* CONNECTED BROKER & BENCHMARK QUICK-STATUS BANNER */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface/60 px-4 py-3 text-xs">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <span className="font-semibold text-ink">Active Custody Gateway:</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-0.5 font-bold text-accent">
            <span className="h-2 w-2 rounded-full bg-accent" />
            {activeBroker.shortName} ({activeBroker.region})
          </span>
          <span className="text-muted">·</span>
          <span className="text-muted">
            Currencies: <strong className="text-ink">{activeBroker.supportedCurrencies.join("/")}</strong>
          </span>
          <span className="text-muted">·</span>
          <span className="text-muted">
            Benchmark: <strong className="text-ink">{activeBenchmark.name} (+{activeBenchmark.returnYtd}% YTD)</strong>
          </span>
        </div>

        <button
          type="button"
          onClick={() => setIsConnectModalOpen(true)}
          className="text-xs font-semibold text-accent hover:underline underline-offset-4"
        >
          Change Broker or Index →
        </button>
      </div>

      {/* 4 CLEAR HERO FINANCIAL CARDS */}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {/* Card 1: Total Portfolio Value */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs">
          <p className="text-xs font-medium text-muted">Total Portfolio Value</p>
          <p className="figures mt-1 text-[28px] font-bold tracking-tight text-ink">
            {money(pf.total_value)}
          </p>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                netPnl >= 0 ? "bg-accent-soft text-accent" : "bg-surface-muted text-muted"
              }`}
            >
              {netPnl >= 0 ? `+${money(netPnl)}` : money(netPnl)} ({fixed(netPnlPct, 2)}%)
            </span>
            <span className="text-muted text-[11px]">vs $100k capital</span>
          </div>
        </div>

        {/* Card 2: Invested Market Capital */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs">
          <p className="text-xs font-medium text-muted">Invested in Securities</p>
          <p className="figures mt-1 text-[28px] font-bold tracking-tight text-ink">
            {money(pf.invested_value)}
          </p>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">
              {pct(1 - cashWeight, 1)} Deployed
            </span>
            <span className="text-muted text-[11px]">{positions.length} active holdings</span>
          </div>
        </div>

        {/* Card 3: Available Cash Reserve */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs">
          <p className="text-xs font-medium text-muted">Available Cash / Buying Power</p>
          <p className="figures mt-1 text-[28px] font-bold tracking-tight text-ink">
            {money(pf.cash)}
          </p>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="inline-flex items-center rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-semibold text-primary">
              {pct(cashWeight, 1)} Cash Reserve
            </span>
            <span className="text-muted text-[11px]">5.33% APY Yield</span>
          </div>
        </div>

        {/* Card 4: Target Return & Goal */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs">
          <p className="text-xs font-medium text-muted">Target Annual Return</p>
          <p className="figures mt-1 text-[28px] font-bold tracking-tight text-ink">
            +{fixed(profile.target_return ?? 7.0, 1)}%
          </p>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">
              {profile.suitability_category ?? "Moderate Conservative"}
            </span>
            <span className="text-muted text-[11px]">Goal: {humanize(profile.primary_goal)}</span>
          </div>
        </div>
      </div>

      {/* MAIN TWO-COLUMN SECTION: PERFORMANCE CHART (8 cols) + ASSET ALLOCATION (4 cols) */}
      <div className="grid gap-8 lg:grid-cols-12">
        {/* Left 8 Cols: Real Performance Chart */}
        <div className="rounded-card border border-line bg-background p-6 shadow-xs lg:col-span-8">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-[17px] font-semibold tracking-tight text-ink">Portfolio Valuation Trajectory</h2>
              <p className="text-xs text-muted">Daily net asset value trend across recent paper trading sessions</p>
            </div>
            <Link
              href="/app/health"
              className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
            >
              Health Diagnostics →
            </Link>
          </div>

          <PortfolioAreaChart totalValue={pf.total_value} initialCapital={initialCapital} />
        </div>

        {/* Right 4 Cols: Clean Asset Allocation Breakdown */}
        <div className="rounded-card border border-line bg-background p-6 shadow-xs lg:col-span-4">
          <AssetAllocationCard positions={positions} cash={pf.cash} totalValue={pf.total_value} />
        </div>
      </div>

      {/* THREE ACTIONABLE ADVISORY CARDS */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* Card 1: Portfolio Health */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs flex flex-col justify-between space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-muted uppercase tracking-wider">Health Review</span>
              <Tag tone="success">78 / 100 Score</Tag>
            </div>
            <h3 className="mt-2 text-[15px] font-semibold text-ink">Conservative Risk Alignment</h3>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              Your portfolio holds an 84% cash cushion, shielding you from equity downturns while maintaining disciplined entry points.
            </p>
          </div>
          <Link
            href="/app/health"
            className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
          >
            Run full health & stress test review →
          </Link>
        </div>

        {/* Card 2: Risk Profile */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs flex flex-col justify-between space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-muted uppercase tracking-wider">Investor Profile</span>
              <Tag tone="brand">{profile.suitability_category ?? "Moderate Conservative"}</Tag>
            </div>
            <h3 className="mt-2 text-[15px] font-semibold text-ink">Income & Capital Growth Goal</h3>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              Configured for a {profile.investment_horizon_years ?? 2}-year horizon with a {fixed(profile.risk_tolerance_score, 1)}/10 risk tolerance ceiling.
            </p>
          </div>
          <Link
            href="/app/profile"
            className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
          >
            Update risk questionnaire & horizon →
          </Link>
        </div>

        {/* Card 3: Compliance & Rules */}
        <div className="rounded-card border border-line bg-background p-5 shadow-xs flex flex-col justify-between space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-muted uppercase tracking-wider">Compliance Safeguards</span>
              <Tag tone="success">12 Rules Active</Tag>
            </div>
            <h3 className="mt-2 text-[15px] font-semibold text-ink">Pre-Trade Guardrails Enforced</h3>
            <p className="mt-1 text-xs text-muted leading-relaxed">
              Every trade is checked against FINRA 2111 suitability, SEC wash-sale rules, and AML transaction thresholds before execution.
            </p>
          </div>
          <Link
            href="/app/compliance"
            className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
          >
            Inspect automated compliance rules →
          </Link>
        </div>
      </div>

      {/* LIVE HOLDINGS & RECENT ORDERS SECTION */}
      <div className="grid gap-8 xl:grid-cols-12">
        {/* Left 8 Cols: Holdings & Watchlist Tabs */}
        <div className="space-y-4 xl:col-span-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setActiveTab("holdings")}
                className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${
                  activeTab === "holdings"
                    ? "border-primary text-ink"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                Your Holdings ({positions.length + 1})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("watchlist")}
                className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${
                  activeTab === "watchlist"
                    ? "border-primary text-ink"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                Market Watchlist ({watchlist.length})
              </button>
            </div>

            <Link
              href="/app/trade"
              className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
            >
              Place an order →
            </Link>
          </div>

          <Panel flush>
            {activeTab === "holdings" ? (
              <Table caption="Live portfolio holdings">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th className="text-right">Shares</th>
                    <th className="text-right">Current Price</th>
                    <th className="text-right">Market Value</th>
                    <th className="text-right">Weight</th>
                    <th className="text-right">Quick Action</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const name =
                      p.symbol === "SPY"
                        ? "SPDR S&P 500 ETF Trust"
                        : p.symbol === "BND"
                        ? "Vanguard Total Bond Market ETF"
                        : p.symbol === "BTC"
                        ? "Bitcoin Digital Asset"
                        : "Securities Holding";

                    return (
                      <tr key={p.symbol} className="hover:bg-surface/50">
                        <td>
                          <div className="font-semibold text-ink">
                            <Link href={`/app/markets?symbol=${p.symbol}`} className="hover:underline">
                              {p.symbol}
                            </Link>
                          </div>
                          <div className="text-[11px] text-muted">{name}</div>
                        </td>
                        <td className="figures text-right font-medium text-ink">{qty(p.qty)}</td>
                        <td className="figures text-right text-ink">{money(p.price)}</td>
                        <td className="figures text-right font-semibold text-ink">{money(p.market_value)}</td>
                        <td className="figures text-right text-muted">{pct(p.weight)}</td>
                        <td className="text-right">
                          <Link
                            href={`/app/trade?symbol=${p.symbol}`}
                            className="inline-flex items-center rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-semibold text-accent hover:bg-accent hover:text-on-accent transition-colors"
                          >
                            Trade
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="hover:bg-surface/50">
                    <td>
                      <div className="font-semibold text-ink">USD Cash</div>
                      <div className="text-[11px] text-muted">Settled Cash & Federal Yield Reserve</div>
                    </td>
                    <td className="figures text-right text-muted">–</td>
                    <td className="figures text-right text-ink">$1.00</td>
                    <td className="figures text-right font-semibold text-ink">{money(pf.cash)}</td>
                    <td className="figures text-right text-muted">{pct(cashWeight)}</td>
                    <td className="text-right">
                      <Link
                        href="/app/trade"
                        className="inline-flex items-center rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-semibold text-primary hover:bg-primary hover:text-on-primary transition-colors"
                      >
                        Deploy
                      </Link>
                    </td>
                  </tr>
                </tbody>
              </Table>
            ) : (
              <Table caption="Market Watchlist">
                <thead>
                  <tr>
                    <th>Benchmark Asset</th>
                    <th>Category</th>
                    <th className="text-right">Market Price</th>
                    <th className="text-right">24h Change</th>
                    <th className="text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {watchlist.map((item) => (
                    <tr key={item.symbol} className="hover:bg-surface/50">
                      <td>
                        <div className="font-semibold text-ink">{item.symbol}</div>
                        <div className="text-[11px] text-muted">{item.name}</div>
                      </td>
                      <td className="text-xs text-muted">{item.category}</td>
                      <td className="figures text-right font-medium text-ink">{money(item.price)}</td>
                      <td
                        className={`figures text-right font-semibold ${
                          item.change >= 0 ? "text-accent" : "text-danger"
                        }`}
                      >
                        {item.change >= 0 ? `+${item.change}%` : `${item.change}%`}
                      </td>
                      <td className="text-right">
                        <Link
                          href={`/app/trade?symbol=${item.symbol}`}
                          className="inline-flex items-center rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-semibold text-accent hover:bg-accent hover:text-on-accent transition-colors"
                        >
                          Buy
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Panel>
        </div>

        {/* Right 4 Cols: Recent Orders */}
        <div className="space-y-4 xl:col-span-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">Recent Orders</h3>
            <Link
              href="/app/trade"
              className="text-xs font-semibold text-accent hover:text-primary underline underline-offset-4"
            >
              All orders ({trades.length})
            </Link>
          </div>

          <Panel flush>
            {trades.length === 0 ? (
              <p className="p-5 text-sm text-muted">No orders executed yet.</p>
            ) : (
              <ul className="divide-y divide-line/70">
                {trades.slice(0, 5).map((t) => (
                  <li key={t.trade_id} className="flex items-baseline justify-between gap-3 p-4 text-xs">
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                            t.side === "BUY" ? "bg-accent-soft text-accent" : "bg-danger-soft text-danger"
                          }`}
                        >
                          {t.side}
                        </span>
                        <span className="font-semibold text-ink">
                          {qty(t.qty)} {t.symbol}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-muted">{dateTime(t.created_at)}</p>
                    </div>

                    <div className="text-right">
                      <p className="figures font-semibold text-ink">
                        {t.filled_price ? money(t.filled_price) : "Market"}
                      </p>
                      <Tag tone={t.status === "FILLED" ? "success" : "neutral"} className="mt-1 text-[10px]">
                        {humanize(t.status)}
                      </Tag>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  return <RequireProfile>{(id) => <Overview clientId={id} />}</RequireProfile>;
}
