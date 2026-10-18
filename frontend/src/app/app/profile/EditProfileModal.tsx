"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { ErrorNotice } from "@/components/ui/Feedback";
import { Input, Select } from "@/components/ui/Field";
import { api } from "@/lib/api";
import { fixed } from "@/lib/format";
import type { ClientProfile } from "@/lib/types";

interface EditProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ClientProfile;
  onSaved: () => void;
}

const GOAL_OPTIONS = [
  { id: "wealth_accumulation", label: "Wealth Accumulation" },
  { id: "retirement", label: "Retirement Planning" },
  { id: "house_downpayment", label: "Real Estate / Home" },
  { id: "education", label: "Education Funding" },
  { id: "emergency_buffer", label: "Emergency Buffer" },
  { id: "tax_optimization", label: "Tax Optimization" },
];

export function EditProfileModal({ isOpen, onClose, profile, onSaved }: EditProfileModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Demographics
  const [age, setAge] = useState<number>(profile.age ?? 30);
  const [employmentStatus, setEmploymentStatus] = useState(profile.employment_status ?? "employed");
  const [dependents, setDependents] = useState<number>(profile.dependents ?? 0);
  const [sourceOfFunds, setSourceOfFunds] = useState(profile.source_of_funds ?? "salary");

  // Finances
  const [annualIncome, setAnnualIncome] = useState<number>(profile.annual_income ?? 100000);
  const [liquidAssets, setLiquidAssets] = useState<number>(profile.liquid_assets ?? 50000);
  const [monthlyExpenses, setMonthlyExpenses] = useState<number>(profile.monthly_expenses ?? 3500);
  const [existingDebts, setExistingDebts] = useState<number>(profile.existing_debts ?? 0);

  // Objectives
  const [primaryGoal, setPrimaryGoal] = useState(profile.primary_goal ?? "growth");
  const [horizonYears, setHorizonYears] = useState<number>(profile.investment_horizon_years ?? 10);
  const [targetReturn, setTargetReturn] = useState<number>(profile.target_return ?? 7.5);
  const [liquidityNeeds, setLiquidityNeeds] = useState(profile.liquidity_needs ?? "medium");
  const [lossCapacity, setLossCapacity] = useState(profile.loss_capacity ?? "medium");
  const [specificGoals, setSpecificGoals] = useState<string[]>(profile.specific_goals ?? ["wealth_accumulation"]);

  // Risk & Psychology
  const [riskToleranceScore, setRiskToleranceScore] = useState<number>(profile.risk_tolerance_score ?? 6.0);
  const [investmentExperience, setInvestmentExperience] = useState(profile.investment_experience ?? "intermediate");
  const [drawdownReaction, setDrawdownReaction] = useState(profile.drawdown_reaction ?? "hold");
  const [monitoringFrequency, setMonitoringFrequency] = useState(profile.monitoring_frequency ?? "monthly");

  // KYC
  const [pepStatus, setPepStatus] = useState<boolean>(profile.pep_status ?? false);
  const [highRiskJurisdiction, setHighRiskJurisdiction] = useState<boolean>(profile.high_risk_jurisdiction ?? false);

  if (!isOpen) return null;

  function toggleGoal(id: string) {
    setSpecificGoals((prev) => (prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await api.updateProfile({
        client_id: profile.client_id,
        age: Number(age),
        employment_status: employmentStatus,
        dependents: Number(dependents),
        source_of_funds: sourceOfFunds,
        annual_income: Number(annualIncome),
        liquid_assets: Number(liquidAssets),
        monthly_expenses: Number(monthlyExpenses),
        existing_debts: Number(existingDebts),
        primary_goal: primaryGoal,
        investment_horizon_years: Number(horizonYears),
        target_return: Number(targetReturn),
        liquidity_needs: liquidityNeeds,
        loss_capacity: lossCapacity,
        specific_goals: specificGoals,
        risk_tolerance_score: Number(riskToleranceScore),
        investment_experience: investmentExperience,
        drawdown_reaction: drawdownReaction,
        monitoring_frequency: monitoringFrequency,
        pep_status: pepStatus,
        high_risk_jurisdiction: highRiskJurisdiction,
      });

      onSaved();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-ink/70 p-4 backdrop-blur-md">
      <div className="relative my-8 w-full max-w-3xl rounded-2xl border border-line bg-background shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-ink">Edit Investor Profile</h2>
            <p className="text-xs text-muted">
              Modify your financial parameters, risk traits, and KYC declarations. Suitability tiers and risk calibrations will update immediately.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink transition-colors"
            aria-label="Close"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="max-h-[calc(85vh-120px)] overflow-y-auto p-6 space-y-6">
          {error && <ErrorNotice error={error} />}

          {/* Section 1: Demographics & Career */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">1. Demographics & Funds Source</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Age</label>
                <Input
                  type="number"
                  min={18}
                  max={100}
                  value={age === 0 ? "" : age}
                  placeholder="30"
                  onChange={(e) => setAge(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Employment</label>
                <Select value={employmentStatus} onChange={(e) => setEmploymentStatus(e.target.value)}>
                  <option value="employed">Employed</option>
                  <option value="self_employed">Self Employed</option>
                  <option value="business_owner">Business Owner</option>
                  <option value="retired">Retired</option>
                  <option value="student">Student</option>
                  <option value="unemployed">Unemployed</option>
                  <option value="other">Other</option>
                </Select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Dependents</label>
                <Input
                  type="number"
                  min={0}
                  max={20}
                  value={dependents === 0 ? "" : dependents}
                  placeholder="0"
                  onChange={(e) => setDependents(e.target.value === "" ? 0 : Number(e.target.value))}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Source of Funds</label>
                <Select value={sourceOfFunds} onChange={(e) => setSourceOfFunds(e.target.value)}>
                  <option value="salary">Salary / Earnings</option>
                  <option value="business">Business Operations</option>
                  <option value="investments">Investments / Capital Gains</option>
                  <option value="inheritance">Inheritance / Windfall</option>
                  <option value="savings">Accumulated Savings</option>
                  <option value="pension">Pension / Retirement</option>
                  <option value="other">Other</option>
                </Select>
              </div>
            </div>
          </div>

          {/* Section 2: Financial Baseline */}
          <div className="border-t border-line pt-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">2. Financial Baseline ($ USD)</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Annual Income</label>
                <Input
                  type="number"
                  min={0}
                  step={1000}
                  value={annualIncome === 0 ? "" : annualIncome}
                  placeholder="0"
                  onChange={(e) => setAnnualIncome(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Liquid Assets</label>
                <Input
                  type="number"
                  min={0}
                  step={1000}
                  value={liquidAssets === 0 ? "" : liquidAssets}
                  placeholder="0"
                  onChange={(e) => setLiquidAssets(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Monthly Expenses</label>
                <Input
                  type="number"
                  min={0}
                  step={100}
                  value={monthlyExpenses === 0 ? "" : monthlyExpenses}
                  placeholder="0"
                  onChange={(e) => setMonthlyExpenses(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Existing Debts</label>
                <Input
                  type="number"
                  min={0}
                  step={500}
                  value={existingDebts === 0 ? "" : existingDebts}
                  placeholder="0"
                  onChange={(e) => setExistingDebts(e.target.value === "" ? 0 : Number(e.target.value))}
                />
              </div>
            </div>
          </div>

          {/* Section 3: Objectives & Horizon */}
          <div className="border-t border-line pt-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">3. Objectives & Horizon</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Primary Goal</label>
                <Select value={primaryGoal} onChange={(e) => setPrimaryGoal(e.target.value)}>
                  <option value="capital_preservation">Capital Preservation</option>
                  <option value="income">Income Generation</option>
                  <option value="balanced">Balanced Growth</option>
                  <option value="growth">Capital Growth</option>
                  <option value="aggressive_growth">Aggressive Growth</option>
                </Select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Horizon (Years)</label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={horizonYears === 0 ? "" : horizonYears}
                  placeholder="10"
                  onChange={(e) => setHorizonYears(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Target Return (% / yr)</label>
                <Input
                  type="number"
                  min={1}
                  max={40}
                  step={0.5}
                  value={targetReturn === 0 ? "" : targetReturn}
                  placeholder="7"
                  onChange={(e) => setTargetReturn(e.target.value === "" ? 0 : Number(e.target.value))}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Loss Capacity</label>
                <Select value={lossCapacity} onChange={(e) => setLossCapacity(e.target.value)}>
                  <option value="low">Low (Cannot absorb loss)</option>
                  <option value="medium">Medium (Moderate drawdowns ok)</option>
                  <option value="high">High (High drawdown tolerance)</option>
                </Select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Liquidity Needs</label>
                <Select value={liquidityNeeds} onChange={(e) => setLiquidityNeeds(e.target.value)}>
                  <option value="low">Low (Long-term lockup ok)</option>
                  <option value="medium">Medium (Moderate access)</option>
                  <option value="high">High (Immediate access needed)</option>
                </Select>
              </div>
            </div>

            <div className="mt-4">
              <label className="mb-2 block text-xs font-medium text-ink">Specific Investment Goals</label>
              <div className="flex flex-wrap gap-2">
                {GOAL_OPTIONS.map((g) => {
                  const active = specificGoals.includes(g.id);
                  return (
                    <button
                      key={g.id}
                      type="button"
                      onClick={() => toggleGoal(g.id)}
                      className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                        active
                          ? "border-primary bg-primary text-on-primary font-medium shadow-xs"
                          : "border-line bg-surface/60 text-muted hover:bg-surface hover:text-ink"
                      }`}
                    >
                      {active ? `✓ ${g.label}` : `+ ${g.label}`}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Section 4: Risk Psychology & Behavior */}
          <div className="border-t border-line pt-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">4. Risk Tolerance & Behavioral Profile</h3>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between items-center mb-1.5">
                  <label className="text-xs font-medium text-ink">Stated Risk Tolerance Score (1 to 10)</label>
                  <span className="figures text-xs font-semibold text-accent">{fixed(riskToleranceScore, 1)} / 10.0</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={0.1}
                  value={riskToleranceScore}
                  onChange={(e) => setRiskToleranceScore(Number(e.target.value))}
                  className="w-full accent-primary cursor-pointer"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Experience Level</label>
                  <Select value={investmentExperience} onChange={(e) => setInvestmentExperience(e.target.value)}>
                    <option value="none">None (First time investor)</option>
                    <option value="novice">Novice (1-2 years)</option>
                    <option value="intermediate">Intermediate (3-5 years)</option>
                    <option value="advanced">Advanced (5-10 years)</option>
                    <option value="expert">Expert (10+ years / Professional)</option>
                  </Select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Reaction to 20% Drawdown</label>
                  <Select value={drawdownReaction} onChange={(e) => setDrawdownReaction(e.target.value)}>
                    <option value="buy_more">Buy more (opportunistic)</option>
                    <option value="hold">Hold steady (long-term plan)</option>
                    <option value="sell_some">Sell some (reduce volatility)</option>
                    <option value="sell_all">Sell all (stop all losses)</option>
                  </Select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Monitoring Frequency</label>
                  <Select value={monitoringFrequency} onChange={(e) => setMonitoringFrequency(e.target.value)}>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                    <option value="quarterly">Quarterly</option>
                  </Select>
                </div>
              </div>
            </div>
          </div>

          {/* Section 5: Regulatory & KYC Attestations */}
          <div className="border-t border-line pt-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">5. KYC & Regulatory Disclosures</h3>
            <div className="rounded-xl border border-line bg-surface/50 p-4 space-y-3">
              <label className="flex items-start gap-2.5 cursor-pointer text-xs text-ink">
                <input
                  type="checkbox"
                  checked={pepStatus}
                  onChange={(e) => setPepStatus(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-line text-primary focus:ring-primary accent-primary"
                />
                <span>I am a Politically Exposed Person (PEP) or immediate family member / close associate of a PEP.</span>
              </label>

              <label className="flex items-start gap-2.5 cursor-pointer text-xs text-ink">
                <input
                  type="checkbox"
                  checked={highRiskJurisdiction}
                  onChange={(e) => setHighRiskJurisdiction(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-line text-primary focus:ring-primary accent-primary"
                />
                <span>I reside or maintain financial ties in a FATF high-risk or heightened-monitoring jurisdiction.</span>
              </label>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-line pt-4">
            <Button type="button" variant="secondary" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" pending={loading}>
              Save & Recalibrate Profile
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
