// Shapes of TokenGuard API responses (apps/api). Only fields the UI uses are typed precisely.

export type ApiErrorBody = { error: { code: string; message: string; request_id: string } };
export type Paged<T> = { items: T[]; next_cursor: string | null; total?: number };
export type DataOrigin = "real" | "synthetic" | "forecast" | "mock" | "assumed" | "measured";

export type HealthResponse = {
  status: "ok" | "degraded";
  environment: string;
  dependencies: {
    database: string;
    anthropic: { mode: "mock" | "live"; model: string };
    embeddings: { semantic_matching: string; model: string | null };
  };
  demo_mode: boolean;
  pricing_catalog_version: string;
};

export type Membership = { workspace_id: string; workspace_name: string; role: "owner" | "viewer" };
export type Me = { user_id: string; email: string | null; memberships: Membership[] };

export type RegressionScores = { n: number; mae: number | null; rmse: number | null; wape: number | null; smape: number | null };

export type SeriesPoint = {
  day: string;
  kind: "actual" | "forecast";
  cost_myr: number;
  lower_myr?: number;
  upper_myr?: number;
  in_month?: boolean;
  origins?: string[];
};

export type DataMix = Record<string, { days: number; rows: number; cost_myr: number; cost_share: number; first_day: string; last_day: string }>;

export type Forecast = {
  id: string;
  status: "ok" | "insufficient_data";
  generated_at: string;
  training_cutoff: string;
  horizon_end: string;
  model_name: string;
  model_version: string;
  budget_myr: number;
  observed_to_date_myr: number;
  predicted_remaining_myr: number;
  forecast_total_myr: number;
  lower_myr: number;
  upper_myr: number;
  budget_risk: "within_budget" | "possible_overrun" | "projected_overrun" | "high_confidence_overrun" | "unknown";
  evidence_type: string;
  data_mix: DataMix;
  metrics: {
    calibration_window?: [string, string];
    calibration_origins?: number;
    selection_reason?: string;
    calibration_scores?: Record<string, RegressionScores>;
    interval_quantiles?: { level: number; n_origins: number };
  };
  assumptions: Record<string, string | number | boolean | null>;
  series?: SeriesPoint[];
  budget_crossing_date?: string | null;
  next_7_days_myr?: number | null;
};

export type ForecastLatest = Forecast | { status: "no_forecast"; message: string };

export type DriverRow = {
  request_category: string;
  label: string;
  application?: string;
  predicted_remaining_myr: number;
  share: number | null;
  recent_run_rate_reference_myr: number;
  increment_vs_run_rate_myr: number;
  predicted_requests?: number;
};

export type Drivers = {
  forecast_id: string;
  status: string;
  period?: { from: string | null; to: string; days: number };
  predicted_remaining_myr?: number;
  reconciles_with_forecast?: boolean;
  reconciliation_difference_myr?: number;
  categories: DriverRow[];
  segments: DriverRow[];
  statements: string[];
  method?: string;
};

export type Anomaly = {
  id: string;
  application: string;
  day: string;
  end_day: string | null;
  metric: string;
  observed_value: number;
  expected_value: number;
  estimated_impact_myr: number | null;
  severity: "low" | "medium" | "high";
  anomaly_score: number;
  reason_code: string;
  explanation: string;
  is_synthetic: boolean;
  acknowledged_at: string | null;
  synthetic_ground_truth: { event_id: string | null; kind?: string; mechanism: string; event_class?: string; alert_expected?: string } | null;
  limitations: string;
};

export type QualityCheck = { id: string; passed: boolean; required: boolean; detail: string };

export type ScenarioAssumptions = {
  eligible_share: number;
  safe_hit_rate: number;
  overhead_per_lookup_myr: number;
  fixed_daily_myr: number;
  target_apps: string[];
  sources: Record<string, string>;
  samples: Record<string, number>;
};

export type Scenario = {
  scenario_type: "none" | "semantic_cache";
  scenario_id: string;
  forecast_run_id: string;
  method: string;
  baseline_forecast: { total_myr: number; observed_to_date_myr: number; predicted_remaining_myr: number; lower_myr: number; upper_myr: number };
  scenario_forecast: { total_myr: number; lower_myr: number; upper_myr: number };
  gross_savings_myr: number;
  overhead_myr: number;
  net_savings_myr: number;
  savings_sensitivity_myr: { low: number; base: number; high: number; forecast_interval: { low: number; high: number } };
  budget_myr: number;
  within_budget_after: boolean;
  assumptions: ScenarioAssumptions;
  default_assumptions: ScenarioAssumptions;
  quality_gate: { status: "pass" | "fail"; checks: QualityCheck[] };
  evidence_type: string;
  details: {
    faq_forecast_cost_myr?: number;
    predicted_faq_requests?: number;
    predicted_hits?: number;
    days?: number;
    per_application?: { application: string; faq_forecast_cost_myr: number; predicted_hits: number; gross_savings_myr: number }[];
  };
};

export type Recommendation = {
  id: string;
  action_type: "enable_semantic_cache" | "no_action";
  status: "proposed" | "approved" | "rejected" | "enabled" | "disabled";
  version: number;
  rationale: string;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  forecast_run_id: string;
  superseded: boolean;
  scenario: Scenario | null;
};

export type Policy = {
  id: string;
  application: string;
  policy_type: string;
  enabled: boolean;
  similarity_threshold: number;
  ttl_hours: number;
  faq_only: boolean;
  holdout_enabled: boolean;
  version: number;
  approved_at: string | null;
  approved_by: string | null;
  updated_at: string;
};

export type AuditEntry = {
  id: string;
  created_at: string;
  action: string;
  application: string | null;
  actor_user_id: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
};

export type MeasurementApp = {
  application: string;
  status: string;
  policy_enabled: boolean;
  since?: string;
  days_observed?: number;
  requests?: number;
  provider_calls?: number;
  exact_hits?: number;
  semantic_hits?: number;
  bypassed?: number;
  eligible_requests?: number;
  holdout_requests?: number;
  observed_provider_cost_myr?: number;
  estimated_avoided_provider_cost_myr?: number | null;
  estimated_overhead_myr?: number;
  estimated_net_savings_myr?: number | null;
  method?: string;
  provider_mode?: string;
  evidence?: string;
};

export type Measurement = {
  applications: MeasurementApp[];
  safe_hit_precision_on_test_set: number | null;
  adversarial_false_hits_on_test_set: number | null;
  note: string;
};

export type Overview = {
  workspace: { id: string; name: string; budget_myr: number; currency: string; timezone: string };
  forecast: Forecast | null;
  top_drivers: DriverRow[];
  driver_statements: string[];
  latest_anomaly: Pick<Anomaly, "id" | "day" | "application" | "reason_code" | "severity" | "explanation" | "is_synthetic"> | null;
  open_alerts: number;
  recommendation: Pick<Recommendation, "id" | "action_type" | "status" | "rationale" | "superseded"> | null;
  live_traffic_7d: { requests: number; cache_hits: number; by_status: Record<string, number>; cache_hit_rate: number | null; data_origin: "real" };
  policies: { id: string; application: string; enabled: boolean; similarity_threshold: number }[];
};

export type UsageDailyRow = {
  day: string;
  application: string;
  request_category: string;
  model: string;
  data_origin: "real" | "synthetic";
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_myr: number;
  cache_hits: number;
  retry_requests: number;
};

export type RequestRow = {
  id: string;
  occurred_at: string;
  application: string;
  provider: string;
  provider_mode: "mock" | "live";
  model: string;
  request_category: string;
  cache_status: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_myr: number;
  latency_ms: number;
  data_origin: string;
  faq_intent_key: string | null;
  similarity_score: number | null;
  error_code: string | null;
};

export type Application = { id: string; name: string; is_active: boolean; has_api_key: boolean };

export type WorkspaceSettings = {
  workspace_id: string;
  name: string;
  monthly_budget_myr: number;
  currency: string;
  timezone: string;
  knowledge_version: number;
  role: "owner" | "viewer";
  applications: Application[];
  data_sources: { real_requests: number; synthetic_days: number };
  provider_mode: "mock" | "live";
  fx_myr_per_usd_demo: number;
  pricing_catalog_version: string;
};

// Evaluation results are large nested JSON produced by apps/api/app/ml/evaluate.py.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type EvaluationResults = Record<string, any>;
export type EvaluationLatest = {
  status: "ok" | "not_run";
  evaluation: { id: string; evaluated_at: string; dataset_version: string; seed: number; method: string; data_origin: string; artifact_path: string | null; results: EvaluationResults } | null;
  workspace_dataset: Record<string, unknown> | null;
};

export type ChatResponse = {
  reply: string;
  cache_status: "miss" | "exact_hit" | "semantic_hit" | "bypass" | "error";
  usage: { input_tokens: number; output_tokens: number };
  estimated_cost_myr: number;
  request_id: string;
  provider_mode: "mock" | "live" | "none";
  request_category: string;
  cache_decision: string | null;
  faq_intent_key: string | null;
  similarity: number | null;
};

export type ChatSession = { token: string; expires_at: string; application_id: string; workspace_name: string };
