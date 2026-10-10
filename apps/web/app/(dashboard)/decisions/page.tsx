"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Power, RotateCcw, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ApprovalDialog } from "@/components/approval-dialog";
import { DataSourceBadge } from "@/components/data-source-badge";
import { CumulativeChart } from "@/components/forecast-chart";
import { OwnerButton } from "@/components/owner-button";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { RecommendationCard } from "@/components/recommendation-card";
import { QualityChecklist, ScenarioComparison } from "@/components/scenario-comparison";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, api } from "@/lib/api";
import { appLabel, formatDateTime, formatMYR, formatNum, formatPct, titleCase } from "@/lib/format";
import { qk, useAudit, useForecast, useMeasurement, usePolicies, useRecommendations } from "@/lib/queries";
import type { Forecast, ScenarioAssumptions } from "@/lib/types";

type Overrides = Partial<Pick<ScenarioAssumptions, "eligible_share" | "safe_hit_rate" | "overhead_per_lookup_myr" | "fixed_daily_myr">>;

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function AssumptionSlider({
  label, value, min, max, step, format, source, onChange, help,
}: {
  label: string; value: number; min: number; max: number; step: number; format: (v: number) => string;
  source: string; onChange: (v: number) => void; help: string;
}) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-[13px] font-medium">{label}</label>
        <span className="flex items-center gap-1.5">
          <span className="tabular text-[13px] font-semibold">{format(value)}</span>
          <DataSourceBadge origin={source} />
        </span>
      </div>
      <Slider id={id} value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} aria-label={label} />
      <p className="text-xs text-muted-foreground">{help}</p>
    </div>
  );
}

export default function DecisionLabPage() {
  const qc = useQueryClient();
  const fq = useForecast();
  const forecast = fq.data && fq.data.status === "ok" ? (fq.data as Forecast) : null;
  const recs = useRecommendations();
  const policies = usePolicies();
  const audit = useAudit();
  const measurement = useMeasurement();
  const [overrides, setOverrides] = useState<Overrides>({});
  const debounced = useDebounced(overrides);

  const compare = useQuery({
    queryKey: ["compare", forecast?.id, debounced],
    queryFn: () => api.compare(debounced, forecast!.id),
    enabled: Boolean(forecast),
    placeholderData: (previous, query) => query?.queryKey[1] === forecast?.id ? keepPreviousData(previous) : undefined,
  });
  const baseline = compare.data?.scenarios.find((s) => s.scenario_type === "none");
  const cache = compare.data?.scenarios.find((s) => s.scenario_type === "semantic_cache");
  const defaults = cache?.default_assumptions;
  const current = { ...defaults, ...overrides } as ScenarioAssumptions;
  const sourceOf = (k: keyof Overrides) => (k in overrides ? "user_adjusted" : (defaults?.sources[k] ?? "assumed"));

  const latest = recs.data?.items[0];
  const generate = useMutation({
    mutationFn: api.generateRecommendation,
    onSuccess: (r) => {
      toast.success(r.action_type === "no_action" ? "No safe intervention yet: see the rationale" : "Recommendation generated");
      qc.invalidateQueries({ queryKey: qk.recommendations });
      qc.invalidateQueries({ queryKey: qk.overview });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const reject = useMutation({
    mutationFn: () => api.reject(latest!.id, latest!.version),
    onSuccess: () => { toast.success("Recommendation rejected"); qc.invalidateQueries(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const disable = useMutation({
    mutationFn: (id: string) => api.disablePolicy(id),
    onSuccess: (p) => { toast.success(`Caching disabled for ${appLabel(p.application)}; provider calls resume.`); qc.invalidateQueries(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (fq.isLoading) return <LoadingBlock rows={4} />;
  if (fq.isError) return <ErrorState error={fq.error} onRetry={() => fq.refetch()} />;
  if (!forecast)
    return (
      <>
        <PageHeader title="Decision Lab" />
        <EmptyState title="A forecast is needed first">Run a forecast on the Predictions page; scenarios transform that exact forecast.</EmptyState>
      </>
    );

  return (
    <>
      <PageHeader
        title="Decision Lab"
        description="Simulate approved-FAQ caching on the same forecast, check the quality gate, then approve or reject. No LLM is used here."
        actions={
          <OwnerButton variant="outline" onClick={() => generate.mutate()} disabled={generate.isPending}
            reason="Only the workspace owner can generate recommendations.">
            {generate.isPending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />} Generate recommendation
          </OwnerButton>
        }
      />
      <div className="space-y-6">
        {compare.isError && <ErrorState error={compare.error} onRetry={() => compare.refetch()} />}
        {!baseline || !cache ? (
          compare.isError ? null : <LoadingBlock rows={2} />
        ) : (
          <>
            <div className={compare.isFetching ? "opacity-70 transition-opacity" : "transition-opacity"}>
              <ScenarioComparison baseline={baseline} cache={cache} />
            </div>
            <div className="grid gap-4 lg:grid-cols-5">
              <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-2">
                <CardContent className="space-y-5">
                  <SectionTitle
                    aside={
                      Object.keys(overrides).length > 0 && (
                        <button className="flex items-center gap-1 text-xs text-primary hover:underline" onClick={() => setOverrides({})}>
                          <RotateCcw className="size-3" /> Reset
                        </button>
                      )
                    }
                  >
                    Assumptions
                  </SectionTitle>
                  <AssumptionSlider label="Eligible share of FAQ requests" value={current.eligible_share} min={0} max={1} step={0.01}
                    format={(v) => formatPct(v)} source={sourceOf("eligible_share")}
                    onChange={(v) => setOverrides((o) => ({ ...o, eligible_share: v }))}
                    help="Static-FAQ requests that pass the safety gate (no personal, order-specific or time-sensitive content)." />
                  <AssumptionSlider label="Safe hit rate" value={current.safe_hit_rate} min={0} max={1} step={0.01}
                    format={(v) => formatPct(v)} source={sourceOf("safe_hit_rate")}
                    onChange={(v) => setOverrides((o) => ({ ...o, safe_hit_rate: v }))}
                    help="Eligible requests matched to an approved FAQ with high confidence (exact/alias or similarity ≥ 0.95)." />
                  <AssumptionSlider label="Overhead per lookup" value={current.overhead_per_lookup_myr} min={0} max={0.001} step={0.00001}
                    format={(v) => `RM${v.toFixed(5)}`} source={sourceOf("overhead_per_lookup_myr")}
                    onChange={(v) => setOverrides((o) => ({ ...o, overhead_per_lookup_myr: v }))}
                    help="Local embedding + database cost per FAQ lookup." />
                  <AssumptionSlider label="Fixed overhead per app per day" value={current.fixed_daily_myr} min={0} max={2} step={0.05}
                    format={(v) => formatMYR(v)} source={sourceOf("fixed_daily_myr")}
                    onChange={(v) => setOverrides((o) => ({ ...o, fixed_daily_myr: v }))}
                    help="Share of hosting/database attributable to the cache." />
                  <p className="text-xs text-muted-foreground">
                    Defaults: {defaults?.samples.real_static_faq_requests ?? 0} real FAQ requests observed
                    {defaults && defaults.samples.real_static_faq_requests < 50
                      ? " (fewer than 50, so rates come from the synthetic dataset or assumptions, not measurement)"
                      : ""}. Sliders are what-if only; approval uses the recommendation&apos;s assumptions.
                  </p>
                </CardContent>
              </Card>
              <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-3">
                <CardContent>
                  <SectionTitle>Forecast with and without caching</SectionTitle>
                  <CumulativeChart forecast={forecast} scenarioNetSavings={cache.net_savings_myr} height={260} />
                </CardContent>
              </Card>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="py-5 shadow-[var(--shadow-soft)]">
                <CardContent><QualityChecklist cache={cache} /></CardContent>
              </Card>
              <div className="space-y-3">
                {recs.isLoading && <LoadingBlock rows={1} />}
                {recs.isError && <ErrorState error={recs.error} onRetry={() => recs.refetch()} />}
                <RecommendationCard rec={latest ?? null} showLink={false} />
                {latest && latest.status === "proposed" && latest.action_type === "enable_semantic_cache" && (
                  <div className="flex flex-wrap gap-2">
                    <ApprovalDialog rec={latest} />
                    <OwnerButton variant="outline" onClick={() => reject.mutate()} disabled={reject.isPending || latest.superseded}
                      reason="Only the workspace owner can reject recommendations.">
                      <X className="size-4" /> Reject
                    </OwnerButton>
                    {latest.superseded && <p className="w-full text-xs text-warning">A newer forecast exists. Generate a fresh recommendation before approving.</p>}
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent>
              <SectionTitle>Cache policies</SectionTitle>
              {policies.isLoading && <LoadingBlock rows={1} />}
              {policies.isError && <ErrorState error={policies.error} />}
              <ul className="divide-y">
                {policies.data?.items.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-2 py-2.5 text-[13px]">
                    <span>
                      <span className="font-medium">{appLabel(p.application)}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        threshold {p.similarity_threshold} · TTL {p.ttl_hours}h{p.holdout_enabled ? " · 10% holdout" : ""}
                      </span>
                    </span>
                    {p.enabled ? (
                      <OwnerButton size="sm" variant="destructive" onClick={() => disable.mutate(p.id)} disabled={disable.isPending}
                        reason="Only the workspace owner can disable policies.">
                        <Power className="size-3.5" /> Disable
                      </OwnerButton>
                    ) : (
                      <Badge variant="outline">Off</Badge>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent>
              <SectionTitle aside={<span className="text-xs text-muted-foreground">since approval</span>}>Measurement</SectionTitle>
              {measurement.isLoading && <LoadingBlock rows={1} />}
              {measurement.isError && <ErrorState error={measurement.error} onRetry={() => measurement.refetch()} />}
              {measurement.data?.applications.every((a) => a.status === "never_enabled") && (
                <p className="text-sm text-muted-foreground">Nothing to measure yet: no policy has been enabled.</p>
              )}
              <ul className="space-y-3">
                {measurement.data?.applications.filter((a) => a.status !== "never_enabled").map((a) => (
                  <li key={a.application} className="rounded-md border p-3 text-[13px]">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-medium">{appLabel(a.application)}</span>
                      {a.provider_mode === "mock" && <DataSourceBadge origin="mock" />}
                    </div>
                    <p className="tabular text-muted-foreground">
                      {formatNum(a.requests)} requests · {formatNum(a.provider_calls)} provider calls ·{" "}
                      {formatNum((a.exact_hits ?? 0) + (a.semantic_hits ?? 0))} cache hits · {formatNum(a.bypassed)} bypassed
                    </p>
                    <p className="tabular">
                      Est. avoided {formatMYR(a.estimated_avoided_provider_cost_myr, true)} − overhead{" "}
                      {formatMYR(a.estimated_overhead_myr, true)} = net {formatMYR(a.estimated_net_savings_myr, true)}
                    </p>
                    <p className="text-xs text-muted-foreground">{a.method}</p>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>

        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle aside={<span className="text-xs text-muted-foreground">append-only</span>}>Audit history</SectionTitle>
            {audit.isLoading && <LoadingBlock rows={2} />}
            {audit.isError && <ErrorState error={audit.error} onRetry={() => audit.refetch()} />}
            {audit.data && audit.data.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">No changes recorded yet.</p>
            ) : (
              <div className="max-h-80 overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="eyebrow">When</TableHead>
                      <TableHead className="eyebrow">Action</TableHead>
                      <TableHead className="eyebrow">Application</TableHead>
                      <TableHead className="eyebrow">Change</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {audit.data?.items.map((a) => (
                      <TableRow key={a.id}>
                        <TableCell className="whitespace-nowrap text-xs">{formatDateTime(a.created_at)}</TableCell>
                        <TableCell className="text-[13px]">{titleCase(a.action)}</TableCell>
                        <TableCell className="text-[13px]">{a.application ? appLabel(a.application) : "—"}</TableCell>
                        <TableCell className="max-w-md truncate font-mono text-[11px] text-muted-foreground">
                          {a.new_value ? JSON.stringify(a.new_value) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
