"use client";

import { Activity, ArrowRight, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { DataSourceBadge } from "@/components/data-source-badge";
import { DriverBreakdown } from "@/components/driver-breakdown";
import { CumulativeChart } from "@/components/forecast-chart";
import { MetricCard } from "@/components/metric-card";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { RecommendationCard } from "@/components/recommendation-card";
import { EmptyState, ErrorState, LoadingCards } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { appLabel, formatDay, formatMYR, formatPct, titleCase } from "@/lib/format";
import { useHealth, useOverview, useRecommendations } from "@/lib/queries";
import { RISK } from "@/lib/risk";

export default function OverviewPage() {
  const o = useOverview();
  const recs = useRecommendations();
  const health = useHealth();
  const f = o.data?.forecast;
  const latestRec = recs.data?.items[0];
  const scenario = latestRec && !latestRec.superseded && latestRec.forecast_run_id === f?.id ? latestRec.scenario : null;

  return (
    <>
      <PageHeader
        title="Predict early. Spend smarter."
        description="Month-end AI spend forecast for your workspace, what is driving it, and the safest action to take."
        badges={
          <>
            {f && <DataSourceBadge origin={f.evidence_type} />}
            <DataSourceBadge origin="forecast" />
          </>
        }
      />
      {o.isLoading && <LoadingCards />}
      {o.isError && <ErrorState error={o.error} onRetry={() => o.refetch()} />}
      {o.data && (
        <div className="space-y-6">
          {!f || f.status !== "ok" ? (
            <EmptyState title="No forecast yet">
              {f?.status === "insufficient_data"
                ? `Not enough history: ${String(f.assumptions.reason ?? "")}`
                : "Seed demo data and run a forecast (Predictions → Run forecast) to see month-end projections."}
            </EmptyState>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="Current spend"
                  value={formatMYR(f.observed_to_date_myr)}
                  sub={`Month to date, through ${formatDay(f.training_cutoff)}`}
                  help="Actual estimated provider cost for complete days this month (synthetic history + live traffic)."
                />
                <MetricCard
                  label="Month-end forecast"
                  value={formatMYR(f.forecast_total_myr)}
                  sub={`${formatMYR(f.lower_myr)} – ${formatMYR(f.upper_myr)} (90% interval)`}
                  help="Actual month-to-date + forecast of every remaining day. Interval from backtest residuals."
                  badge={<DataSourceBadge origin="forecast" />}
                />
                <MetricCard
                  label="Budget risk"
                  value={RISK[f.budget_risk].label}
                  tone={RISK[f.budget_risk].tone}
                  sub={
                    f.budget_crossing_date
                      ? `Budget ${formatMYR(f.budget_myr)} crossed around ${formatDay(f.budget_crossing_date)}`
                      : `Budget ${formatMYR(f.budget_myr)}`
                  }
                  help={RISK[f.budget_risk].help}
                />
                <MetricCard
                  label="Potential net savings"
                  value={scenario ? formatMYR(scenario.net_savings_myr) : "—"}
                  sub={
                    scenario
                      ? `${formatMYR(scenario.savings_sensitivity_myr.low)} – ${formatMYR(scenario.savings_sensitivity_myr.high)} this month, after overhead`
                      : "Generate a recommendation in the Decision Lab"
                  }
                  help="Simulated on the same forecast: approved-FAQ caching savings minus estimated cache overhead."
                  badge={scenario ? <DataSourceBadge origin={scenario.evidence_type} /> : undefined}
                  tone={scenario && scenario.net_savings_myr > 0 ? "success" : "default"}
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-2">
                  <CardContent>
                    <SectionTitle aside={<DataSourceBadge origin={f.evidence_type} />}>
                      Cumulative spend vs budget
                    </SectionTitle>
                    <CumulativeChart forecast={f} scenarioNetSavings={scenario?.net_savings_myr} />
                  </CardContent>
                </Card>
                <Card className="py-5 shadow-[var(--shadow-soft)]">
                  <CardContent>
                    <SectionTitle
                      aside={
                        <Link href="/predictions" className="text-xs text-primary hover:underline">
                          Details
                        </Link>
                      }
                    >
                      Top predicted cost drivers
                    </SectionTitle>
                    <DriverBreakdown rows={o.data.top_drivers} showIncrement={false} />
                    {o.data.driver_statements[0] && (
                      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">{o.data.driver_statements[0]}</p>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            <RecommendationCard rec={o.data.recommendation} />
            <Card className="py-5 shadow-[var(--shadow-soft)]">
              <CardContent className="space-y-3">
                <SectionTitle aside={<span className="text-xs text-muted-foreground">{o.data.open_alerts} open</span>}>
                  <span className="flex items-center gap-2">
                    <TriangleAlert className="size-4 text-warning" aria-hidden /> Latest anomaly
                  </span>
                </SectionTitle>
                {o.data.latest_anomaly ? (
                  <>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant={o.data.latest_anomaly.severity === "high" ? "destructive" : "secondary"}>
                        {o.data.latest_anomaly.severity}
                      </Badge>
                      <span className="text-[13px] font-medium">{titleCase(o.data.latest_anomaly.reason_code)}</span>
                      <span className="text-xs text-muted-foreground">
                        {appLabel(o.data.latest_anomaly.application)} · {formatDay(o.data.latest_anomaly.day)}
                      </span>
                      {o.data.latest_anomaly.is_synthetic && <DataSourceBadge origin="synthetic" />}
                    </div>
                    <p className="text-[13px] leading-relaxed text-muted-foreground">{o.data.latest_anomaly.explanation}</p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No anomalies detected in the lookback window.</p>
                )}
                <Button asChild variant="outline" size="sm">
                  <Link href="/anomalies">
                    All anomalies <ArrowRight className="size-3.5" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
            <Card className="py-5 shadow-[var(--shadow-soft)]">
              <CardContent className="space-y-3">
                <SectionTitle aside={<DataSourceBadge origin={health.data?.dependencies.anthropic.mode === "mock" ? "mock" : "real"} />}>
                  <span className="flex items-center gap-2">
                    <Activity className="size-4 text-primary" aria-hidden /> Cache policy & live traffic
                  </span>
                </SectionTitle>
                <ul className="space-y-1.5 text-[13px]">
                  {o.data.policies.map((p) => (
                    <li key={p.id} className="flex items-center justify-between">
                      <span>{appLabel(p.application)}</span>
                      <Badge variant={p.enabled ? "default" : "outline"}>
                        {p.enabled ? `On · ≥${p.similarity_threshold}` : "Off"}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <div className="rounded-md bg-muted/60 p-3 text-[13px]">
                  <p className="eyebrow mb-1">Last 7 days (gateway)</p>
                  <p className="tabular">
                    {o.data.live_traffic_7d.requests} requests · {o.data.live_traffic_7d.cache_hits} safe cache hits ·{" "}
                    hit rate {formatPct(o.data.live_traffic_7d.cache_hit_rate)}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
