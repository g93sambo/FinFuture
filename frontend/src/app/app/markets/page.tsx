"use client";

import { useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Tag } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { big, dateTime, fixed, humanize, money, points } from "@/lib/format";
import type { Quote } from "@/lib/types";
import { useAction, useRequest } from "@/lib/useRequest";

const tenorOrder = ["1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
const quick = ["SPY", "VTI", "QQQ", "BND", "AGG", "GLD", "VXUS"];

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

function QuoteBlock() {
  const [input, setInput] = useState("SPY");
  const [quote, setQuote] = useState<Quote | null>(null);
  const { run, pending, error } = useAction(async (s: string) => setQuote(await api.quote(s)));
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
        <Field label="Ticker" className="flex-1">
          {(p) => <Input {...p} value={input} onChange={(e) => setInput(e.target.value.toUpperCase())} className="figures" spellCheck={false} />}
        </Field>
        <Button type="submit" pending={pending}>
          Look up
        </Button>
      </form>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {quick.map((s) => (
          <button key={s} type="button" onClick={() => lookup(s)} className="figures text-primary underline decoration-primary/30 underline-offset-4">
            {s}
          </button>
        ))}
      </div>
      <div className="mt-5">
        <ErrorNotice error={error} />
        {quote ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-ink pb-3">
              <p className="text-lg font-semibold text-ink">{quote.symbol}</p>
              <p className="figures text-[26px] text-ink">{money(quote.price)}</p>
              {quote.change_pct !== null ? (
                <p className={`figures text-sm ${quote.change_pct > 0 ? "text-success" : quote.change_pct < 0 ? "text-danger" : "text-muted"}`}>
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
          </>
        ) : !pending ? (
          <p className="text-sm text-muted">Pick a ticker to see the latest price.</p>
        ) : null}
      </div>
    </Panel>
  );
}

export default function MarketsPage() {
  const { data, error, loading, reload } = useRequest("macro", () => api.macro());
  const curve = data
    ? tenorOrder.filter((t) => typeof data.yield_curve[t] === "number").map((t, i) => ({ x: i, y: data.yield_curve[t], label: t }))
    : [];
  const y10 = data?.yield_curve["10Y"];
  const y2 = data?.yield_curve["2Y"];
  const spread = typeof y10 === "number" && typeof y2 === "number" ? y10 - y2 : null;

  return (
    <>
      <PageHeader title="Markets" lede="Prices, the Treasury curve and the macro figures the Advisor uses for context." />
      <div className="grid gap-8 xl:grid-cols-12">
        <div className="xl:col-span-5">
          <QuoteBlock />
        </div>
        <div className="space-y-8 xl:col-span-7">
          {loading && !data ? <Loading label="Loading the yield curve" /> : null}
          <ErrorNotice error={error} onRetry={reload} />
          {data ? (
            <>
              <Panel
                title="US Treasury yield curve"
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
