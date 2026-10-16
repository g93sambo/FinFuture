"use client";

import { BulletBars } from "@/components/charts/BulletBars";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ErrorNotice, Notice, Skeleton, Tag, type Tone } from "@/components/ui/Feedback";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { dateTime, fixed, humanize, money, pct, qty, signedPct } from "@/lib/format";
import type { HealthReport } from "@/lib/types";
import { useRequest } from "@/lib/useRequest";

const gradeTone: Record<HealthReport["health_grade"], Tone> = {
  EXCELLENT: "success",
  GOOD: "success",
  FAIR: "warning",
  POOR: "danger",
  CRITICAL: "danger",
};
const alertTone: Record<string, Tone> = { INFO: "neutral", WARNING: "warning", CRITICAL: "danger" };

function ScoreScale({ score }: { score: number }) {
  const bands = [
    ["Critical", 0, 30],
    ["Poor", 30, 50],
    ["Fair", 50, 70],
    ["Good", 70, 85],
    ["Excellent", 85, 100],
  ] as const;
  return (
    <div aria-hidden>
      <div className="relative flex h-3">
        {bands.map(([name, a, b], i) => (
          <span key={name} className={`h-full ${i > 0 ? "border-l-2 border-background" : ""} ${score >= a && score < b + (b === 100 ? 1 : 0) ? "bg-primary" : "bg-chart-track"}`} style={{ width: `${b - a}%` }} />
        ))}
        <span className="absolute -top-1.5 h-6 w-0.5 bg-ink" style={{ left: `calc(${Math.min(100, Math.max(0, score))}% - 1px)` }} />
      </div>
      <div className="mt-1.5 flex text-[12px] text-muted">
        {bands.map(([name, a, b]) => (
          <span key={name} style={{ width: `${b - a}%` }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}

function Report({ r, rerun, pending }: { r: HealthReport; rerun: () => void; pending: boolean }) {
  const sb = r.score_breakdown;
  const drifts = Object.values(r.drift_analysis.asset_drifts).sort((a, b) => b.absolute_drift - a.absolute_drift);
  const bc = r.benchmark_comparison;
  const plan = r.rebalancing_plan;
  const n = r.narrative;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4 text-sm text-muted">
        <span>
          Prepared {dateTime(r.timestamp)} · {r.portfolio_summary.holdings_count} holdings · {money(r.portfolio_summary.total_value)}
        </span>
        <Button variant="secondary" size="sm" onClick={rerun} pending={pending}>
          Run again
        </Button>
      </div>

      <div className="grid gap-8 xl:grid-cols-12">
        <Panel title="Health score" className="xl:col-span-7">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
            <p className="figures text-[40px] leading-none text-ink">{fixed(r.health_score, 0)}</p>
            <p className="text-muted">out of 100</p>
            <Tag tone={gradeTone[r.health_grade]}>{humanize(r.health_grade)}</Tag>
          </div>
          <div className="mt-6">
            <ScoreScale score={r.health_score} />
          </div>
          <p className="mt-6 max-w-[68ch] text-[15px] text-ink">{n.executive_summary}</p>
        </Panel>

        <Panel title="How the score is built" className="xl:col-span-5">
          <Ledger
            rows={[
              { label: "Starting point", value: fixed(sb.base_potential, 1) },
              { label: "Diversification", note: "Up to +20 for more effective holdings", value: `+${fixed(sb.diversification_reward, 1)}` },
              { label: "Drift from target", note: "Up to −40", value: `−${fixed(sb.drift_penalty, 1)}` },
              { label: "Concentration", note: "Up to −20 for positions above 20%", value: `−${fixed(sb.concentration_penalty, 1)}` },
              { label: "Fit with your risk level", note: "Up to −20", value: `−${fixed(sb.risk_misalignment_penalty, 1)}` },
              { label: <span className="font-medium text-ink">Score</span>, value: <span className="font-semibold">{fixed(sb.final_score, 1)}</span> },
            ]}
          />
        </Panel>
      </div>

      {r.alerts.length ? (
        <Panel title={`Alerts (${r.alerts.length})`}>
          <ul className="divide-y divide-line">
            {r.alerts.map((a) => (
              <li key={a.alert_type} className="grid gap-x-6 gap-y-1 py-3 md:grid-cols-[8rem_1fr]">
                <span>
                  <Tag tone={alertTone[a.severity] ?? "neutral"}>{humanize(a.severity)}</Tag>
                </span>
                <div>
                  <p className="font-medium text-ink">{a.title}</p>
                  <p className="mt-0.5 text-sm text-ink">{a.message}</p>
                  <p className="mt-1 text-[13px] text-muted">{a.action_recommended}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      ) : (
        <Notice tone="success" title="No alerts">
          Drift, concentration and volatility are all within limits.
        </Notice>
      )}

      <div className="grid gap-8 xl:grid-cols-12">
        <Panel title="Drift from target" className="xl:col-span-7" aside={<span>Threshold {pct(r.drift_analysis.threshold, 0)}</span>}>
          <BulletBars
            title="Current weight against target weight"
            max={Math.max(...drifts.map((d) => Math.max(d.current_weight, d.target_weight)), 0.01)}
            rows={drifts.map((d) => ({ label: d.symbol, value: d.current_weight, target: d.target_weight, valueText: pct(d.current_weight) }))}
          />
          <p className="mt-4 text-sm text-ink">{n.drift_diagnosis}</p>
        </Panel>

        <Panel title="Concentration" className="xl:col-span-5">
          <Ledger
            rows={[
              { label: "Largest holding", value: `${r.concentration_metrics.max_position_symbol} ${pct(r.concentration_metrics.max_position_weight)}` },
              { label: "Top three together", value: pct(r.concentration_metrics.top_3_concentration) },
              { label: "Herfindahl index", note: "Sum of squared weights", value: fixed(r.concentration_metrics.herfindahl_index, 3) },
              { label: "Effective holdings", note: "1 / Herfindahl", value: fixed(r.concentration_metrics.effective_asset_count, 1) },
            ]}
          />
          <p className="mt-4 text-sm text-ink">{n.risk_and_concentration_diagnosis}</p>
        </Panel>
      </div>

      <Panel title={`Against ${bc.benchmark_name}`} flush>
        <Table caption="Portfolio against benchmark">
          <thead>
            <tr>
              <Th>Measure</Th>
              <Th numeric>Your portfolio</Th>
              <Th numeric>60/40</Th>
              <Th numeric>Difference</Th>
            </tr>
          </thead>
          <tbody>
            <Tr>
              <Td>Expected annual return</Td>
              <Td numeric>{pct(bc.portfolio_annualized_return)}</Td>
              <Td numeric>{pct(bc.benchmark_annualized_return)}</Td>
              <Td numeric>{signedPct(bc.excess_return)}</Td>
            </Tr>
            <Tr>
              <Td>Volatility</Td>
              <Td numeric>{pct(bc.portfolio_volatility)}</Td>
              <Td numeric>{pct(bc.benchmark_volatility)}</Td>
              <Td numeric>{fixed(bc.relative_volatility)}×</Td>
            </Tr>
            <Tr>
              <Td>Sharpe ratio</Td>
              <Td numeric>{fixed(bc.portfolio_sharpe_ratio)}</Td>
              <Td numeric>{fixed(bc.benchmark_sharpe_ratio)}</Td>
              <Td numeric>{fixed(bc.portfolio_sharpe_ratio - bc.benchmark_sharpe_ratio)}</Td>
            </Tr>
            {["Equity", "Fixed Income", "Alternative"].map((k) => (
              <Tr key={k}>
                <Td>{k} share</Td>
                <Td numeric>{pct(bc.asset_mix_comparison.Portfolio?.[k])}</Td>
                <Td numeric>{pct(bc.asset_mix_comparison.Benchmark?.[k])}</Td>
                <Td numeric>{signedPct((bc.asset_mix_comparison.Portfolio?.[k] ?? 0) - (bc.asset_mix_comparison.Benchmark?.[k] ?? 0))}</Td>
              </Tr>
            ))}
            <Tr>
              <Td>Beta to benchmark</Td>
              <Td numeric>{fixed(bc.beta_to_benchmark)}</Td>
              <Td numeric>1.00</Td>
              <Td numeric />
            </Tr>
          </tbody>
        </Table>
        <p className="px-5 py-3 text-[13px] text-muted">
          Returns and volatilities are long-run assumptions per fund, not forecasts. {n.benchmark_comparison_narrative}
        </p>
      </Panel>

      <Panel title="Rebalancing plan" flush aside={<span>Tolerance ±{pct(plan.tolerance_band, 0)}</span>}>
        {plan.orders.length === 0 ? (
          <p className="p-5 text-sm text-muted">Every holding is within tolerance. No orders needed.</p>
        ) : (
          <>
            <Table caption="Rebalancing orders">
              <thead>
                <tr>
                  <Th>Order</Th>
                  <Th numeric>Quantity</Th>
                  <Th numeric>Est. value</Th>
                  <Th numeric>Now</Th>
                  <Th numeric>Target</Th>
                  <Th numeric>After</Th>
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
                    <Td numeric>{pct(o.post_rebalance_weight)}</Td>
                    <Td className="text-right">
                      <ButtonLink href={`/app/trade?symbol=${o.symbol}&side=${o.side}&qty=${Math.max(1, Math.floor(o.qty))}`} variant="quiet">
                        Draft
                      </ButtonLink>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <p className="px-5 py-3 text-[13px] text-muted">
              Cash {money(plan.cash_before)} before, about {money(plan.estimated_cash_after)} after. Turnover {pct(plan.portfolio_turnover)}.
            </p>
          </>
        )}
      </Panel>

      <Panel title="Recommendations">
        <ol className="list-inside list-decimal space-y-1.5 text-[15px] text-ink marker:text-muted">
          {n.actionable_recommendations.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ol>
        <p className="mt-4 border-t border-line pt-3 text-[12.5px] text-muted">{n.regulatory_disclosure}</p>
      </Panel>
    </div>
  );
}

function HealthSkeleton() {
  return (
    <div className="space-y-8 animate-fadeIn" aria-busy="true" aria-label="Running health review">
      <div className="flex justify-between items-center border-b border-line pb-4">
        <Skeleton height="16px" width="300px" />
        <Skeleton height="32px" width="90px" />
      </div>
      <div className="grid gap-8 xl:grid-cols-12">
        <Panel title="Health score" className="xl:col-span-7">
          <div className="flex items-baseline gap-4">
            <Skeleton height="40px" width="70px" />
            <Skeleton height="20px" width="80px" />
          </div>
          <div className="mt-6">
            <Skeleton height="24px" width="100%" />
          </div>
          <div className="mt-6 space-y-2">
            <Skeleton height="16px" width="100%" />
            <Skeleton height="16px" width="90%" />
          </div>
        </Panel>
        <Panel title="How the score is built" className="xl:col-span-5">
          <div className="space-y-4 py-2">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="flex justify-between items-center">
                <Skeleton height="14px" width="120px" />
                <Skeleton height="14px" width="50px" />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Health({ clientId }: { clientId: string }) {
  const { data, error, loading, reload } = useRequest(`health:${clientId}`, () => api.healthReport(clientId));
  if (loading && !data) return <HealthSkeleton />;
  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return null;
  return <Report r={data} rerun={reload} pending={loading} />;
}

export default function HealthPage() {
  return (
    <>
      <PageHeader
        title="Health review"
        lede="Drift against your target mix, concentration, a comparison with a 60/40 portfolio, and the trades that would fix any gaps."
      />
      <RequireProfile>{(id) => <Health clientId={id} />}</RequireProfile>
    </>
  );
}
