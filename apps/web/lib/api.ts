"use client";

import { getAccessToken } from "./auth";
import { API_BASE_URL } from "./config";
import type {
  Anomaly,
  ApiErrorBody,
  AuditEntry,
  ChatResponse,
  ChatSession,
  Drivers,
  EvaluationLatest,
  Forecast,
  ForecastLatest,
  HealthResponse,
  Me,
  Measurement,
  Overview,
  Paged,
  Policy,
  Recommendation,
  RequestRow,
  Scenario,
  UsageDailyRow,
  WorkspaceSettings,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}

type Opts = { method?: string; body?: unknown; token?: string | null; auth?: boolean };

export async function apiFetch<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = opts.token !== undefined ? opts.token : opts.auth === false ? null : await getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the TokenGuard API. Is the backend running?");
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? res.statusText, body?.error?.request_id);
  }
  return (await res.json()) as T;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  health: () => apiFetch<HealthResponse>("/health", { auth: false }),
  me: () => apiFetch<Me>("/me"),
  overview: () => apiFetch<Overview>("/overview"),
  forecastLatest: () => apiFetch<ForecastLatest>("/forecasts/latest"),
  runForecast: () => apiFetch<Forecast>("/forecasts/run", { method: "POST", body: {} }),
  drivers: (id: string) => apiFetch<Drivers>(`/forecasts/${id}/drivers`),
  anomalies: (severity?: string) => apiFetch<Paged<Anomaly>>(`/anomalies${q({ severity })}`),
  acknowledge: (id: string) => apiFetch<{ id: string; acknowledged_at: string }>(`/anomalies/${id}/acknowledge`, { method: "POST" }),
  compare: (assumptions: Record<string, unknown>, forecast_run_id: string) =>
    apiFetch<{ forecast_run_id: string; scenarios: Scenario[] }>("/scenarios/compare", {
      method: "POST",
      body: { forecast_run_id, actions: ["none", "semantic_cache"], assumptions },
    }),
  recommendations: () => apiFetch<Paged<Recommendation>>("/recommendations"),
  generateRecommendation: () => apiFetch<Recommendation>("/recommendations/generate", { method: "POST" }),
  approve: (id: string, expected_version: number, enable_holdout: boolean) =>
    apiFetch<Recommendation>(`/recommendations/${id}/approve`, { method: "POST", body: { expected_version, enable_holdout } }),
  reject: (id: string, expected_version: number) =>
    apiFetch<Recommendation>(`/recommendations/${id}/reject`, { method: "POST", body: { expected_version } }),
  policies: () => apiFetch<Paged<Policy>>("/policies"),
  disablePolicy: (id: string) => apiFetch<Policy>(`/policies/${id}/disable`, { method: "POST" }),
  patchPolicy: (id: string, body: Partial<Pick<Policy, "similarity_threshold" | "ttl_hours" | "holdout_enabled">>) =>
    apiFetch<Policy>(`/policies/${id}`, { method: "PATCH", body }),
  audit: () => apiFetch<Paged<AuditEntry>>("/audit"),
  measurement: () => apiFetch<Measurement>("/measurement"),
  evaluation: () => apiFetch<EvaluationLatest>("/evaluation/latest"),
  usageDaily: (params: { from?: string; to?: string; data_origin?: string }) =>
    apiFetch<Paged<UsageDailyRow>>(`/usage/daily${q(params)}`),
  usageRequests: (cursor?: string | null, filters: {
    from?: string; to?: string; application?: string; model?: string; request_category?: string; data_origin?: string;
  } = {}) => apiFetch<Paged<RequestRow>>(`/usage/requests${q({ ...filters, cursor, limit: 50 })}`),
  settings: () => apiFetch<WorkspaceSettings>("/settings/workspace"),
  patchSettings: (body: { monthly_budget_myr?: number }) =>
    apiFetch<WorkspaceSettings>("/settings/workspace", { method: "PATCH", body }),
  rotateKey: (appId: string) =>
    apiFetch<{ application_id: string; api_key: string; note: string }>(`/applications/${appId}/rotate-key`, { method: "POST" }),
  invalidateFaq: () => apiFetch<{ knowledge_version: number }>("/faq/invalidate", { method: "POST" }),
  demoReset: () => apiFetch<{ status: string }>("/demo/reset", { method: "POST" }),
  chatSession: () => apiFetch<ChatSession>("/chat/session", { method: "POST", auth: false }),
  chat: (token: string, application_id: string, message: string) =>
    apiFetch<ChatResponse>("/chat", { method: "POST", token, body: { application_id, message, locale: "en" } }),
};
