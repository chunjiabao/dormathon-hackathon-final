"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// One place for query keys so mutations can invalidate precisely.
export const qk = {
  health: ["health"] as const,
  me: ["me"] as const,
  overview: ["overview"] as const,
  forecast: ["forecast"] as const,
  drivers: (id: string) => ["drivers", id] as const,
  anomalies: (severity?: string) => ["anomalies", severity ?? "all"] as const,
  recommendations: ["recommendations"] as const,
  policies: ["policies"] as const,
  audit: ["audit"] as const,
  measurement: ["measurement"] as const,
  evaluation: ["evaluation"] as const,
  usageDaily: (p: object) => ["usageDaily", p] as const,
  settings: ["settings"] as const,
};

export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: api.health, staleTime: 30_000 });
export const useMe = () => useQuery({ queryKey: qk.me, queryFn: api.me, staleTime: 60_000 });
export const useOverview = () => useQuery({ queryKey: qk.overview, queryFn: api.overview });
export const useForecast = () => useQuery({ queryKey: qk.forecast, queryFn: api.forecastLatest });
export const useDrivers = (id?: string) =>
  useQuery({ queryKey: qk.drivers(id ?? ""), queryFn: () => api.drivers(id!), enabled: Boolean(id) });
export const useAnomalies = (severity?: string) =>
  useQuery({ queryKey: qk.anomalies(severity), queryFn: () => api.anomalies(severity) });
export const useRecommendations = () => useQuery({ queryKey: qk.recommendations, queryFn: api.recommendations });
export const usePolicies = () => useQuery({ queryKey: qk.policies, queryFn: api.policies });
export const useAudit = () => useQuery({ queryKey: qk.audit, queryFn: api.audit });
export const useMeasurement = () => useQuery({ queryKey: qk.measurement, queryFn: api.measurement });
export const useEvaluation = () => useQuery({ queryKey: qk.evaluation, queryFn: api.evaluation, staleTime: 300_000 });
export const useSettings = () => useQuery({ queryKey: qk.settings, queryFn: api.settings });
export const useUsageDaily = (p: { from?: string; to?: string; data_origin?: string }) =>
  useQuery({ queryKey: qk.usageDaily(p), queryFn: () => api.usageDaily(p) });

/** Role of the signed-in user in the (single, P0) workspace. */
export function useRole(): { role: "owner" | "viewer" | null; isOwner: boolean; loading: boolean } {
  const me = useMe();
  const role = me.data?.memberships[0]?.role ?? null;
  return { role, isOwner: role === "owner", loading: me.isLoading };
}
