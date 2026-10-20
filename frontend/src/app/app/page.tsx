"use client";

import Link from "next/link";
import { useMemo } from "react";
import { LineChart, type LinePoint } from "@/components/charts/LineChart";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { ErrorNotice, Skeleton, Tag } from "@/components/ui/Feedback";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { dateTime, fixed, humanize, money, pct, qty } from "@/lib/format";
import type { PortfolioHistoryPoint } from "@/lib/types";
import { useRequest } from "@/lib/useRequest";

function OverviewSkeleton() {
  return (
    <div className="space-y-8 animate-fadeIn" aria-busy="true" aria-label="Loading portfolio">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="rounded-feature bg-surface p-5">
            <Skeleton height="14px" width="80px" />
            <div className="mt-2">
              <Skeleton height="26px" width="120px" />
            </div>
          </div>
        ))}
      </div>
      <Skeleton height="320px" width="100%" />
    </div>
  );
}

function StatCard({ label, value, note }: { label: string; value: string; note?: React.ReactNode }) {
  return (
    <div className="rounded-card border border-line bg-background p-5 shadow-xs">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="figures mt-1 text-[28px] font-bold tracking-tight text-ink">{value}</p>
      {note ? <div className="mt-2 text-xs text-muted">{note}</div> : null}
    </div>
  );
}

/** Recorded valuations; consecutive duplicates are collapsed so the line only moves on real changes. */
function ValuationChart({ points }: { points: PortfolioHistoryPoint[] }) {
  const series = useMemo<LinePoint[]>(() => {
    const out: LinePoint[] = [];
    for (const p of points) {
      const prev = out[out.length - 1];
      if (prev && Math.abs(prev.y - p.total_value) < 0.005) continue;
      out.push({ x: new Date(p.timestamp).getTime(), y: p.total_value, label: dateTime(p.timestamp) });
    }
    return out;
  }, [points]);

  const spanMs = series.length ? series[series.length - 1].x - series[0].x : 0;
  const shortSpan = spanMs < 2 * 24 * 3600 * 1000;

  if (series.length < 2) {
    return (
      <p className="py-10 text-center text-sm text-muted">
        Your valuation history starts with your first trade. Place an order and the chart will track every change from here.
      </p>
    );
  }
  return (
    <LineChart
      title="Recorded portfolio value"
      points={series}
      xLabel="Date"
      yLabel="Value (USD)"
      formatX={(v) =>
        shortSpan
          ? new Date(v).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
          : new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric" })
      }
      formatY={(v) => money(v)}
    />
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
  const history = useRequest(`pf-history:${clientId}`, () => api.portfolioHistory(clientId));

  if (loading && !data) return <OverviewSkeleton />;
  if (!data) return <ErrorNotice error={error ?? "Could not load your portfolio."} onRetry={reload} />;

  const [pf, profile, { trades }] = data;
  const positions = [...pf.positions].sort((a, b) => b.market_value - a.market_value);
  const cashWeight = pf.total_value > 0 ? pf.cash / pf.total_value : 1;
  const points = history.data?.points ?? [];
  const first = points.length ? points[0] : null;
  const change = first ? pf.total_value - first.total_value : null;

  function handleExportReport() {
    const payload = {
      exported_at: new Date().toISOString(),
      platform: "FinFuture",
      suitability_category: profile.suitability_category,
      risk_tolerance_score: profile.risk_tolerance_score,
      portfolio: pf,
      recent_trades: trades,
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "finfuture-portfolio-report.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-8">
      {error ? <ErrorNotice error={error} onRetry={reload} /> : null}

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-xs text-muted">
          Your paper-trading account (simulated money, orders sent to Alpaca paper) · Profile:{" "}
          <span className="font-semibold text-ink">{profile.suitability_category ?? "Not set"}</span>
        </p>
        <div className="flex flex-wrap items-center gap-2.5">
          <Link href="/app/advisor" className="rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-ink transition-colors hover:border-accent">
            Ask the advisor
          </Link>
          <Link href="/app/trade" className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-on-primary shadow-xs transition-colors hover:bg-primary-hover">
            New order
          </Link>
          <button
            type="button"
            onClick={handleExportReport}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-muted transition-colors hover:text-ink"
          >
            Export report (JSON)
          </button>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total portfolio value"
          value={money(pf.total_value)}
          note={
            change === null ? null : (
              <span className={change >= 0 ? "font-semibold text-accent" : "font-semibold text-danger"}>
                {change >= 0 ? "+" : ""}
                {money(change)} since {dateTime(first!.timestamp)}
              </span>
            )
          }
        />
        <StatCard label="Invested in securities" value={money(pf.invested_value)} note={`${pct(1 - cashWeight, 1)} invested · ${positions.length} holdings`} />
        <StatCard label="Cash available" value={money(pf.cash)} note={`${pct(cashWeight, 1)} of portfolio`} />
        <StatCard
          label="Target annual return"
          value={profile.target_return != null ? `${fixed(profile.target_return, 1)}%` : "–"}
          note={`Goal: ${humanize(profile.primary_goal)} · ${profile.investment_horizon_years ?? "–"}-year horizon`}
        />
      </div>

      <div className="grid gap-8 lg:grid-cols-12">
        <div className="rounded-card border border-line bg-background p-6 shadow-xs lg:col-span-8">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-[17px] font-semibold tracking-tight text-ink">Portfolio value</h2>
              <p className="text-xs text-muted">Valuations recorded by the platform after trades and portfolio refreshes</p>
            </div>
            <Link href="/app/health" className="text-xs font-semibold text-accent underline underline-offset-4 hover:text-primary">
              Health review →
            </Link>
          </div>
          {history.loading && !history.data ? <Skeleton height="260px" width="100%" /> : <ValuationChart points={points} />}
        </div>

        <div className="rounded-card border border-line bg-background p-6 shadow-xs lg:col-span-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[15px] font-semibold tracking-tight text-ink">Current allocation</h3>
            <Link href="/app/allocation" className="text-xs font-medium text-accent underline underline-offset-4 hover:text-primary">
              Get a target allocation
            </Link>
          </div>
          <ul className="mt-4 divide-y divide-line/70 text-xs">
            {[...positions.map((p) => ({ key: p.symbol, label: p.symbol, value: p.market_value, weight: p.weight })), { key: "CASH", label: "Cash (USD)", value: pf.cash, weight: cashWeight }].map((row) => (
              <li key={row.key} className="py-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-ink">{row.label}</span>
                  <span className="figures text-ink">
                    {money(row.value)} <span className="text-muted">· {pct(row.weight, 1)}</span>
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.max(row.weight * 100, 1))}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid gap-8 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-8">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">Holdings ({positions.length})</h3>
            <Link href="/app/trade" className="text-xs font-semibold text-accent underline underline-offset-4 hover:text-primary">
              Place an order →
            </Link>
          </div>
          <Panel flush>
            {positions.length === 0 ? (
              <p className="p-5 text-sm text-muted">No holdings yet. Your cash is {money(pf.cash)}.</p>
            ) : (
              <Table caption="Portfolio holdings">
                <thead>
                  <tr>
                    <Th>Symbol</Th>
                    <Th numeric>Shares</Th>
                    <Th numeric>Price</Th>
                    <Th numeric>Market value</Th>
                    <Th numeric>Weight</Th>
                    <Th numeric>
                      <span className="sr-only">Actions</span>
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <Tr key={p.symbol}>
                      <Td className="font-semibold">
                        <Link href={`/app/markets?symbol=${p.symbol}`} className="hover:underline">
                          {p.symbol}
                        </Link>
                      </Td>
                      <Td numeric>{qty(p.qty)}</Td>
                      <Td numeric>{money(p.price)}</Td>
                      <Td numeric className="font-semibold">{money(p.market_value)}</Td>
                      <Td numeric className="text-muted">{pct(p.weight)}</Td>
                      <Td numeric>
                        <Link
                          href={`/app/trade?symbol=${p.symbol}`}
                          className="inline-flex items-center rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-semibold text-accent transition-colors hover:bg-accent hover:text-on-accent"
                        >
                          Trade
                        </Link>
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Panel>

          <Panel title="Next steps">
            <ul className="grid gap-x-8 gap-y-4 text-sm sm:grid-cols-2">
              {[
                ["/app/health", "Run a health review", "Drift, concentration and stress scenarios."],
                ["/app/allocation", "Get an allocation", "Optimised for your profile, with reasons."],
                ["/app/compare", "Compare funds", "Six-factor scores for any tickers you choose."],
                ["/app/audit", "Verify your audit trail", "Recompute every hash and signature."],
              ].map(([href, label, note]) => (
                <li key={href}>
                  <Link href={href} className="font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary">
                    {label}
                  </Link>
                  <p className="text-[0.9375rem] text-muted">{note}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="space-y-4 xl:col-span-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">Recent orders</h3>
            <Link href="/app/trade" className="text-xs font-semibold text-accent underline underline-offset-4 hover:text-primary">
              All orders
            </Link>
          </div>
          <Panel flush>
            {trades.length === 0 ? (
              <p className="p-5 text-sm text-muted">No orders yet.</p>
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
                      <p className="figures font-semibold text-ink">{t.filled_price ? money(t.filled_price) : "–"}</p>
                      <div className="mt-1 flex justify-end gap-1">
                        <Tag tone={t.status === "FILLED" ? "success" : "neutral"}>{humanize(t.status)}</Tag>
                        {t.simulated ? <Tag tone="warning">Simulated</Tag> : null}
                      </div>
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
  return (
    <>
      <PageHeader title="Overview" lede="Here's where your money stands today." />
      <RequireProfile>{(id) => <Overview clientId={id} />}</RequireProfile>
    </>
  );
}
