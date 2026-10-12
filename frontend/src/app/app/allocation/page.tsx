"use client";

import { useState } from "react";
import { BulletBars } from "@/components/charts/BulletBars";
import { LineChart } from "@/components/charts/LineChart";
import { ComplianceSummary } from "@/components/domain/Compliance";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Empty, ErrorNotice, Notice } from "@/components/ui/Feedback";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { fixed, money, pct, qty, signedPct } from "@/lib/format";
import type { AgentEvent } from "@/lib/types";
import { useAction } from "@/lib/useRequest";

const solverNames: Record<string, string> = {
  cvar_ratio: "CVaR ratio optimisation",
  min_variance: "Minimum variance (fallback)",
  inverse_volatility: "Inverse volatility (fallback)",
  equal_weighted: "Equal weight (fallback)",
  profile_heuristic: "Profile benchmark (fallback)",
};

function splitText(text = "") {
  const [head, ...rest] = text.split("\n\n");
  const m = head.match(/\(([^)]+)\)/);
  return { solver: m?.[1] ?? "", explanation: rest.join("\n\n") };
}

function Allocation({ clientId }: { clientId: string }) {
  const [events, setEvents] = useState<AgentEvent[] | null>(null);
  const { run, pending, error } = useAction(async () => {
    const res = await api.recommendAllocation(clientId);
    setEvents(res.events);
  });

  const check = events?.find((e) => e.event === "compliance_check");
  const result = events?.find((e) => e.agent === "AllocationEngine" && e.weights);

  if (!events) {
    return (
      <>
        <ErrorNotice error={error} onRetry={() => run()} />
        <Empty
          title="No recommendation generated yet"
          action={
            <Button onClick={() => run()} pending={pending}>
              Build my allocation
            </Button>
          }
        >
          The optimiser uses a year of daily prices for SPY, VTI, QQQ, BND, AGG and SHY. It limits any single fund according to your tier,
          then the result is checked against the suitability and concentration rules before it is shown here. This takes a few seconds.
        </Empty>
      </>
    );
  }

  if (!result) {
    return (
      <div className="space-y-6">
        <Notice tone="danger" title="The recommendation was withheld">
          It failed a blocking compliance rule, so it was not released. The reasons are below.
        </Notice>
        {check ? (
          <Panel title="Compliance">
            <ComplianceSummary passed={check.passed} details={check.details} violations={check.violations} />
          </Panel>
        ) : null}
        <Button variant="secondary" onClick={() => run()} pending={pending}>
          Try again
        </Button>
      </div>
    );
  }

  const weights = Object.entries(result.weights ?? {})
    .filter(([, w]) => w > 0.0005)
    .sort((a, b) => b[1] - a[1]);
  const m = result.metrics ?? {};
  const { solver, explanation } = splitText(result.text);
  const frontier = result.frontier ?? [];
  const annVol = m.annualized_volatility;
  const nearest = frontier.length && annVol !== undefined
    ? frontier.reduce((best, p, i) => (Math.abs(p.annualized_volatility - annVol) < Math.abs(frontier[best].annualized_volatility - annVol) ? i : best), 0)
    : undefined;
  const attributions = Object.entries(result.feature_attributions ?? {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const plan = result.rebalance_plan;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <p className="text-sm text-muted">
          Method: <span className="text-ink">{solverNames[solver] ?? solver}</span>
        </p>
        <Button variant="secondary" size="sm" onClick={() => run()} pending={pending}>
          Recalculate
        </Button>
      </div>
      <ErrorNotice error={error} />

      <div className="grid gap-8 xl:grid-cols-12">
        <div className="space-y-8 xl:col-span-7">
          <Panel title="Recommended weights">
            <BulletBars title="Recommended weight per fund" max={1} rows={weights.map(([s, w]) => ({ label: s, value: w }))} />
          </Panel>

          <Panel title="Why this mix">
            <div className="max-w-[70ch] space-y-3 text-[15px] whitespace-pre-line text-ink">{explanation}</div>
          </Panel>

          {frontier.length > 1 ? (
            <Panel title="Efficient frontier" aside={<span>Annualised, from one year of daily returns</span>}>
              <LineChart
                title="Efficient frontier: expected return against volatility"
                points={frontier.map((p) => ({
                  x: p.annualized_volatility,
                  y: p.annualized_return,
                  label: `Portfolio ${p.point_index + 1}`,
                  detail: `Sharpe ${fixed(p.sharpe_ratio)}`,
                }))}
                xLabel="Volatility"
                yLabel="Return"
                formatX={(v) => pct(v, 0)}
                formatY={(v) => pct(v, 1)}
                markers
                highlight={nearest}
                highlightLabel="Closest to yours"
              />
              <p className="mt-3 text-[13px] text-muted">
                Each point is the highest-return portfolio for its level of volatility. The square marks the frontier point nearest your
                recommended portfolio&rsquo;s volatility of {pct(annVol)}.
              </p>
            </Panel>
          ) : null}
        </div>

        <div className="space-y-8 xl:col-span-5">
          {check ? (
            <Panel title="Compliance">
              <ComplianceSummary passed={check.passed} details={check.details} violations={check.violations} />
            </Panel>
          ) : null}

          <Panel title="Expected characteristics">
            <Ledger
              rows={[
                { label: "Annualised volatility", value: pct(m.annualized_volatility) },
                { label: "Daily expected return", value: pct(m.expected_return, 3) },
                { label: "Sharpe ratio", value: fixed(m.sharpe_ratio) },
                { label: "CVaR at 95%", note: "Average loss on the worst 5% of days", value: pct(m.cvar_95, 2) },
                { label: "Max drawdown (history)", value: pct(m.max_drawdown, 1) },
              ]}
            />
            <p className="mt-3 text-[12.5px] text-muted">
              Estimates from historical prices. Investing involves risk, including possible loss of principal. Past performance is no
              guarantee of future results.
            </p>
          </Panel>

          {attributions.length ? (
            <Panel title="What drives the risk" flush>
              <Table caption="Attribution by fund">
                <thead>
                  <tr>
                    <Th>Fund</Th>
                    <Th numeric>Weight</Th>
                    <Th numeric>Attribution</Th>
                  </tr>
                </thead>
                <tbody>
                  {attributions.map(([s, v]) => (
                    <Tr key={s}>
                      <Td className="font-medium">{s}</Td>
                      <Td numeric>{pct(result.weights?.[s])}</Td>
                      <Td numeric>{Math.abs(v) < 0.01 ? v.toExponential(2) : fixed(v, 3)}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
              <p className="px-5 py-3 text-[13px] text-muted">
                Shares of portfolio risk (Euler decomposition), or SHAP contributions to the latest day&rsquo;s return when SHAP is available.
              </p>
            </Panel>
          ) : null}
        </div>
      </div>

      <Panel title="Moving from your current holdings" flush>
        {!plan ? (
          <p className="p-5 text-sm text-muted">You hold no funds yet, so there is nothing to rebalance. Draft purchases on the Trade page.</p>
        ) : plan.orders.length === 0 ? (
          <p className="p-5 text-sm text-muted">Your holdings already match these weights within tolerance.</p>
        ) : (
          <>
            <p className="px-5 pt-4 text-sm text-muted">
              Largest drift {pct(plan.max_drift)}, turnover {pct(plan.portfolio_turnover)}. Sales come first so they fund the purchases.
            </p>
            <Table caption="Rebalancing orders" className="mt-3">
              <thead>
                <tr>
                  <Th>Order</Th>
                  <Th numeric>Quantity</Th>
                  <Th numeric>Est. value</Th>
                  <Th numeric>Weight now</Th>
                  <Th numeric>Target</Th>
                  <Th numeric>Change</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {plan.orders.map((o) => (
                  <Tr key={`${o.side}${o.symbol}`}>
                    <Td className="font-medium">
                      {o.side === "BUY" ? "Buy" : "Sell"} {o.symbol}
                    </Td>
                    <Td numeric>{qty(o.qty)}</Td>
                    <Td numeric>{money(o.estimated_amount)}</Td>
                    <Td numeric>{pct(o.current_weight)}</Td>
                    <Td numeric>{pct(o.target_weight)}</Td>
                    <Td numeric>{signedPct(o.weight_delta)}</Td>
                    <Td className="text-right">
                      <ButtonLink
                        href={`/app/trade?symbol=${o.symbol}&side=${o.side}&qty=${Math.max(1, Math.floor(o.qty))}`}
                        variant="quiet"
                      >
                        Draft
                      </ButtonLink>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </>
        )}
      </Panel>
    </div>
  );
}

export default function AllocationPage() {
  return (
    <>
      <PageHeader title="Allocation" lede="A portfolio built from your profile, with the reasoning, the risk estimates and the compliance result." />
      <RequireProfile>{(id) => <Allocation clientId={id} />}</RequireProfile>
    </>
  );
}
