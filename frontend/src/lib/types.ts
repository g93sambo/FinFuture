// Shapes returned by the FastAPI backend (backend/api/routes/*).

export interface User {
  id: string;
  email: string;
}

export interface SessionStart {
  session_id: string;
  message: string;
  stage: string;
  client_id: string | null;
}

export interface ClientProfile {
  client_id: string;
  user_id: string | null;
  age: number | null;
  employment_status: string | null;
  dependents: number | null;
  annual_income: number | null;
  net_worth: number | null;
  liquid_assets: number | null;
  monthly_expenses: number | null;
  existing_debts: number | null;
  investment_experience: string | null;
  risk_tolerance_score: number | null;
  investment_horizon_years: number | null;
  liquidity_needs: string | null;
  loss_capacity: string | null;
  primary_goal: string | null;
  target_return: number | null;
  specific_goals: string[] | null;
  suitability_category: string | null;
  detected_biases: string[] | null;
  emotional_risk_score: number | null;
  panic_sell_likelihood: number | null;
  kyc_verified: boolean | null;
  aml_flag: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface Position {
  symbol: string;
  qty: number;
  price: number;
  market_value: number;
  weight: number;
}

export interface Portfolio {
  client_id: string;
  source: "alpaca_paper" | "ledger" | string;
  total_value: number;
  cash: number;
  invested_value: number;
  positions: Position[];
  weights: Record<string, number>;
}

export interface Trade {
  trade_id: string;
  client_id?: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  qty: number;
  status: string;
  filled_price: number | null;
  alpaca_order_id: string | null;
  created_at: string | null;
}

export interface Proposal {
  proposal_id: string;
  client_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  notional_value: number;
  projected_weight: number;
  created_at: string;
  expires_in_seconds: number;
}

export interface Execution {
  success: boolean;
  order_id: string | null;
  trade_id: string | null;
  client_id: string;
  proposal_id: string;
  symbol: string;
  side: string;
  qty: number;
  filled_price: number | null;
  filled_qty: number | null;
  status: string;
  executed_at: string;
  dry_run: boolean;
  error: string | null;
}

export interface Violation {
  rule_id: string;
  rule_name: string;
  category: string;
  severity: "BLOCK" | "WARN" | string;
  description: string;
  actual_value?: unknown;
  threshold?: unknown;
}

export interface RuleResult {
  rule_id: string;
  rule_name: string;
  category: string;
  passed: boolean;
  severity: string;
  details: string;
}

export interface ComplianceDetails {
  passed: boolean;
  violations: Violation[];
  warnings: string[];
  rule_results: RuleResult[];
  timestamp: string;
  audit_entry_id: string | null;
}

export interface FrontierPoint {
  point_index: number;
  expected_return: number;
  volatility: number;
  annualized_return: number;
  annualized_volatility: number;
  sharpe_ratio: number;
  cvar_95: number;
  weights: Record<string, number>;
}

export interface RebalanceOrder {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  estimated_price: number;
  estimated_amount: number;
  current_weight: number;
  target_weight: number;
  weight_delta: number;
}

export interface RebalancePlan {
  total_portfolio_value: number;
  cash_before: number;
  estimated_cash_after: number;
  max_drift: number;
  portfolio_turnover: number;
  is_rebalance_needed: boolean;
  orders: RebalanceOrder[];
}

/** Every event the orchestrator emits (REST chat, WebSocket, allocation, trade). */
export interface AgentEvent {
  event:
    | "user_message"
    | "agent_response"
    | "bias_alert"
    | "compliance_check"
    | "trade_proposal"
    | "trade_approved"
    | "trade_filled"
    | "portfolio_update"
    | "error"
    | string;
  agent?: string;
  text?: string;
  timestamp?: string;
  structured_event?: string;
  // agent_response
  client_id?: string;
  profile_complete?: boolean;
  stage?: string;
  session_id?: string;
  // bias_alert
  bias_type?: string;
  severity?: string;
  confidence?: number;
  cool_off_recommended?: boolean;
  // compliance_check
  passed?: boolean;
  details?: ComplianceDetails;
  violations?: Violation[];
  // trade
  proposal?: Proposal;
  execution?: Execution;
  // portfolio_update
  portfolio?: Portfolio;
  report?: HealthReport;
  // allocation
  weights?: Record<string, number>;
  metrics?: Record<string, number>;
  feature_attributions?: Record<string, number>;
  frontier?: FrontierPoint[];
  rebalance_plan?: RebalancePlan | null;
  // compare
  // error
  error?: string;
}

export interface FactorBreakdown {
  expense_ratio_score: number;
  tracking_error_score: number;
  liquidity_score: number;
  aum_scale_score: number;
  historical_return_score: number;
  reputation_score: number;
  raw_metrics: Record<string, number>;
}

export interface ComparedProduct {
  symbol: string;
  name: string;
  asset_class: string;
  sub_category: string;
  risk_level: number;
  composite_score: number;
  rank: number;
  is_suitable: boolean;
  suitability_reason: string | null;
  factor_breakdown: FactorBreakdown;
  key_advantages: string[];
  key_risks: string[];
}

export interface CompareResponse {
  ranked_products: ComparedProduct[];
  unsuitable_products: ComparedProduct[];
  winner_symbol: string;
  rationale: string;
  report: { methodology: string; client_risk_tier: number; category: string };
}

export interface AssetDrift {
  symbol: string;
  asset_class: string;
  current_weight: number;
  target_weight: number;
  absolute_drift: number;
  percentage_drift: number;
  drift_direction: "OVERWEIGHT" | "UNDERWEIGHT" | "ALIGNED";
  exceeds_threshold: boolean;
}

export interface HealthAlert {
  alert_type: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  message: string;
  affected_assets: string[];
  metric_value: number;
  threshold_value: number;
  action_recommended: string;
}

export interface HealthReport {
  client_id: string;
  timestamp: string;
  portfolio_summary: { total_value: number; cash: number; holdings_count: number; asset_classes: string[] };
  health_score: number;
  health_grade: "EXCELLENT" | "GOOD" | "FAIR" | "POOR" | "CRITICAL";
  score_breakdown: {
    base_potential: number;
    diversification_reward: number;
    drift_penalty: number;
    concentration_penalty: number;
    risk_misalignment_penalty: number;
    raw_score: number;
    final_score: number;
    health_grade: string;
  };
  drift_analysis: {
    asset_drifts: Record<string, AssetDrift>;
    max_drift: number;
    total_drift: number;
    portfolio_turnover: number;
    threshold: number;
    rebalance_required: boolean;
    drifted_assets: string[];
  };
  concentration_metrics: {
    max_position_symbol: string;
    max_position_weight: number;
    herfindahl_index: number;
    effective_asset_count: number;
    top_3_concentration: number;
    has_concentration_risk: boolean;
    concentrated_assets: string[];
  };
  benchmark_comparison: {
    benchmark_name: string;
    portfolio_annualized_return: number;
    benchmark_annualized_return: number;
    excess_return: number;
    portfolio_volatility: number;
    benchmark_volatility: number;
    relative_volatility: number;
    portfolio_sharpe_ratio: number;
    benchmark_sharpe_ratio: number;
    beta_to_benchmark: number;
    asset_mix_comparison: Record<string, Record<string, number>>;
  };
  alerts: HealthAlert[];
  rebalancing_plan: {
    total_portfolio_value: number;
    cash_before: number;
    estimated_cash_after: number;
    tolerance_band: number;
    is_rebalance_needed: boolean;
    portfolio_turnover: number;
    orders: (RebalanceOrder & { post_rebalance_weight: number })[];
  };
  narrative: {
    executive_summary: string;
    drift_diagnosis: string;
    risk_and_concentration_diagnosis: string;
    benchmark_comparison_narrative: string;
    actionable_recommendations: string[];
    regulatory_disclosure: string;
    generation_mode: string;
  };
}

export interface AuditEntry {
  entry_id: string;
  timestamp: string;
  event_type: string;
  actor: string;
  status: string | null;
  details: Record<string, unknown>;
  entry_hash: string;
  prev_hash: string | null;
  signature: string;
}

export interface AnchorResult {
  merkle_root: string;
  tx_hash: string;
  block_number: number | null;
  status: "confirmed" | "submitted" | "dry_run" | "failed" | string;
  chain_id: number;
  timestamp: string;
  entries_count: number;
}

export interface ComplianceRule {
  id: string;
  name: string;
  category: string;
  severity: "BLOCK" | "WARN" | string;
  description: string | null;
  parameters: Record<string, unknown>;
}

export interface Quote {
  symbol: string;
  price: number;
  bid: number | null;
  ask: number | null;
  volume: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  previous_close: number | null;
  currency: string;
  timestamp: string;
  source: string;
}

export interface MacroResponse {
  macro: Record<string, number>;
  yield_curve: Record<string, number>;
  as_of: string;
}

export interface PriceHistoryPoint {
  date: string;
  close: number;
}

export interface PriceHistoryResponse {
  symbol: string;
  period: string;
  points: PriceHistoryPoint[];
  start_price: number;
  end_price: number;
  period_return_pct: number;
}

/** Error body of a blocked trade (403 / 409 / 400 from /trade/execute). */
export interface TradeBlockedDetail {
  error: string;
  reason: string;
  violations: Violation[];
  proposal_id: string;
}
