"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, FlaskConical } from "lucide-react";
import { useMemo, useState } from "react";
import { Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { DataSourceBadge } from "@/components/data-source-badge";
import { OwnerButton } from "@/components/owner-button";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import { appLabel, formatDay, formatMYR, formatMetric, formatNum, formatPct, titleCase } from "@/lib/format";
import { useAnomalies, useEvaluation, useUsageDaily } from "@/lib/queries";
import type { Anomaly } from "@/lib/types";

const PCT_METRICS = new Set(["expensive_share", "retry_rate"]);
const METRIC_LABELS: Record<string, string> = {
  requests: "Requests",
  cost: "Daily cost",
  in_per_req: "Input tokens / request",
  cost_per_req: "Cost / request",
  expensive_share: "Expensive-model share",
  retry_rate: "Retry rate",
};

function fmtMetric(metric: string, v: number) {
  if (PCT_METRICS.has(metric)) return formatPct(v, 1);
  if (metric === "cost") return formatMYR(v);
  if (metric === "cost_per_req") return formatMYR(v, true);
  return formatNum(v, metric === "in_per_req" ? 0 : 0);
}

function addDays(day: string, n: number) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function Sparkline({ data, start, end }: { data: { day: string; cost: number }[]; start: string; end: string }) {
  if (!data.length) return <span className="text-xs text-muted-foreground">no series</span>;
  return (
    <div className="h-12 w-40" aria-label="Daily cost around the event">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 2, bottom: 4, left: 2 }}>
          <XAxis hide dataKey="day" />
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <ReferenceArea x1={start} x2={end} fill="#fde68a" fillOpacity={0.6} ifOverflow="extendDomain" />
          <Tooltip
            formatter={(v: number) => [formatMYR(v), "Cost"]}
            labelFormatter={(_, p) => formatDay(p?.[0]?.payload?.day)}
            contentStyle={{ fontSize: 11 }}
          />
          <Line dataKey="cost" stroke="var(--chart-actual)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function AnomalyRow({ a, series }: { a: Anomaly; series: Map<string, { day: string; cost: number }[]> }) {
  const qc = useQueryClient();
  const ack = useMutation({
    mutationFn: () => api.acknowledge(a.id),
    onSuccess: () => {
      toast.success("Anomaly acknowledged");
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const end = a.end_day ?? a.day;
  const window = (series.get(`${a.application}:${a.is_synthetic ? "synthetic" : "real"}`) ?? []).filter((p) => p.day >= addDays(a.day, -14) && p.day <= addDays(end, 7));
  const gt = a.synthetic_ground_truth;
  return (
    <Card className="gap-0 py-0 shadow-[var(--shadow-soft)]">
      <CardContent className="grid gap-4 p-5 md:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={a.severity === "high" ? "destructive" : a.severity === "medium" ? "default" : "secondary"}>
              {a.severity}
            </Badge>
            <span className="font-semibold">{titleCase(a.reason_code)}</span>
            <span className="text-[13px] text-muted-foreground">
              {appLabel(a.application)} · {formatDay(a.day)}
              {a.end_day && a.end_day !== a.day && ` → ${formatDay(a.end_day)}`}
            </span>
            {a.is_synthetic && <DataSourceBadge origin="synthetic" />}
            {a.acknowledged_at && (
              <Badge variant="outline" className="gap-1">
                <Check className="size-3" /> acknowledged
              </Badge>
            )}
          </div>
          <dl className="tabular grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-4">
            <div>
              <dt className="eyebrow">{METRIC_LABELS[a.metric] ?? a.metric}</dt>
              <dd>{fmtMetric(a.metric, a.observed_value)}</dd>
            </div>
            <div>
              <dt className="eyebrow">Expected</dt>
              <dd className="text-muted-foreground">{fmtMetric(a.metric, a.expected_value)}</dd>
            </div>
            <div>
              <dt className="eyebrow">Est. extra cost</dt>
              <dd>{a.estimated_impact_myr === null ? "—" : formatMYR(a.estimated_impact_myr)}</dd>
            </div>
            <div>
              <dt className="eyebrow">Robust z-score</dt>
              <dd>{formatMetric(a.anomaly_score, 1)}</dd>
            </div>
          </dl>
          <p className="text-[13px] leading-relaxed">{a.explanation}</p>
          {gt && (
            <p className="flex items-start gap-1.5 rounded-md bg-warning/10 px-2.5 py-1.5 text-xs text-[#92400e]">
              <FlaskConical className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                {gt.event_id ? (
                  <>
                    Known injected mechanism ({gt.event_id}, {gt.kind}): {gt.mechanism}. Class: {titleCase(gt.event_class ?? "")}.
                  </>
                ) : (
                  gt.mechanism
                )}
              </span>
            </p>
          )}
        </div>
        <div className="flex flex-row items-center justify-between gap-3 md:flex-col md:items-end">
          <Sparkline data={window} start={a.day} end={end} />
          {!a.acknowledged_at && (
            <OwnerButton size="sm" variant="outline" onClick={() => ack.mutate()} disabled={ack.isPending}
              reason="Only the workspace owner can acknowledge alerts.">
              Acknowledge
            </OwnerButton>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function AnomaliesPage() {
  const [severity, setSeverity] = useState("all");
  const q = useAnomalies(severity === "all" ? undefined : severity);
  const usage = useUsageDaily({});
  const ev = useEvaluation();

  const series = useMemo(() => {
    const m = new Map<string, Map<string, number>>();
    for (const r of usage.data?.items ?? []) {
      const key = `${r.application}:${r.data_origin}`;
      const app = m.get(key) ?? new Map<string, number>();
      app.set(r.day, (app.get(r.day) ?? 0) + r.cost_myr);
      m.set(key, app);
    }
    const out = new Map<string, { day: string; cost: number }[]>();
    m.forEach((days, app) =>
      out.set(app, [...days.entries()].sort().map(([day, cost]) => ({ day, cost: Math.round(cost * 100) / 100 }))),
    );
    return out;
  }, [usage.data]);

  const test = ev.data?.evaluation?.results?.anomaly?.splits?.test;
  const benign = ev.data?.evaluation?.results?.anomaly?.benign_promotions_all_splits;

  return (
    <>
      <PageHeader
        title="Anomalies"
        description="Statistically unusual daily usage per application, explained with observed vs expected values."
        actions={
          <Select value={severity} onValueChange={setSeverity}>
            <SelectTrigger className="w-40" aria-label="Filter by severity">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All severities</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="low">Low</SelectItem>
            </SelectContent>
          </Select>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-3">
          {q.isLoading && <LoadingBlock rows={4} />}
          {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
          {q.data && q.data.items.length === 0 && (
            <EmptyState title="No anomalies">
              Nothing unusual in the last 90 days{severity !== "all" ? ` at ${severity} severity` : ""}, or not enough history
              yet (detection needs 6+ weeks per application).
            </EmptyState>
          )}
          {q.data?.items.map((a) => <AnomalyRow key={a.id} a={a} series={series} />)}
        </div>
        <aside className="space-y-4">
          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent className="space-y-3 text-[13px]">
              <SectionTitle>How detection works</SectionTitle>
              <p className="text-muted-foreground">
                Two detectors: a robust same-weekday median/MAD baseline, and an IsolationForest trained on earlier
                history. An alert needs an unusual pattern <em>and</em> at least RM0.50 of extra cost per day; outages
                alert regardless of cost. Consecutive days merge into one alert.
              </p>
              <p className="text-muted-foreground">
                Scores are robust z-scores, not probabilities. Explanations are correlations in usage metrics, not proven
                causes.
              </p>
            </CardContent>
          </Card>
          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent className="space-y-3 text-[13px]">
              <SectionTitle aside={<DataSourceBadge origin="synthetic" />}>False alarms (held-out test)</SectionTitle>
              {ev.isError ? <ErrorState error={ev.error} onRetry={() => ev.refetch()} /> : ev.isLoading ? <LoadingBlock rows={1} /> : !test ? (
                <p className="text-muted-foreground">No evaluation has been run yet.</p>
              ) : (
                <dl className="tabular grid grid-cols-2 gap-2">
                  <dt className="text-muted-foreground">Precision</dt>
                  <dd className="text-right">{formatMetric(test.day_level.precision)}</dd>
                  <dt className="text-muted-foreground">Recall</dt>
                  <dd className="text-right">{formatMetric(test.day_level.recall)}</dd>
                  <dt className="text-muted-foreground">False alerts / 30 days</dt>
                  <dd className="text-right">{formatMetric(test.false_alerts_per_30_days, 2)}</dd>
                  <dt className="text-muted-foreground">Benign promotions alerted</dt>
                  <dd className="text-right">{benign ? `${benign.alerted}/${benign.total}` : "—"}</dd>
                </dl>
              )}
              <p className="text-xs text-muted-foreground">
                Benign one-day weekend promotions are deliberate hard negatives in the synthetic data. A real campaign
                can still trigger a traffic-spike alert; acknowledge it if expected.
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </>
  );
}
