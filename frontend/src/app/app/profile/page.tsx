"use client";

import { BulletBars } from "@/components/charts/BulletBars";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { ErrorNotice, Loading, Tag } from "@/components/ui/Feedback";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api";
import { dateTime, fixed, humanize, money, pct } from "@/lib/format";
import { useRequest } from "@/lib/useRequest";

const tierOrder = ["Conservative", "Moderate Conservative", "Moderate", "Growth", "Aggressive Growth"];

function Profile({ clientId }: { clientId: string }) {
  const { data: p, error, loading, reload } = useRequest(`profile:${clientId}`, () => api.profile(clientId));
  if (loading && !p) return <Loading label="Loading your profile" />;
  if (error) return <ErrorNotice error={error} onRetry={reload} />;
  if (!p) return null;

  const reserveMonths = p.monthly_expenses && p.monthly_expenses > 0 && p.liquid_assets !== null ? p.liquid_assets / p.monthly_expenses : null;
  const tierIdx = tierOrder.indexOf(p.suitability_category ?? "");

  return (
    <div className="grid gap-8 xl:grid-cols-12">
      <div className="space-y-8 xl:col-span-7">
        <Panel title="Suitability">
          <p className="text-sm text-muted">Tier assigned from your answers. Each step up allows more equity and more volatility.</p>
          <ol className="mt-4 grid grid-cols-5 border border-line text-center text-[0.875rem]">
            {tierOrder.map((t, i) => (
              <li
                key={t}
                className={`px-1 py-2.5 ${i > 0 ? "border-l border-line" : ""} ${i === tierIdx ? "bg-primary font-semibold text-on-primary" : "text-muted"}`}
                aria-current={i === tierIdx ? "true" : undefined}
              >
                {t}
              </li>
            ))}
          </ol>
          <Ledger
            className="mt-5"
            rows={[
              { label: "Stated risk tolerance", value: `${fixed(p.risk_tolerance_score, 1)} / 10` },
              { label: "Investment horizon", value: p.investment_horizon_years ? `${p.investment_horizon_years} years` : "–" },
              { label: "Primary goal", value: humanize(p.primary_goal) },
              { label: "Target return", value: p.target_return !== null ? `${fixed(p.target_return, 1)}% a year` : "–" },
              { label: "Capacity for loss", value: humanize(p.loss_capacity) },
              { label: "Liquidity needs", value: humanize(p.liquidity_needs) },
              { label: "Experience", value: humanize(p.investment_experience) },
            ]}
          />
        </Panel>

        <Panel title="Finances">
          <Ledger
            rows={[
              { label: "Annual income", value: money(p.annual_income) },
              { label: "Liquid savings", value: money(p.liquid_assets) },
              { label: "Monthly expenses", value: money(p.monthly_expenses) },
              { label: "Existing debts", value: money(p.existing_debts) },
              { label: "Net worth (estimated)", value: money(p.net_worth) },
              {
                label: "Emergency reserve",
                note: "Savings divided by monthly expenses. Under three months caps your suitability.",
                value: reserveMonths !== null ? `${fixed(reserveMonths, 1)} months` : "–",
              },
              { label: "Age", value: p.age ?? "–" },
              { label: "Employment", value: humanize(p.employment_status) },
              { label: "Dependents", value: p.dependents ?? 0 },
            ]}
          />
        </Panel>
      </div>

      <div className="space-y-8 xl:col-span-5">
        <Panel title="Behaviour">
          <BulletBars
            title="Behavioural indicators"
            max={1}
            rows={[
              {
                label: "Emotional",
                sublabel: "Emotional risk score",
                value: (p.emotional_risk_score ?? 0) / 100,
                valueText: `${fixed(p.emotional_risk_score, 0)} / 100`,
              },
              { label: "Panic sell", sublabel: "Likelihood of selling after a 20% fall", value: p.panic_sell_likelihood ?? 0, valueText: pct(p.panic_sell_likelihood, 0) },
            ]}
          />
          <p className="mt-4 text-[0.9375rem] text-muted">
            Emotional risk combines your stated reaction to a fall, how often you check, detected biases and financial stress. Panic-sell
            likelihood is a logistic estimate for a 20% drawdown. Both rise when the Advisor detects a bias in conversation.
          </p>
          <div className="mt-5 border-t border-line pt-4">
            <p className="mb-2 text-sm font-medium text-ink">Biases noticed so far</p>
            {p.detected_biases?.length ? (
              <div className="flex flex-wrap gap-2">
                {p.detected_biases.map((b) => (
                  <Tag key={b} tone="warning">
                    {humanize(b)}
                  </Tag>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">None recorded.</p>
            )}
          </div>
        </Panel>

        <Panel title="Identity checks">
          <Ledger
            rows={[
              { label: "KYC", value: p.kyc_verified ? <Tag tone="success">Verified</Tag> : <Tag tone="danger">Not verified</Tag> },
              { label: "AML review", value: p.aml_flag ? <Tag tone="danger">Flagged</Tag> : <Tag tone="success">Clear</Tag> },
            ]}
          />
          {!p.kyc_verified ? (
            <p className="mt-3 text-[0.9375rem] text-danger">Orders are refused until KYC is verified.</p>
          ) : null}
        </Panel>

        <Panel title="Record">
          <Ledger
            rows={[
              { label: "Client reference", value: <span className="text-[0.9375rem]">{p.client_id}</span> },
              { label: "Created", value: dateTime(p.created_at) },
              { label: "Last updated", value: dateTime(p.updated_at) },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <>
      <PageHeader title="Risk profile" lede="What the profiler recorded about you, and the scores it derived." />
      <RequireProfile>{(id) => <Profile clientId={id} />}</RequireProfile>
    </>
  );
}
