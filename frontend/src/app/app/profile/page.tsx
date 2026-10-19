"use client";

import { useState } from "react";
import Link from "next/link";
import { BulletBars } from "@/components/charts/BulletBars";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, Tag } from "@/components/ui/Feedback";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api";
import { dateTime, fixed, humanize, money, pct } from "@/lib/format";
import { useRequest } from "@/lib/useRequest";
import { EditProfileModal } from "./EditProfileModal";

const tierOrder = ["Conservative", "Moderate Conservative", "Moderate", "Growth", "Aggressive Growth"];

const SCENARIO_PROBES = [
  {
    id: "flash_crash",
    title: "Scenario 1: -14% Flash Crash in 48 Hours",
    prompt: "Global yields spike and your equity ETFs drop 14% in two trading days. What is your immediate instinct?",
    options: [
      { label: "Sell 50% to stop further losses", delta: -2.2, bias: "Loss Aversion (High Panic Sensitivity)" },
      { label: "Hold steady and wait for quarterly review", delta: 0.0, bias: "Disciplined Long-Term Alignment" },
      { label: "Rebalance from bonds into discounted equities", delta: +0.8, bias: "Counter-Cyclical Institutional Discipline" },
    ],
  },
  {
    id: "fomo_rally",
    title: "Scenario 2: +45% Tech Momentum Surge",
    prompt: "A concentrated AI semiconductor ETF is up 45% in 60 days while your diversified bond/equity mix is up 4%.",
    options: [
      { label: "Shift 30% of portfolio into the hot ETF", delta: -1.5, bias: "Recency Bias & Herd Mentality" },
      { label: "Keep core allocation; cap satellite at 5%", delta: +0.3, bias: "Core-Satellite Risk Control" },
    ],
  },
];

function Profile({ clientId }: { clientId: string }) {
  const { data: p, error, loading, reload } = useRequest(`profile:${clientId}`, () => api.profile(clientId));
  const [probeChoices, setProbeChoices] = useState<Record<string, { delta: number; bias: string; label: string }>>({});
  const [isEditing, setIsEditing] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  if (loading && !p) return <Loading label="Loading your profile" />;
  if (error) return <ErrorNotice error={error} onRetry={reload} />;
  if (!p) return null;

  const reserveMonths =
    p.monthly_expenses && p.monthly_expenses > 0 && p.liquid_assets !== null ? p.liquid_assets / p.monthly_expenses : null;
  const tierIdx = tierOrder.indexOf(p.suitability_category ?? "");

  // Compute Stated vs. Revealed Behavioral Risk Score (1-10 scale)
  const statedRisk = p.risk_tolerance_score ?? 5.0;
  const emotionalPenalty = ((p.emotional_risk_score ?? 30) / 100) * 2.2;
  const panicPenalty = (p.panic_sell_likelihood ?? 0.2) * 2.0;
  const reservePenalty = reserveMonths !== null && reserveMonths < 3 ? 1.5 : 0;
  const scenarioDelta = Object.values(probeChoices).reduce((acc, c) => acc + c.delta, 0);

  const revealedRisk = Math.max(1.0, Math.min(10.0, statedRisk - emotionalPenalty * 0.5 - panicPenalty * 0.5 - reservePenalty + scenarioDelta));
  const calibrationGap = statedRisk - revealedRisk;

  return (
    <div className="space-y-8">
      {/* Profile Actions Banner */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line bg-surface/40 p-4 sm:p-5">
        <div>
          <span className="text-xs uppercase tracking-wider text-muted font-medium">Investor Profile</span>
          <div className="flex items-center gap-2 mt-0.5">
            <h2 className="text-base font-semibold text-ink">Investor Suitability & Objectives</h2>
            <Tag tone="neutral">{p.suitability_category ?? "Unclassified"}</Tag>
          </div>
          <p className="text-xs text-muted mt-1">
            Stated tolerance: <strong className="text-ink">{fixed(p.risk_tolerance_score, 1)} / 10</strong> &bull; Horizon:{" "}
            <strong className="text-ink">{p.investment_horizon_years ?? 10} years</strong> &bull; Primary goal:{" "}
            <strong className="text-ink capitalize">{humanize(p.primary_goal)}</strong>
          </p>
        </div>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <Button onClick={() => setIsEditing(true)}>Edit Profile</Button>
          <Link
            href="/onboarding"
            className="text-xs text-muted hover:text-primary transition-colors underline-offset-4 hover:underline"
          >
            Retake questionnaire
          </Link>
        </div>
      </div>

      {savedNotice && (
        <Notice tone="success" title="Profile Updated">
          {savedNotice}
        </Notice>
      )}

      <Panel
        title="Stated vs. revealed behavioral risk calibration"
        aside={
          Math.abs(calibrationGap) > 1.2 ? (
            <Tag tone="warning">Calibration gap: {fixed(Math.abs(calibrationGap), 1)} pts</Tag>
          ) : (
            <Tag tone="success">Well-calibrated</Tag>
          )
        }
      >
        <p className="text-sm text-muted max-w-[75ch]">
          Traditional questionnaires only capture what investors <em>say</em> in calm markets. Our profiler compares your{" "}
          <strong>Stated Risk Score</strong> against your <strong>Revealed Behavioral Risk Capacity</strong> (inferred from emotional drawdown
          sensitivity, liquidity buffer, conversation biases, and digital-twin scenario decisions).
        </p>
        <div className="mt-5 grid gap-8 lg:grid-cols-12">
          <div className="lg:col-span-6 space-y-4">
            <BulletBars
              title="Stated vs. revealed risk tolerance (out of 10)"
              max={10}
              rows={[
                {
                  label: "Stated score",
                  sublabel: "Self-reported questionnaire tolerance",
                  value: statedRisk,
                  valueText: `${fixed(statedRisk, 1)} / 10`,
                },
                {
                  label: "Revealed score",
                  sublabel: "Behavior- & liquidity-adjusted true capacity",
                  value: revealedRisk,
                  target: statedRisk,
                  valueText: `${fixed(revealedRisk, 1)} / 10`,
                },
              ]}
            />
            {calibrationGap > 1.2 ? (
              <Notice tone="warning" title="Over-stated risk tolerance detected">
                Your stated score ({fixed(statedRisk, 1)}/10) is {fixed(calibrationGap, 1)} points higher than your behavioral drawdown capacity (
                {fixed(revealedRisk, 1)}/10). The Allocation Engine automatically constrains tail risk (CVaR 95%) so you are not forced into panic
                selling during a drawdown.
              </Notice>
            ) : (
              <Notice tone="success" title="Behavioral alignment confirmed">
                Your stated risk appetite ({fixed(statedRisk, 1)}/10) aligns closely with your revealed behavioral capacity (
                {fixed(revealedRisk, 1)}/10).
              </Notice>
            )}
          </div>

          <div className="lg:col-span-6 space-y-4 border-t border-line pt-4 lg:border-t-0 lg:border-l lg:pl-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Interactive Digital-Twin Behavioral Stress Probes
            </p>
            {SCENARIO_PROBES.map((sc) => {
              const picked = probeChoices[sc.id];
              return (
                <div key={sc.id} className="rounded-xl border border-line bg-surface/70 p-4 space-y-2">
                  <p className="text-xs font-semibold text-ink">{sc.title}</p>
                  <p className="text-xs text-muted">{sc.prompt}</p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {sc.options.map((opt) => {
                      const active = picked?.label === opt.label;
                      return (
                        <button
                          key={opt.label}
                          type="button"
                          onClick={() => setProbeChoices((prev) => ({ ...prev, [sc.id]: opt }))}
                          className={`rounded-lg border px-3 py-1.5 text-xs transition-all ${
                            active
                              ? "border-primary bg-primary text-on-primary font-medium shadow-xs"
                              : "border-line bg-background text-ink hover:border-primary/40"
                          }`}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                  {picked ? (
                    <p className="text-[11.5px] text-accent pt-1">
                      Signal: <strong>{picked.bias}</strong> ({picked.delta >= 0 ? `+${picked.delta}` : picked.delta} revealed risk adjustment)
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      <div className="grid gap-8 xl:grid-cols-12">
        <div className="space-y-8 xl:col-span-7">
          <Panel title="Suitability & Objectives">
            <p className="text-sm text-muted">Tier assigned from your answers. Each step up allows more equity and more volatility.</p>
            <ol className="mt-4 grid grid-cols-5 overflow-hidden rounded-xl border border-line bg-surface/50 text-center text-[12px]">
              {tierOrder.map((t, i) => (
                <li
                  key={t}
                  className={`px-1.5 py-2.5 ${i > 0 ? "border-l border-line" : ""} ${
                    i === tierIdx ? "bg-primary font-semibold text-on-primary" : "text-muted"
                  }`}
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
                { label: "Revealed behavioral score", value: `${fixed(revealedRisk, 1)} / 10` },
                { label: "Investment horizon", value: p.investment_horizon_years ? `${p.investment_horizon_years} years` : "–" },
                { label: "Primary goal", value: humanize(p.primary_goal) },
                {
                  label: "Specific goals",
                  value: p.specific_goals?.length ? p.specific_goals.map(humanize).join(", ") : "None specified",
                },
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
                { label: "Source of funds", value: humanize(p.source_of_funds || "salary") },
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
                {
                  label: "Panic sell",
                  sublabel: "Likelihood of selling after a 20% fall",
                  value: p.panic_sell_likelihood ?? 0,
                  valueText: pct(p.panic_sell_likelihood, 0),
                },
              ]}
            />
            <p className="mt-4 text-[13px] text-muted">
              Emotional risk combines your stated reaction to a fall, how often you check, detected biases and financial stress. Panic-sell
              likelihood is a logistic estimate for a 20% drawdown. Both rise when the Advisor detects a bias in conversation.
            </p>
            <div className="mt-5 border-t border-line pt-4">
              <Ledger
                rows={[
                  { label: "Drawdown reaction", value: humanize(p.drawdown_reaction || "hold") },
                  { label: "Monitoring frequency", value: humanize(p.monitoring_frequency || "monthly") },
                ]}
              />
            </div>
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

          <Panel title="Identity & Regulatory Checks">
            <Ledger
              rows={[
                { label: "KYC status", value: p.kyc_verified ? <Tag tone="success">Verified</Tag> : <Tag tone="danger">Not verified</Tag> },
                { label: "AML review", value: p.aml_flag ? <Tag tone="danger">Flagged</Tag> : <Tag tone="success">Clear</Tag> },
                {
                  label: "PEP declaration",
                  value: p.pep_status ? <Tag tone="warning">PEP Declared</Tag> : <Tag tone="neutral">Standard Client</Tag>,
                },
                {
                  label: "Jurisdiction risk",
                  value: p.high_risk_jurisdiction ? <Tag tone="warning">High-Risk Jurisdiction</Tag> : <Tag tone="neutral">Standard Risk</Tag>,
                },
              ]}
            />
            {!p.kyc_verified ? (
              <p className="mt-3 text-[13px] text-danger">
                {p.pep_status || p.high_risk_jurisdiction
                  ? "Trading is paused: a politically exposed person or high-risk jurisdiction declaration needs a manual compliance review. If it was selected by mistake, edit your profile."
                  : "Trading is paused until these checks pass. Edit your profile, choose your source of funds (salary, business, investments, savings, pension or inheritance) and save to re-run them."}
              </p>
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

      <EditProfileModal
        isOpen={isEditing}
        onClose={() => setIsEditing(false)}
        profile={p}
        onSaved={() => {
          reload();
          setSavedNotice("Profile parameters updated and risk suitability recalibrated successfully.");
          setTimeout(() => setSavedNotice(null), 6000);
        }}
      />
    </div>
  );
}

export default function ProfilePage() {
  return (
    <>
      <PageHeader
        title="Risk profile"
        lede="What the profiler recorded about you, Stated vs. Revealed behavioral calibration, and interactive scenario stress-probes."
        actions={<ButtonLink href="/onboarding" variant="secondary">Update / Retake questionnaire</ButtonLink>}
      />
      <RequireProfile>{(id) => <Profile clientId={id} />}</RequireProfile>
    </>
  );
}

