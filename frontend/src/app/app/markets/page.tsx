"use client";

import { useEffect, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { TickerAutocomplete } from "@/components/domain/TickerAutocomplete";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Skeleton, Tag } from "@/components/ui/Feedback";
import { Field } from "@/components/ui/Field";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { big, dateTime, fixed, humanize, money, points } from "@/lib/format";
import type { PriceHistoryResponse, Quote } from "@/lib/types";
import { useAction, useRequest } from "@/lib/useRequest";

const tenorOrder = ["1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
const quick = ["SPY", "VTI", "QQQ", "BND", "AGG", "GLD", "VXUS", "NVDA", "AAPL", "MSFT"];
const periods = [
  { id: "1mo", label: "1M" },
  { id: "3mo", label: "3M" },
  { id: "6mo", label: "6M" },
  { id: "1y", label: "1Y" },
] as const;

const macroLabels: Record<string, string> = {
  cpi: "Inflation (CPI)",
  unemployment_rate: "Unemployment rate",
  fed_funds_rate: "Fed funds rate",
  gdp_growth_rate: "GDP growth",
  treasury_10y_yield: "10-year Treasury",
};

function sourceLabel(s: string) {
  if (s === "fixture") return "Recorded snapshot";
  if (s === "cache") return "Cached";
  if (s === "yfinance") return "Yahoo Finance";
  return humanize(s);
}

function QuoteBlock({
  activeSymbol,
  onSelectSymbol,
}: {
  activeSymbol: string;
  onSelectSymbol: (sym: string) => void;
}) {
  const [input, setInput] = useState(activeSymbol);
  const [quote, setQuote] = useState<Quote | null>(null);
  const { run, pending, error } = useAction(async (s: string) => {
    const q = await api.quote(s);
    setQuote(q);
    onSelectSymbol(s);
  });

  useEffect(() => {
    void run(activeSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lookup = (s: string) => {
    setInput(s);
    void run(s);
  };

  return (
    <Panel title="Quote">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) void run(input.trim().toUpperCase());
        }}
        className="flex items-end gap-3"
      >
        <Field label="Ticker / Security Name" className="flex-1">
          {() => (
            <TickerAutocomplete
              value={input}
              onChange={(val) => setInput(val.toUpperCase())}
              onSelectSymbol={(sym) => {
                setInput(sym);
                void run(sym);
              }}
              placeholder="Search ticker or name (e.g. SPY, Apple, Vanguard)..."
            />
          )}
        </Field>
        <Button type="submit" pending={pending}>
          Look up
        </Button>
      </form>
      <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
        {quick.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => lookup(s)}
            className={`figures rounded-full px-2.5 py-1 font-medium transition-all duration-140 ease-out active:scale-95 ${
              activeSymbol === s
                ? "bg-primary text-on-primary shadow-xs"
                : "border border-line bg-surface text-muted hover:text-ink"
            }`}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="mt-5">
        <ErrorNotice error={error} />
        {quote ? (
          <div className={`transition-opacity duration-140 ${pending ? "opacity-60" : "opacity-100"}`}>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line pb-3">
              <p className="text-lg font-semibold text-ink">{quote.symbol}</p>
              <p className="figures text-[26px] font-bold text-ink">{money(quote.price)}</p>
              {quote.change_pct !== null ? (
                <p className={`figures text-sm font-medium ${quote.change_pct > 0 ? "text-success" : quote.change_pct < 0 ? "text-danger" : "text-muted"}`}>
                  {quote.change_pct > 0 ? "+" : ""}
                  {fixed(quote.change, 2)} ({quote.change_pct > 0 ? "+" : ""}
                  {fixed(quote.change_pct, 2)}%)
                </p>
              ) : null}
            </div>
            <Ledger
              rows={[
                { label: "Bid / ask", value: `${money(quote.bid)} / ${money(quote.ask)}` },
                { label: "Open", value: money(quote.open) },
                { label: "Day range", value: `${money(quote.low)} – ${money(quote.high)}` },
                { label: "Previous close", value: money(quote.previous_close) },
                { label: "Volume", value: big(quote.volume) },
              ]}
            />
            <p className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              <Tag tone={quote.source === "fixture" ? "warning" : "neutral"}>{sourceLabel(quote.source)}</Tag>
              as of {dateTime(quote.timestamp)}
            </p>
          </div>
        ) : pending ? (
          <div className="space-y-4 py-2 animate-fadeIn">
            <div className="flex gap-4 items-baseline border-b border-line pb-3">
              <Skeleton height="20px" width="60px" />
              <Skeleton height="32px" width="100px" />
            </div>
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex justify-between">
                  <Skeleton height="14px" width="80px" />
                  <Skeleton height="14px" width="90px" />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted">Pick a ticker to see the latest price.</p>
        )}
      </div>
    </Panel>
  );
}

export default function MarketsPage() {
  const [activeSymbol, setActiveSymbol] = useState("SPY");
  const [period, setPeriod] = useState<string>("6mo");

  const { data: historyData, loading: historyLoading, error: historyError } = useRequest<PriceHistoryResponse>(
    `history:${activeSymbol}:${period}`,
    () => api.history(activeSymbol, period)
  );

  const { data, error, loading, reload } = useRequest("macro", () => api.macro());

  const pricePoints = historyData?.points
    ? historyData.points.map((pt, idx) => ({
        x: idx,
        y: pt.close,
        label: pt.date.slice(5), // MM-DD
      }))
    : [];

  // Downsample labels if many points so x-axis stays crisp
  const sampledPricePoints =
    pricePoints.length > 14
      ? pricePoints.filter((_, i) => i === 0 || i === pricePoints.length - 1 || i % Math.ceil(pricePoints.length / 8) === 0).map((p, idx) => ({ ...p, x: idx }))
      : pricePoints;

  const curve = data
    ? tenorOrder.filter((t) => typeof data.yield_curve[t] === "number").map((t, i) => ({ x: i, y: data.yield_curve[t], label: t }))
    : [];
  const y10 = data?.yield_curve["10Y"];
  const y2 = data?.yield_curve["2Y"];
  const spread = typeof y10 === "number" && typeof y2 === "number" ? y10 - y2 : null;

  return (
    <>
      <PageHeader title="Markets" lede="Live equity & ETF price history, the sovereign US Treasury yield curve, and macroeconomic benchmarks." />
      <div className="grid gap-8 xl:grid-cols-12">
        <div className="xl:col-span-5">
          <QuoteBlock activeSymbol={activeSymbol} onSelectSymbol={setActiveSymbol} />
        </div>
        <div className="space-y-8 xl:col-span-7">
          {/* Dynamic Ticker Historical Price Chart */}
          <Panel
            title={`${activeSymbol} price performance`}
            aside={
              <div className="flex items-center gap-3">
                {historyData ? (
                  <Tag tone={historyData.period_return_pct >= 0 ? "success" : "danger"}>
                    {historyData.period_return_pct >= 0 ? "+" : ""}
                    {fixed(historyData.period_return_pct, 2)}% ({period.toUpperCase()})
                  </Tag>
                ) : null}
                <div className="flex rounded-full border border-line bg-surface p-0.5 gap-0.5">
                  {periods.map((p) => {
                    const isActive = period === p.id;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setPeriod(p.id)}
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-medium transition-all duration-140 ease-out active:scale-95 ${
                          isActive
                            ? "bg-primary text-on-primary shadow-xs font-semibold"
                            : "text-muted hover:text-ink"
                        }`}
                      >
                        {isActive && historyLoading && (
                          <span className="h-2 w-2 animate-spin rounded-full border border-white border-t-transparent" />
                        )}
                        <span>{p.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            }
          >
            <div className="relative min-h-[220px]">
              {/* Active Loading Overlay during timeframe change */}
              {historyLoading && (
                <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-xl bg-background/75 backdrop-blur-[2px] transition-all duration-200 animate-fadeIn">
                  <div className="flex items-center gap-2.5 rounded-full border border-line bg-background px-4 py-2 shadow-md">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
                    <span className="text-xs font-semibold text-ink">
                      Loading {activeSymbol} {periods.find((p) => p.id === period)?.label ?? period} data…
                    </span>
                  </div>
                </div>
              )}

              <div className={`transition-opacity duration-200 ${historyLoading ? "opacity-30" : "opacity-100"}`}>
                <ErrorNotice error={historyError} />
                {sampledPricePoints.length > 1 ? (
                  <LineChart
                    title={`${activeSymbol} historical closing price`}
                    points={sampledPricePoints}
                    categoricalX
                    xLabel="Date"
                    yLabel="Price (USD)"
                    formatX={(v) => String(v)}
                    formatY={(v) => `$${v.toFixed(0)}`}
                  />
                ) : !historyLoading ? (
                  <p className="text-sm text-muted py-8 text-center">No historical price series available for {activeSymbol}.</p>
                ) : null}
              </div>
            </div>
          </Panel>

          {loading && !data ? (
            <Panel title="US Treasury yield curve (Sovereign benchmark)">
              <div className="h-[220px] flex items-center justify-center border border-dashed border-line bg-surface/30">
                <Loading label="Loading the yield curve" />
              </div>
            </Panel>
          ) : null}
          <ErrorNotice error={error} onRetry={reload} />
          {data ? (
            <>
              <Panel
                title="US Treasury yield curve (Sovereign benchmark)"
                aside={
                  spread !== null ? (
                    <Tag tone={spread < 0 ? "warning" : "neutral"}>
                      10Y minus 2Y {spread > 0 ? "+" : ""}
                      {fixed(spread, 2)} pts{spread < 0 ? ", inverted" : ""}
                    </Tag>
                  ) : null
                }
              >
                {curve.length > 1 ? (
                  <LineChart
                    title="Treasury yield by maturity"
                    points={curve}
                    categoricalX
                    xLabel="Maturity"
                    yLabel="Yield"
                    formatX={(v) => String(v)}
                    formatY={(v) => `${v.toFixed(2)}%`}
                  />
                ) : (
                  <p className="text-sm text-muted">No curve data available.</p>
                )}
                <details className="mt-4">
                  <summary className="cursor-pointer text-[13px] text-primary underline decoration-primary/30 underline-offset-4">Show as a table</summary>
                  <Table caption="Treasury yields" className="mt-3">
                    <thead>
                      <tr>
                        {curve.map((c) => (
                          <Th key={c.label} numeric>
                            {c.label}
                          </Th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {curve.map((c) => (
                          <Td key={c.label} numeric>
                            {points(c.y)}
                          </Td>
                        ))}
                      </tr>
                    </tbody>
                  </Table>
                </details>
              </Panel>

              <Panel title="Macro indicators" aside={<span>Retrieved {dateTime(data.as_of)}</span>}>
                <Ledger
                  rows={Object.entries(data.macro)
                    .filter(([k]) => k in macroLabels)
                    .map(([k, v]) => ({ label: macroLabels[k], value: points(v) }))}
                />
                <p className="mt-3 text-[13px] text-muted">
                  From FRED when a key is configured, otherwise a recorded snapshot. CPI from FRED is the index level rather than a rate.
                </p>
              </Panel>
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}
