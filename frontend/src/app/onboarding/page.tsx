"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Wordmark } from "@/components/shell/Wordmark";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fixed, money } from "@/lib/format";
import type { OnboardingData } from "@/lib/types";
import {
  SUPPORTED_BROKERAGES,
  BENCHMARK_INDICES,
  getStoredBroker,
  setStoredBroker,
  getStoredBenchmark,
  setStoredBenchmark,
} from "@/lib/custodians";

const employmentOptions = [
  { value: "employed", label: "Employed", desc: "Full-time or part-time salary" },
  { value: "self-employed", label: "Self-Employed", desc: "Business owner, contractor, or founder" },
  { value: "retired", label: "Retired", desc: "Living off pensions or investments" },
  { value: "student", label: "Student", desc: "Currently in education" },
  { value: "unemployed", label: "Not Employed", desc: "Seeking employment or in transition" },
];

const sourceOptions = [
  { value: "salary", label: "Employment Salary" },
  { value: "business", label: "Business Profits" },
  { value: "investments", label: "Investment Returns" },
  { value: "savings", label: "Personal Savings" },
  { value: "inheritance", label: "Family / Inheritance" },
];

const goalOptions = [
  {
    value: "capital_preservation",
    label: "Capital Preservation",
    desc: "Minimize downside risk and protect principal against inflation. Minimal equity exposure.",
  },
  {
    value: "income",
    label: "Steady Income",
    desc: "Generate consistent dividend and bond yield with low volatility.",
  },
  {
    value: "balanced",
    label: "Balanced Growth",
    desc: "Moderate capital appreciation with a defensive cushion against downturns.",
  },
  {
    value: "growth",
    label: "Long-term Growth",
    desc: "Maximize capital appreciation over 5–10+ year equity market cycles.",
  },
  {
    value: "aggressive_growth",
    label: "Aggressive Growth",
    desc: "Pursue maximum long-term return and tolerate substantial drawdowns.",
  },
];

const drawdownOptions = [
  {
    value: "buy_more",
    emoji: "📈",
    label: "Buy more at a discount",
    desc: "View market pullbacks as attractive buying opportunities.",
  },
  {
    value: "hold",
    emoji: "🛡️",
    label: "Hold firm and stick to the plan",
    desc: "Stay disciplined; trust the long-term asset allocation.",
  },
  {
    value: "anxious",
    emoji: "⏳",
    label: "Feel anxious, but wait it out",
    desc: "Dislike short-term volatility, but avoid hasty panic selling.",
  },
  {
    value: "sell_some",
    emoji: "⚠️",
    label: "Sell some to cut losses",
    desc: "Reduce risk exposure to cap further emotional distress.",
  },
  {
    value: "sell_all",
    emoji: "🛑",
    label: "Sell everything to cash",
    desc: "Move immediately to safety to preserve remaining capital.",
  },
];

const experienceOptions = [
  { value: "none", label: "None", desc: "Brand new to investing" },
  { value: "novice", label: "Novice", desc: "Basic savings & occasional mutual funds" },
  { value: "intermediate", label: "Intermediate", desc: "Familiar with stocks, ETFs, and bonds" },
  { value: "advanced", label: "Advanced", desc: "Active portfolio manager, factor awareness" },
  { value: "expert", label: "Expert", desc: "Institutional or professional background" },
];

const lossCapacityOptions = [
  { value: "low", label: "Low", desc: "Cannot tolerate any capital loss" },
  { value: "medium", label: "Medium", desc: "Can absorb modest temporary drawdowns" },
  { value: "high", label: "High", desc: "Can withstand significant portfolio volatility" },
];

const liquidityOptions = [
  { value: "low", label: "Low", desc: "Funds locked for 5+ years" },
  { value: "medium", label: "Medium", desc: "May need partial access in 1–3 years" },
  { value: "high", label: "High", desc: "May need withdrawals within 12 months" },
];

const monitoringOptions = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annually" },
];

const specificGoalTags = [
  { id: "retirement", label: "Retirement" },
  { id: "wealth_accumulation", label: "Wealth Accumulation" },
  { id: "home_purchase", label: "Home Purchase" },
  { id: "education_fund", label: "Education" },
  { id: "tax_optimization", label: "Tax Efficiency" },
];

export default function OnboardingPage() {
  const { status, user, session, setClientId, refreshSession } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [age, setAge] = useState<number>(32);
  const [employmentStatus, setEmploymentStatus] = useState("employed");
  const [dependents, setDependents] = useState(0);
  const [sourceOfFunds, setSourceOfFunds] = useState("salary");

  const [annualIncome, setAnnualIncome] = useState<number>(120000);
  const [liquidAssets, setLiquidAssets] = useState<number>(50000);
  const [monthlyExpenses, setMonthlyExpenses] = useState<number>(4000);
  const [existingDebts, setExistingDebts] = useState<number>(10000);

  const [primaryGoal, setPrimaryGoal] = useState("growth");
  const [investmentHorizonYears, setInvestmentHorizonYears] = useState(10);
  const [targetReturn, setTargetReturn] = useState(7.5);
  const [liquidityNeeds, setLiquidityNeeds] = useState("medium");
  const [specificGoals, setSpecificGoals] = useState<string[]>(["wealth_accumulation"]);

  const [riskToleranceScore, setRiskToleranceScore] = useState(7.0);
  const [drawdownReaction, setDrawdownReaction] = useState("hold");
  const [monitoringFrequency, setMonitoringFrequency] = useState("monthly");
  const [investmentExperience, setInvestmentExperience] = useState("intermediate");
  const [lossCapacity, setLossCapacity] = useState("medium");
  const [pepStatus, setPepStatus] = useState(false);
  const [highRiskJurisdiction, setHighRiskJurisdiction] = useState(false);
  const [selectedBrokerId, setSelectedBrokerId] = useState<string>("webank");
  const [selectedBenchmarkSymbol, setSelectedBenchmarkSymbol] = useState<string>("^GSPC");

  useEffect(() => {
    setSelectedBrokerId(getStoredBroker().id);
    setSelectedBenchmarkSymbol(getStoredBenchmark().symbol);
  }, []);

  // Check auth and attempt to prefill existing profile if available
  useEffect(() => {
    if (status === "anonymous") {
      router.replace("/login");
      return;
    }
    if (status === "authenticated") {
      api
        .myProfile()
        .then((p) => {
          if (p) {
            if (p.age) setAge(p.age);
            if (p.employment_status) setEmploymentStatus(p.employment_status);
            if (p.dependents !== null) setDependents(p.dependents);
            if (p.annual_income !== null) setAnnualIncome(p.annual_income);
            if (p.liquid_assets !== null) setLiquidAssets(p.liquid_assets);
            if (p.monthly_expenses !== null) setMonthlyExpenses(p.monthly_expenses);
            if (p.existing_debts !== null) setExistingDebts(p.existing_debts);
            if (p.primary_goal) setPrimaryGoal(p.primary_goal);
            if (p.investment_horizon_years) setInvestmentHorizonYears(p.investment_horizon_years);
            if (p.target_return !== null) setTargetReturn(p.target_return);
            if (p.liquidity_needs) setLiquidityNeeds(p.liquidity_needs);
            if (p.loss_capacity) setLossCapacity(p.loss_capacity);
            if (p.risk_tolerance_score !== null) setRiskToleranceScore(p.risk_tolerance_score);
            if (p.investment_experience) setInvestmentExperience(p.investment_experience);
            if (p.specific_goals?.length) setSpecificGoals(p.specific_goals);
            if (p.source_of_funds) setSourceOfFunds(p.source_of_funds);
            if (p.drawdown_reaction) setDrawdownReaction(p.drawdown_reaction);
            if (p.monitoring_frequency) setMonitoringFrequency(p.monitoring_frequency);
            if (p.pep_status !== null && p.pep_status !== undefined) setPepStatus(p.pep_status);
            if (p.high_risk_jurisdiction !== null && p.high_risk_jurisdiction !== undefined) setHighRiskJurisdiction(p.high_risk_jurisdiction);
          }
        })
        .catch(() => {
          // No existing profile, keep sensible defaults
        });
    }
  }, [status, router]);

  // Derived metrics for live feedback
  const reserveMonths = monthlyExpenses > 0 ? liquidAssets / monthlyExpenses : 0;
  const dtiRatio = annualIncome > 0 ? (existingDebts / annualIncome) * 100 : 0;

  // Approximate live suitability calculation matching backend logic
  const estimatedTier = (() => {
    let s_h = 2.0;
    if (investmentHorizonYears >= 20) s_h = 10.0;
    else if (investmentHorizonYears >= 10) s_h = 8.5;
    else if (investmentHorizonYears >= 5) s_h = 6.5;
    else if (investmentHorizonYears >= 2) s_h = 4.0;

    let s_lc = lossCapacity === "high" ? 9.0 : lossCapacity === "low" ? 2.5 : 6.0;
    if (reserveMonths < 3.0 && monthlyExpenses > 0) s_lc = Math.min(s_lc, 3.0);

    let s_g = 6.0;
    if (primaryGoal === "capital_preservation") s_g = 2.0;
    else if (primaryGoal === "income") s_g = 4.0;
    else if (primaryGoal === "balanced") s_g = 5.5;
    else if (primaryGoal === "growth") s_g = 8.0;
    else if (primaryGoal === "aggressive_growth") s_g = 10.0;

    const expMap: Record<string, number> = { none: 2.0, novice: 4.0, intermediate: 6.5, advanced: 8.5, expert: 10.0 };
    const s_exp = expMap[investmentExperience] ?? 6.0;

    let score = 0.35 * riskToleranceScore + 0.25 * s_lc + 0.2 * s_h + 0.1 * s_g + 0.1 * s_exp;
    if (investmentHorizonYears < 3) score = Math.min(score, 4.0);
    if (lossCapacity === "low" || reserveMonths < 3.0) score = Math.min(score, 5.0);
    if (investmentExperience === "none" && riskToleranceScore > 7.0) score = Math.min(score, 6.5);

    if (score < 3.0) return "Conservative";
    if (score < 5.0) return "Moderate Conservative";
    if (score < 7.0) return "Moderate";
    if (score < 8.5) return "Growth";
    return "Aggressive Growth";
  })();

  function toggleSpecificGoal(id: string) {
    setSpecificGoals((prev) => (prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]));
  }

  function validateStep(): boolean {
    setError(null);
    if (step === 1) {
      if (!age || age < 18) {
        setError("Under regulatory requirements, advisory clients must be at least 18 years old.");
        return false;
      }
    } else if (step === 2) {
      if (annualIncome < 0 || liquidAssets < 0 || monthlyExpenses < 0 || existingDebts < 0) {
        setError("Financial values cannot be negative numbers.");
        return false;
      }
    }
    return true;
  }

  function next() {
    if (validateStep()) setStep((s) => Math.min(5, s + 1));
  }

  function back() {
    setError(null);
    setStep((s) => Math.max(1, s - 1));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validateStep()) return;
    setLoading(true);
    setError(null);

    const payload: OnboardingData = {
      age: Number(age),
      employment_status: employmentStatus,
      dependents: Number(dependents),
      annual_income: Number(annualIncome),
      liquid_assets: Number(liquidAssets),
      monthly_expenses: Number(monthlyExpenses),
      existing_debts: Number(existingDebts),
      investment_experience: investmentExperience,
      risk_tolerance_score: Number(riskToleranceScore),
      investment_horizon_years: Number(investmentHorizonYears),
      liquidity_needs: liquidityNeeds,
      loss_capacity: lossCapacity,
      primary_goal: primaryGoal,
      target_return: Number(targetReturn),
      specific_goals: specificGoals,
      drawdown_reaction: drawdownReaction,
      monitoring_frequency: monitoringFrequency,
      source_of_funds: sourceOfFunds,
      pep_status: pepStatus,
      high_risk_jurisdiction: highRiskJurisdiction,
      session_id: session?.session_id ?? null,
    };

    try {
      setStoredBroker(selectedBrokerId);
      setStoredBenchmark(selectedBenchmarkSymbol);
      const profile = await api.submitOnboarding(payload);
      setClientId(profile.client_id);
      await refreshSession();
      router.replace("/app/advisor");
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
    }
  }

  const steps = [
    { num: 1, title: "Personal Profile", lede: "Demographics & employment status" },
    { num: 2, title: "Financial Baseline", lede: "Income, liquid reserves & debts" },
    { num: 3, title: "Goals & Horizon", lede: "Target returns & timeframe" },
    { num: 4, title: "Risk & Psychology", lede: "Tolerance & drawdown reaction" },
    { num: 5, title: "Synthesis & Review", lede: "Suitability tier & compliance" },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-surface/40">
      <header className="sticky top-0 z-20 border-b border-line bg-background/95 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1280px] items-center justify-between px-5 sm:px-8">
          <Wordmark href="/app" />
          <div className="flex items-center gap-4 text-xs text-muted">
            {user?.email ? <span className="hidden sm:inline">Signed in as {user.email}</span> : null}
            <Link href="/app" className="rounded-full bg-primary px-3.5 py-1.5 font-medium text-on-primary hover:bg-primary-hover transition-colors">
              Dashboard
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1280px] flex-1 px-5 py-8 sm:px-8">
        {/* Stepper Header */}
        <div className="mb-8 rounded-card border border-line bg-background p-6 shadow-[0_2px_12px_rgba(15,41,34,0.03)]">
          <p className="text-xs font-semibold tracking-wider text-accent uppercase">Investor Onboarding</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-ink sm:text-3xl">Risk Profile & Suitability Setup</h1>
          <p className="mt-1.5 text-sm text-muted">
            Configure your investment parameters directly using interactive options and sliders. No chat required.
          </p>

          <ol className="mt-6 grid grid-cols-5 gap-2 text-xs">
            {steps.map((st) => {
              const active = step === st.num;
              const completed = step > st.num;
              return (
                <li
                  key={st.num}
                  className={`border-t-2 pt-2.5 transition-colors ${
                    active ? "border-accent font-semibold text-primary" : completed ? "border-accent/50 text-ink" : "border-line text-muted"
                  }`}
                >
                  <span className="figures mr-1 text-accent">0{st.num}.</span>
                  <span className="hidden sm:inline">{st.title}</span>
                </li>
              );
            })}
          </ol>
        </div>

        {error ? (
          <div className="mb-6">
            <Notice tone="danger">{error}</Notice>
          </div>
        ) : null}

        <div className="grid gap-8 lg:grid-cols-12">
          {/* Main Form Body */}
          <div className="lg:col-span-8">
            <form
              onSubmit={handleSubmit}
              noValidate
              className="rounded-card border border-line bg-background p-6 shadow-[0_4px_20px_rgba(15,41,34,0.03)] sm:p-8"
            >
              {/* STEP 1: PERSONAL & DEMOGRAPHICS */}
              {step === 1 && (
                <div className="space-y-6">
                  <div className="border-b border-line pb-4">
                    <h2 className="text-lg font-semibold text-ink">1. About You</h2>
                    <p className="text-sm text-muted">Regulatory identity parameters used for KYC compliance.</p>
                  </div>

                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label="Your Age" hint="Clients must be 18 or older.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          min={18}
                          max={110}
                          value={age}
                          onChange={(e) => setAge(parseInt(e.target.value) || 0)}
                          required
                        />
                      )}
                    </Field>

                    <Field label="Number of Dependents" hint="Children or dependents relying on your income.">
                      {() => (
                        <div className="flex gap-2 pt-0.5">
                          {[0, 1, 2, 3, 4].map((d) => (
                            <button
                              key={d}
                              type="button"
                              onClick={() => setDependents(d)}
                              className={`h-10 flex-1 rounded-control border text-sm font-medium transition-colors ${
                                dependents === d
                                  ? "border-primary bg-primary text-on-primary shadow-xs"
                                  : "border-line bg-surface/60 text-ink hover:bg-surface"
                              }`}
                            >
                              {d === 4 ? "4+" : d}
                            </button>
                          ))}
                        </div>
                      )}
                    </Field>
                  </div>

                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">Current Employment Status</label>
                    <div className="grid gap-2.5 sm:grid-cols-2">
                      {employmentOptions.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setEmploymentStatus(opt.value)}
                          className={`flex flex-col items-start rounded-xl border p-3.5 text-left transition-all ${
                            employmentStatus === opt.value
                              ? "border-accent bg-accent-soft/60 ring-1 ring-accent"
                              : "border-line bg-surface/40 hover:bg-surface"
                          }`}
                        >
                          <span className="text-sm font-semibold text-ink">{opt.label}</span>
                          <span className="mt-0.5 text-xs text-muted">{opt.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">Primary Source of Investment Funds</label>
                    <div className="flex flex-wrap gap-2">
                      {sourceOptions.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setSourceOfFunds(opt.value)}
                          className={`rounded-full border px-4 py-2 text-xs font-medium transition-colors ${
                            sourceOfFunds === opt.value
                              ? "border-primary bg-primary text-on-primary shadow-xs"
                              : "border-line bg-surface/60 text-ink hover:bg-surface"
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 2: FINANCIAL BASELINE */}
              {step === 2 && (
                <div className="space-y-6">
                  <div className="border-b border-line pb-4">
                    <h2 className="text-lg font-semibold text-ink">2. Financial Situation</h2>
                    <p className="text-sm text-muted">
                      Your liquidity and reserve health determine your capacity for loss and regulatory guardrails.
                    </p>
                  </div>

                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label="Annual Gross Income ($)" hint="Salary, business draws, or pension.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          step={1000}
                          min={0}
                          value={annualIncome}
                          onChange={(e) => setAnnualIncome(Math.max(0, parseFloat(e.target.value) || 0))}
                          required
                        />
                      )}
                    </Field>

                    <Field label="Liquid Cash & Savings ($)" hint="Checking, savings, or money market reserves.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          step={1000}
                          min={0}
                          value={liquidAssets}
                          onChange={(e) => setLiquidAssets(Math.max(0, parseFloat(e.target.value) || 0))}
                          required
                        />
                      )}
                    </Field>

                    <Field label="Estimated Monthly Living Costs ($)" hint="Housing, groceries, bills, and lifestyle.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          step={100}
                          min={0}
                          value={monthlyExpenses}
                          onChange={(e) => setMonthlyExpenses(Math.max(0, parseFloat(e.target.value) || 0))}
                          required
                        />
                      )}
                    </Field>

                    <Field label="Existing Debts & Liabilities ($)" hint="Credit card balances, auto loans, personal debt.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          step={500}
                          min={0}
                          value={existingDebts}
                          onChange={(e) => setExistingDebts(Math.max(0, parseFloat(e.target.value) || 0))}
                          required
                        />
                      )}
                    </Field>
                  </div>

                  {/* Financial health telemetry card */}
                  <div className="rounded-xl border border-line bg-surface/70 p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Financial Health Check</h3>
                    <div className="mt-3 grid gap-4 sm:grid-cols-2">
                      <div className="rounded-lg border border-line bg-background p-3.5">
                        <span className="text-xs text-muted">Emergency Reserve Runway</span>
                        <p className="figures text-xl font-bold text-ink">{fixed(reserveMonths, 1)} months</p>
                        <p className={`mt-1 text-[11.5px] ${reserveMonths < 3.0 ? "text-danger font-medium" : "text-success"}`}>
                          {reserveMonths < 3.0
                            ? "⚠️ Below 3 months: Reg BI caps risk to protect your short-term cash flow."
                            : "✓ Healthy buffer: Exceeds 3-month liquidity safety guideline."}
                        </p>
                      </div>

                      <div className="rounded-lg border border-line bg-background p-3.5">
                        <span className="text-xs text-muted">Debt-to-Income (DTI)</span>
                        <p className="figures text-xl font-bold text-ink">{fixed(dtiRatio, 1)}%</p>
                        <p className="mt-1 text-[11.5px] text-muted">
                          {dtiRatio > 40 ? "Elevated debt obligations considered in loss capacity." : "Moderate/healthy leverage profile."}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 3: GOALS & HORIZON */}
              {step === 3 && (
                <div className="space-y-6">
                  <div className="border-b border-line pb-4">
                    <h2 className="text-lg font-semibold text-ink">3. Goals & Horizon</h2>
                    <p className="text-sm text-muted">What are you investing for, and how long can this capital compound?</p>
                  </div>

                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">Primary Investment Objective</label>
                    <div className="space-y-2.5">
                      {goalOptions.map((g) => (
                        <button
                          key={g.value}
                          type="button"
                          onClick={() => setPrimaryGoal(g.value)}
                          className={`flex w-full items-start justify-between rounded-xl border p-3.5 text-left transition-all ${
                            primaryGoal === g.value
                              ? "border-accent bg-accent-soft/60 ring-1 ring-accent"
                              : "border-line bg-surface/40 hover:bg-surface"
                          }`}
                        >
                          <div>
                            <span className="text-sm font-semibold text-ink">{g.label}</span>
                            <p className="mt-0.5 text-xs text-muted">{g.desc}</p>
                          </div>
                          <span
                            className={`figures ml-4 mt-1 h-4 w-4 shrink-0 rounded-full border ${
                              primaryGoal === g.value ? "border-accent bg-accent" : "border-line bg-background"
                            }`}
                          />
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* SLIDER: Investment Horizon */}
                  <div className="rounded-xl border border-line bg-surface/70 p-4">
                    <div className="flex items-center justify-between">
                      <label htmlFor="horizon-slider" className="text-sm font-medium text-ink">
                        Investment Horizon
                      </label>
                      <span className="figures text-base font-bold text-accent">{investmentHorizonYears} years</span>
                    </div>
                    <input
                      id="horizon-slider"
                      type="range"
                      min={1}
                      max={35}
                      step={1}
                      value={investmentHorizonYears}
                      onChange={(e) => setInvestmentHorizonYears(parseInt(e.target.value))}
                      className="mt-3 w-full accent-accent"
                    />
                    <div className="mt-2 flex justify-between text-[11px] text-muted">
                      <span>1 year (Short)</span>
                      <span>5 years (Medium)</span>
                      <span>15 years (Long)</span>
                      <span>30+ years (Generational)</span>
                    </div>
                  </div>

                  {/* SLIDER: Target Annual Return */}
                  <div className="rounded-xl border border-line bg-surface/70 p-4">
                    <div className="flex items-center justify-between">
                      <label htmlFor="return-slider" className="text-sm font-medium text-ink">
                        Target Annual Return
                      </label>
                      <span className="figures text-base font-bold text-accent">{fixed(targetReturn, 1)}% per year</span>
                    </div>
                    <input
                      id="return-slider"
                      type="range"
                      min={3.0}
                      max={15.0}
                      step={0.5}
                      value={targetReturn}
                      onChange={(e) => setTargetReturn(parseFloat(e.target.value))}
                      className="mt-3 w-full accent-accent"
                    />
                    <div className="mt-2 flex justify-between text-[11px] text-muted">
                      <span>3% (Inflation beat)</span>
                      <span>7% (Market avg)</span>
                      <span>11% (Growth tilt)</span>
                      <span>15% (Aggressive alpha)</span>
                    </div>
                  </div>

                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">Liquidity Needs for this Account</label>
                    <div className="grid gap-2.5 sm:grid-cols-3">
                      {liquidityOptions.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setLiquidityNeeds(opt.value)}
                          className={`rounded-xl border p-3.5 text-left transition-colors ${
                            liquidityNeeds === opt.value
                              ? "border-primary bg-primary text-on-primary shadow-xs"
                              : "border-line bg-surface/50 text-ink hover:bg-surface"
                          }`}
                        >
                          <span className="block text-sm font-semibold">{opt.label}</span>
                          <span className={`mt-0.5 block text-xs ${liquidityNeeds === opt.value ? "text-on-primary/80" : "text-muted"}`}>
                            {opt.desc}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">Specific Financial Goals (Select all that apply)</label>
                    <div className="flex flex-wrap gap-2">
                      {specificGoalTags.map((g) => {
                        const sel = specificGoals.includes(g.id);
                        return (
                          <button
                            key={g.id}
                            type="button"
                            onClick={() => toggleSpecificGoal(g.id)}
                            className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                              sel
                                ? "border-accent bg-accent-soft text-accent font-semibold"
                                : "border-line bg-surface/60 text-muted hover:bg-surface"
                            }`}
                          >
                            {sel ? "✓ " : "+ "}
                            {g.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 4: RISK & PSYCHOLOGY */}
              {step === 4 && (
                <div className="space-y-6">
                  <div className="border-b border-line pb-4">
                    <h2 className="text-lg font-semibold text-ink">4. Risk & Psychology</h2>
                    <p className="text-sm text-muted">
                      Understanding your emotional reaction to market drops prevents behavioral panic selling.
                    </p>
                  </div>

                  {/* SLIDER: Risk Tolerance Score */}
                  <div className="rounded-xl border border-line bg-surface/70 p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <label htmlFor="risk-slider" className="text-sm font-semibold text-ink">
                          Stated Risk Tolerance Score
                        </label>
                        <p className="text-xs text-muted">From 1 (maximum capital preservation) to 10 (maximum volatility tolerance).</p>
                      </div>
                      <span className="figures text-xl font-bold text-accent">{fixed(riskToleranceScore, 1)} / 10</span>
                    </div>

                    <input
                      id="risk-slider"
                      type="range"
                      min={1.0}
                      max={10.0}
                      step={0.5}
                      value={riskToleranceScore}
                      onChange={(e) => setRiskToleranceScore(parseFloat(e.target.value))}
                      className="mt-4 w-full accent-accent"
                    />

                    <div className="mt-2.5 flex items-center justify-between border-t border-line pt-2 text-xs">
                      <span className="font-semibold text-ink">
                        {riskToleranceScore <= 2.5
                          ? "Conservative: Minimum equity, prioritizes cash and treasuries."
                          : riskToleranceScore <= 4.5
                            ? "Moderate Conservative: Defensive allocation with light equity participation."
                            : riskToleranceScore <= 6.5
                              ? "Moderate: Balanced 60/40 style allocation."
                              : riskToleranceScore <= 8.5
                                ? "Growth: High equity orientation (70-85%)."
                                : "Aggressive Growth: High equity (85-100%), maximum beta."}
                      </span>
                    </div>
                  </div>

                  {/* DRAWDOWN REACTION */}
                  <div>
                    <label className="mb-2 block text-sm font-medium text-ink">
                      If your portfolio dropped 20% in a month during a market sell-off, what would you do?
                    </label>
                    <div className="space-y-2.5">
                      {drawdownOptions.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setDrawdownReaction(opt.value)}
                          className={`flex w-full items-start rounded-xl border p-3.5 text-left transition-all ${
                            drawdownReaction === opt.value
                              ? "border-accent bg-accent-soft/60 ring-1 ring-accent"
                              : "border-line bg-surface/40 hover:bg-surface"
                          }`}
                        >
                          <span className="mr-3 text-lg">{opt.emoji}</span>
                          <div>
                            <span className="text-sm font-semibold text-ink">{opt.label}</span>
                            <p className="mt-0.5 text-xs text-muted">{opt.desc}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* EXPERIENCE & LOSS CAPACITY */}
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <label className="mb-2 block text-sm font-medium text-ink">Investment Experience</label>
                      <div className="space-y-2">
                        {experienceOptions.map((exp) => (
                          <button
                            key={exp.value}
                            type="button"
                            onClick={() => setInvestmentExperience(exp.value)}
                            className={`flex w-full flex-col rounded-xl border p-3 text-left text-xs transition-colors ${
                              investmentExperience === exp.value
                                ? "border-primary bg-primary text-on-primary font-medium shadow-xs"
                                : "border-line bg-surface/50 text-ink hover:bg-surface"
                            }`}
                          >
                            <span className="font-semibold">{exp.label}</span>
                            <span className={investmentExperience === exp.value ? "text-on-primary/80" : "text-muted"}>
                              {exp.desc}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="mb-2 block text-sm font-medium text-ink">Capacity for Loss</label>
                      <div className="space-y-2">
                        {lossCapacityOptions.map((lc) => (
                          <button
                            key={lc.value}
                            type="button"
                            onClick={() => setLossCapacity(lc.value)}
                            className={`flex w-full flex-col rounded-xl border p-3 text-left text-xs transition-colors ${
                              lossCapacity === lc.value
                                ? "border-primary bg-primary text-on-primary font-medium shadow-xs"
                                : "border-line bg-surface/50 text-ink hover:bg-surface"
                            }`}
                          >
                            <span className="font-semibold">{lc.label}</span>
                            <span className={lossCapacity === lc.value ? "text-on-primary/80" : "text-muted"}>
                              {lc.desc}
                            </span>
                          </button>
                        ))}
                      </div>

                      <div className="mt-4">
                        <label className="mb-1.5 block text-xs font-medium text-ink">Portfolio Check Frequency</label>
                        <div className="flex gap-1.5">
                          {monitoringOptions.map((m) => (
                            <button
                              key={m.value}
                              type="button"
                              onClick={() => setMonitoringFrequency(m.value)}
                              className={`flex-1 rounded-lg border py-1.5 text-center text-xs font-medium transition-colors ${
                                monitoringFrequency === m.value
                                  ? "border-primary bg-primary text-on-primary shadow-xs"
                                  : "border-line bg-surface/60 text-muted hover:bg-surface"
                              }`}
                            >
                              {m.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 5: REVIEW & COMPLETE */}
              {step === 5 && (
                <div className="space-y-6">
                  <div className="border-b border-line pb-4">
                    <h2 className="text-lg font-semibold text-ink">5. Suitability Synthesis & Review</h2>
                    <p className="text-sm text-muted">
                      Review your profile parameters before saving your permanent investor suitability classification.
                    </p>
                  </div>

                  <div className="rounded-xl border border-line bg-surface/70 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
                      <div>
                        <span className="text-xs uppercase tracking-wider text-muted">Assigned Suitability Tier</span>
                        <h3 className="text-2xl font-bold text-accent">{estimatedTier}</h3>
                      </div>
                      <div className="text-right">
                        <span className="text-xs text-muted">Risk Tolerance</span>
                        <p className="figures text-lg font-semibold text-ink">{fixed(riskToleranceScore, 1)} / 10</p>
                      </div>
                    </div>

                    <div className="mt-4 grid grid-cols-2 gap-4 text-xs sm:grid-cols-4">
                      <div>
                        <span className="text-muted">Horizon</span>
                        <p className="figures font-semibold text-ink">{investmentHorizonYears} years</p>
                      </div>
                      <div>
                        <span className="text-muted">Target Return</span>
                        <p className="figures font-semibold text-ink">{fixed(targetReturn, 1)}% a year</p>
                      </div>
                      <div>
                        <span className="text-muted">Emergency Buffer</span>
                        <p className="figures font-semibold text-ink">{fixed(reserveMonths, 1)} months</p>
                      </div>
                      <div>
                        <span className="text-muted">Drawdown Reaction</span>
                        <p className="font-semibold text-ink capitalize">{drawdownReaction.replace("_", " ")}</p>
                      </div>
                    </div>
                  </div>

                  {/* Connected Stock Application & Benchmark Selection */}
                  <div className="rounded-xl border border-line bg-surface/50 p-5 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
                      <div>
                        <h3 className="text-sm font-bold text-ink">Connected Stock Application & Brokerage</h3>
                        <p className="text-xs text-muted">
                          Choose which stock application or custodian executes your paper and live orders.
                        </p>
                      </div>
                      <span className="rounded-full bg-accent/15 px-2.5 py-0.5 text-[11px] font-bold text-accent">
                        {SUPPORTED_BROKERAGES.length} Platforms Available
                      </span>
                    </div>

                    <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                      {SUPPORTED_BROKERAGES.map((b) => {
                        const isSelected = selectedBrokerId === b.id;
                        return (
                          <button
                            key={b.id}
                            type="button"
                            onClick={() => setSelectedBrokerId(b.id)}
                            className={`flex flex-col items-start rounded-xl border p-3 text-left transition-all ${
                              isSelected
                                ? "border-accent bg-background shadow-xs ring-2 ring-accent/30"
                                : "border-line bg-background/50 hover:bg-background"
                            }`}
                          >
                            <div className="flex w-full items-center justify-between">
                              <span className="text-xs font-bold text-ink truncate">{b.shortName}</span>
                              {isSelected ? (
                                <span className="h-4 w-4 rounded-full bg-accent text-[10px] font-bold text-white flex items-center justify-center">
                                  ✓
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 text-[11px] text-muted truncate w-full">{b.name}</p>
                            <div className="mt-2 flex flex-wrap gap-1">
                              {b.badges.slice(0, 1).map((bg) => (
                                <span
                                  key={bg}
                                  className="rounded bg-surface px-1.5 py-0.2 text-[9.5px] font-medium text-muted border border-line/60"
                                >
                                  {bg}
                                </span>
                              ))}
                            </div>
                          </button>
                        );
                      })}
                    </div>

                    {/* Benchmark Selection */}
                    <div className="border-t border-line/60 pt-3">
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs font-bold text-ink">Primary Performance Benchmark Index</span>
                        <span className="text-[11px] text-muted">Hurdle baseline for portfolio comparisons</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {BENCHMARK_INDICES.slice(0, 4).map((idx) => {
                          const isSelected = selectedBenchmarkSymbol === idx.symbol;
                          return (
                            <button
                              key={idx.symbol}
                              type="button"
                              onClick={() => setSelectedBenchmarkSymbol(idx.symbol)}
                              className={`rounded-lg border p-2 text-left transition-all ${
                                isSelected
                                  ? "border-accent bg-background shadow-xs ring-1 ring-accent"
                                  : "border-line bg-background/40 hover:bg-background"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className="figures text-xs font-bold text-ink">{idx.ticker}</span>
                                <span className="text-[10px] font-semibold text-accent">+{idx.returnYtd}%</span>
                              </div>
                              <p className="text-[10px] text-muted truncate">{idx.name}</p>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-line bg-surface/50 p-4 space-y-3">
                    <p className="text-xs font-semibold text-ink">KYC & Regulatory Attestations</p>
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

                  <div className="rounded-xl border border-line bg-surface/40 p-4 text-xs text-muted">
                    <p className="font-semibold text-ink">Regulatory Disclosures & Advisory Agreement</p>
                    <ul className="mt-2 list-disc space-y-1 pl-4">
                      <li>All trades are strictly non-discretionary and require your human authorization before execution.</li>
                      <li>Simulated paper-trading cash ($100,000) does not represent actual monetary transfers or obligations.</li>
                      <li>Suitability classifications adhere to FINRA Rule 2111 and SEC Regulation Best Interest (Reg BI).</li>
                    </ul>
                  </div>
                </div>
              )}

              {/* Navigation Actions */}
              <div className="mt-8 flex items-center justify-between border-t border-line pt-5">
                {step > 1 ? (
                  <Button type="button" variant="secondary" onClick={back} disabled={loading}>
                    ← Back
                  </Button>
                ) : (
                  <Link href="/app" className="text-xs text-muted hover:text-ink hover:underline">
                    Cancel & Return to Dashboard
                  </Link>
                )}

                {step < 5 ? (
                  <Button type="button" onClick={next}>
                    Continue to Step {step + 1} →
                  </Button>
                ) : (
                  <Button type="submit" pending={loading}>
                    Save & Complete Risk Profile
                  </Button>
                )}
              </div>
            </form>
          </div>

          {/* Right Column: Live Profile Summary Card */}
          <aside className="lg:col-span-4">
            <div className="sticky top-24 rounded-card border border-line bg-background p-6 shadow-[0_4px_20px_rgba(15,41,34,0.03)]">
              <h2 className="text-xs font-bold uppercase tracking-wider text-muted">Live Profile Summary</h2>

              <div className="mt-4 border-b border-line pb-4">
                <span className="text-xs text-muted">Estimated Suitability Tier</span>
                <p className="text-xl font-bold text-accent">{estimatedTier}</p>
                <p className="mt-1 text-[11.5px] text-muted">
                  Calibrated from horizon ({investmentHorizonYears}y), stated tolerance ({fixed(riskToleranceScore, 1)}), and financial capacity.
                </p>
              </div>

              <div className="mt-4 space-y-2.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted">Age & Status:</span>
                  <span className="font-medium text-ink capitalize">
                    {age} yrs, {employmentStatus}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Annual Income:</span>
                  <span className="figures font-medium text-ink">{money(annualIncome)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Liquid Savings:</span>
                  <span className="figures font-medium text-ink">{money(liquidAssets)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Monthly Expenses:</span>
                  <span className="figures font-medium text-ink">{money(monthlyExpenses)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Emergency Cushion:</span>
                  <span className={`figures font-medium ${reserveMonths < 3.0 ? "text-danger" : "text-success"}`}>
                    {fixed(reserveMonths, 1)} months
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Primary Goal:</span>
                  <span className="font-medium text-ink capitalize">{primaryGoal.replace("_", " ")}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Investment Horizon:</span>
                  <span className="figures font-medium text-ink">{investmentHorizonYears} years</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Experience Level:</span>
                  <span className="font-medium text-ink capitalize">{investmentExperience}</span>
                </div>
              </div>

              <div className="mt-5 border-t border-line pt-3 text-[11.5px] text-muted">
                Changes update in real-time as you drag sliders and select options.
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
