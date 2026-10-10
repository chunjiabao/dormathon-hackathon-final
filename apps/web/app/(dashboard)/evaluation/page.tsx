"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataSourceBadge } from "@/components/data-source-badge";
import { MetricCard } from "@/components/metric-card";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingCards } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { appLabel, formatDateTime, formatDay, formatMYR, formatMetric, formatPct, titleCase } from "@/lib/format";
import { useEvaluation, useForecast } from "@/lib/queries";
import type { EvaluationResults, Forecast } from "@/lib/types";

const MODEL_LABELS: Record<string, string> = {
  hist_gradient_boosting: "HistGradientBoosting",
  seasonal_naive_7: "Seasonal naive (t-7)",
  naive_previous_day: "Previous-day naive",
  rolling_mean_7: "7-day rolling mean",
};

const Th = ({ children, right }: { children: React.ReactNode; right?: boolean }) => (
  <TableHead className={`eyebrow ${right ? "text-right" : ""}`}>{children}</TableHead>
);
const Td = ({ children, right }: { children: React.ReactNode; right?: boolean }) => (
  <TableCell className={`tabular text-[13px] ${right ? "text-right" : ""}`}>{children}</TableCell>
);

function ForecastSection({ fc }: { fc: EvaluationResults }) {
  const origins: string[] = fc.test.origins;
  const [origin, setOrigin] = useState(origins[0]);
  const plot = useMemo(
    () => (fc.backtest_plot as { origin: string; day: string; actual: number; forecast: number; seasonal_naive: number }[])
      .filter((r) => r.origin === origin),
    [fc, origin],
  );
  const ov = fc.overrun_classification;
  return (
    <div className="space-y-4">
      <p className="text-[13px]">
        <span className="font-semibold">Shipped model: {MODEL_LABELS[fc.selection.chosen] ?? fc.selection.chosen}.</span>{" "}
        <span className="text-muted-foreground">{fc.selection.reason} (selected on validation only).</span>
      </p>
      <Card className="py-5 shadow-[var(--shadow-soft)]">
        <CardContent>
          <SectionTitle>Held-out test backtest: workspace daily cost</SectionTitle>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>
                <Th>Model</Th><Th right>MAE</Th><Th right>RMSE</Th><Th right>WAPE</Th><Th right>sMAPE</Th>
                <Th right>WAPE h=1</Th><Th right>h=2-7</Th><Th right>h=8-14</Th><Th right>Seg. WAPE excl. events</Th>
              </TableRow></TableHeader>
              <TableBody>
                {Object.entries(fc.test.scores as Record<string, EvaluationResults>).map(([m, s]) => (
                  <TableRow key={m} className={m === fc.selection.chosen ? "bg-accent/60" : undefined}>
                    <Td>{MODEL_LABELS[m] ?? m}{m === fc.selection.chosen && <Badge className="ml-1.5">shipped</Badge>}</Td>
                    <Td right>{formatMetric(s.workspace_daily.mae, 2)}</Td>
                    <Td right>{formatMetric(s.workspace_daily.rmse, 2)}</Td>
                    <Td right>{formatMetric(s.workspace_daily.wape)}</Td>
                    <Td right>{formatMetric(s.workspace_daily.smape)}</Td>
                    <Td right>{formatMetric(s.workspace_daily_h1.wape)}</Td>
                    <Td right>{formatMetric(s.workspace_daily_h2_7.wape)}</Td>
                    <Td right>{formatMetric(s.workspace_daily_h8_14.wape)}</Td>
                    <Td right>{formatMetric(s.segment_daily_excluding_event_days?.wape)}</Td>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {origins.length} origins × {fc.test.horizon_days}-day horizon, retrained at each origin. The test window contains
            injected anomalies, so absolute errors are large by design; the last column excludes injected-event days
            (labels used only for scoring). Interval coverage (nominal {formatPct(fc.test.interval_coverage.nominal)}):{" "}
            {formatPct(fc.test.interval_coverage.segment_daily, 1)} segment-days, {formatPct(fc.test.interval_coverage.cumulative_total, 1)} cumulative totals.
          </p>
        </CardContent>
      </Card>
      <Card className="py-5 shadow-[var(--shadow-soft)]">
        <CardContent>
          <SectionTitle aside={
            <Select value={origin} onValueChange={setOrigin}>
              <SelectTrigger className="w-44" aria-label="Backtest origin"><SelectValue /></SelectTrigger>
              <SelectContent>{origins.map((o) => <SelectItem key={o} value={o}>Origin {formatDay(o)}</SelectItem>)}</SelectContent>
            </Select>
          }>Backtest plot</SectionTitle>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={plot} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#ececea" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#71717a" }} tickFormatter={(d) => formatDay(d, false)} />
              <YAxis tick={{ fontSize: 11, fill: "#71717a" }} width={52} tickFormatter={(v) => `RM${v}`} />
              <Tooltip formatter={(v: number) => formatMYR(v)} labelFormatter={(d) => formatDay(String(d))} contentStyle={{ fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line dataKey="actual" name="Actual" stroke="var(--chart-actual)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="forecast" name={MODEL_LABELS[fc.selection.chosen]} stroke="var(--chart-forecast)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Line dataKey="seasonal_naive" name="Seasonal naive" stroke="var(--chart-reference)" strokeWidth={1.5} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      {ov?.status === "ok" && (
        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle>Month-end budget overrun classification</SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <Th>Budget</Th><Th right>Pos / neg</Th><Th right>Central precision</Th><Th right>Central recall</Th>
                <Th right>Lower-bound precision</Th><Th right>Upper-bound recall</Th>
              </TableRow></TableHeader>
              <TableBody>
                {Object.entries(ov.budgets as Record<string, EvaluationResults>).map(([b, v]) => (
                  <TableRow key={b}>
                    <Td>RM{b}</Td><Td right>{v.positives} / {v.negatives}</Td>
                    <Td right>{formatMetric(v.central_forecast.precision)}</Td>
                    <Td right>{formatMetric(v.central_forecast.recall)}</Td>
                    <Td right>{formatMetric(v.high_confidence_lower_bound.precision)}</Td>
                    <Td right>{formatMetric(v.possible_upper_bound.recall)}</Td>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-2 text-xs text-muted-foreground">
              {ov.n_origins} daily origins, model frozen at {formatDay(ov.frozen_at)}. Mean month-end error{" "}
              {formatPct(ov.month_end_abs_pct_error.all, 1)}. {ov.caveat} &quot;n/a&quot; = undefined (no predicted positives), not zero.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function AnomalySection({ an }: { an: EvaluationResults }) {
  const t = an.splits.test;
  const cm = t.confusion_matrix;
  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted-foreground">
        {an.methods.join(" + ")}. Thresholds chosen on validation (z ≥ {an.chosen_config.z_threshold}, IsolationForest
        quantile {an.chosen_config.if_quantile}, impact floor {formatMYR(an.chosen_config.impact_floor_myr)}); test reported once.
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-2">
          <CardContent>
            <SectionTitle>By split (application-days)</SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <Th>Split</Th><Th right>Precision</Th><Th right>Recall</Th><Th right>F1</Th><Th right>FPR</Th>
                <Th right>False alerts / 30d</Th><Th right>Event recall</Th><Th right>Delay (d)</Th>
              </TableRow></TableHeader>
              <TableBody>
                {Object.entries(an.splits as Record<string, EvaluationResults>).map(([n, s]) => (
                  <TableRow key={n} className={n === "test" ? "bg-accent/60" : undefined}>
                    <Td>{n}</Td><Td right>{formatMetric(s.day_level.precision)}</Td><Td right>{formatMetric(s.day_level.recall)}</Td>
                    <Td right>{formatMetric(s.day_level.f1)}</Td><Td right>{formatMetric(s.day_level.false_positive_rate)}</Td>
                    <Td right>{formatMetric(s.false_alerts_per_30_days, 2)}</Td><Td right>{formatMetric(s.event_recall)}</Td>
                    <Td right>{formatMetric(s.mean_detection_delay_days, 1)}</Td>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle>Test confusion matrix</SectionTitle>
            <div className="tabular grid grid-cols-[auto_1fr_1fr] gap-1 text-center text-[13px]" role="table" aria-label="Confusion matrix">
              <span />
              <span className="eyebrow">Alert</span>
              <span className="eyebrow">No alert</span>
              <span className="eyebrow self-center text-left">Anomaly</span>
              <span className="rounded bg-success/15 py-3 font-semibold">{cm.tp}</span>
              <span className="rounded bg-danger/10 py-3">{cm.fn}</span>
              <span className="eyebrow self-center text-left">Normal</span>
              <span className="rounded bg-danger/10 py-3">{cm.fp}</span>
              <span className="rounded bg-muted py-3">{cm.tn}</span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Benign promotions alerted: {an.benign_promotions_all_splits.alerted}/{an.benign_promotions_all_splits.total} (all splits).
            </p>
          </CardContent>
        </Card>
      </div>
      <Card className="py-5 shadow-[var(--shadow-soft)]">
        <CardContent>
          <SectionTitle>Test events</SectionTitle>
          <Table>
            <TableHeader><TableRow><Th>Event</Th><Th>Type</Th><Th>App</Th><Th>Start</Th><Th>Expected</Th><Th>Detected</Th><Th>Reasons</Th></TableRow></TableHeader>
            <TableBody>
              {(t.events as EvaluationResults[]).map((e) => (
                <TableRow key={e.event_id}>
                  <Td>{e.event_id}</Td><Td>{e.kind}</Td><Td>{appLabel(e.app_id)}</Td><Td>{formatDay(e.start_date)}</Td>
                  <Td>{e.alert_expected}</Td>
                  <Td>{e.detected ? <span className="text-success">yes · {e.detection_delay_days}d</span> : <span className="text-muted-foreground">no</span>}</Td>
                  <Td>{(e.reason_codes as string[]).map(titleCase).join(", ") || "—"}</Td>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">{(an.notes as string[]).map((n) => <li key={n}>{n}</li>)}</ul>
        </CardContent>
      </Card>
    </div>
  );
}

function CacheSection({ c, sim }: { c: EvaluationResults; sim: EvaluationResults | null }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Hit precision" value={formatMetric(c.hit_precision, 2)} sub={`${c.accepted_hits} accepted hits of ${c.n} queries`} tone="success" />
        <MetricCard label="False hits" value={String(c.false_hits)} sub={`${c.adversarial_false_hits} on adversarial queries`} tone={c.false_hits ? "danger" : "success"} />
        <MetricCard label="Coverage" value={formatPct(c.positive_coverage)} sub="of answerable questions served from cache" />
        <MetricCard label="Decision latency" value={`${c.latency_ms.median.toFixed(2)} ms`} sub={`p95 ${c.latency_ms.p95.toFixed(2)} ms`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle>Similarity threshold sweep</SectionTitle>
            <Table>
              <TableHeader><TableRow><Th>Threshold</Th><Th right>Hit precision</Th><Th right>Coverage</Th><Th right>False hits</Th></TableRow></TableHeader>
              <TableBody>
                {(c.threshold_sweep as EvaluationResults[]).map((s) => (
                  <TableRow key={s.threshold} className={s.threshold === c.threshold ? "bg-accent/60" : undefined}>
                    <Td>{s.threshold}</Td><Td right>{formatMetric(s.hit_precision)}</Td><Td right>{formatPct(s.positive_coverage)}</Td>
                    <Td right>{s.false_hits}</Td>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-2 text-xs text-muted-foreground">
              Without the deterministic safety gate (embeddings only): precision {formatMetric(c.ablation_without_safety_gate.hit_precision)},{" "}
              {c.ablation_without_safety_gate.false_hits} false hit(s). {c.caveat}
            </p>
          </CardContent>
        </Card>
        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle>By query group</SectionTitle>
            <Table>
              <TableHeader><TableRow><Th>Group</Th><Th right>Queries</Th><Th right>Hits</Th><Th right>Correct hits</Th></TableRow></TableHeader>
              <TableBody>
                {Object.entries(c.by_group as Record<string, EvaluationResults>).map(([g, v]) => (
                  <TableRow key={g}><Td>{titleCase(g)}</Td><Td right>{v.n}</Td><Td right>{v.hits}</Td><Td right>{v.correct_hits}</Td></TableRow>
                ))}
              </TableBody>
            </Table>
            {sim && (
              <div className="mt-4 space-y-1 rounded-md bg-muted/60 p-3 text-[13px]">
                <p className="eyebrow">What-if simulator vs counterfactual truth</p>
                <p className="tabular">True net savings {formatMYR(sim.true_net_savings_myr)} ({formatDay(sim.window[0])} – {formatDay(sim.window[1])})</p>
                <p className="tabular">On actual units: {formatMYR(sim.oracle_actual_units.estimate_myr)} ({formatPct(sim.oracle_actual_units.pct_error, 1)} error)</p>
                <p className="tabular">On the forecast (as in production): {formatMYR(sim.forecast_based.estimate_myr)} ({formatPct(sim.forecast_based.pct_error, 1)} error)</p>
                <p className="text-xs text-muted-foreground">{sim.note}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function EvaluationPage() {
  const ev = useEvaluation();
  const fq = useForecast();
  const r = ev.data?.evaluation?.results;
  const f = fq.data && fq.data.status === "ok" ? (fq.data as Forecast) : null;
  return (
    <>
      <PageHeader
        title="Evaluation"
        description="Honest, code-generated metrics for the forecaster, anomaly detector and safe cache."
        badges={<DataSourceBadge origin="synthetic" />}
      />
      {ev.isLoading && <LoadingCards />}
      {ev.isError && <ErrorState error={ev.error} onRetry={() => ev.refetch()} />}
      {ev.data?.status === "not_run" && (
        <EmptyState title="No evaluation has run yet">
          Run <code>scripts/run_evaluation.py --db</code> (or <code>make train</code>). No placeholder numbers are shown.
        </EmptyState>
      )}
      {r && (
        <div className="space-y-6">
          <Card className="gap-0 py-0 shadow-[var(--shadow-soft)]">
            <CardContent className="grid gap-3 p-5 text-[13px] md:grid-cols-3">
              <div>
                <p className="eyebrow">Dataset</p>
                <p>Synthetic, seed {r.dataset.seed}, {r.dataset.days} days ({formatDay(r.dataset.start_date)} – {formatDay(r.dataset.end_date)})</p>
                <p className="text-xs text-muted-foreground">Train {r.dataset.splits.train.join(" → ")} · validation {r.dataset.splits.validation.join(" → ")} · test {r.dataset.splits.test.join(" → ")}</p>
              </div>
              <div>
                <p className="eyebrow">Run</p>
                <p>{formatDateTime(ev.data!.evaluation!.evaluated_at)} · {r.runtime_seconds}s</p>
                <p className="text-xs text-muted-foreground">Artifact {ev.data!.evaluation!.artifact_path}</p>
              </div>
              <div>
                <p className="eyebrow">Data behind today&apos;s forecast</p>
                {f ? Object.entries(f.data_mix).map(([o, m]) => (
                  <p key={o} className="flex items-center gap-2"><DataSourceBadge origin={o} /> {m.days} days, {formatPct(m.cost_share, 1)} of cost</p>
                )) : <p className="text-muted-foreground">No forecast yet.</p>}
              </div>
            </CardContent>
          </Card>
          <Tabs defaultValue="forecast">
            <TabsList className="h-auto flex-wrap">
              <TabsTrigger value="forecast">Forecasting</TabsTrigger>
              <TabsTrigger value="anomaly">Anomalies</TabsTrigger>
              <TabsTrigger value="cache">Safe cache & simulator</TabsTrigger>
            </TabsList>
            <TabsContent value="forecast" className="pt-3"><ForecastSection fc={r.forecast} /></TabsContent>
            <TabsContent value="anomaly" className="pt-3"><AnomalySection an={r.anomaly} /></TabsContent>
            <TabsContent value="cache" className="pt-3">
              {r.cache ? <CacheSection c={r.cache} sim={r.simulator} /> : <EmptyState title="Cache evaluation not in this run" />}
            </TabsContent>
          </Tabs>
          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent className="text-[13px]">
              <SectionTitle>Limitations</SectionTitle>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>All metrics here are on synthetic data generated by our own simulator; they do not demonstrate performance on real customers.</li>
                <li>Tree models cannot extrapolate sustained growth; the upper bound is the conservative budget signal.</li>
                <li>Intervals are empirical and under-cover during distribution shift (campaigns, outages, prompt changes).</li>
                <li>Cache results come from a 51-query hand-labelled set; zero false hits there is not a general guarantee.</li>
                <li><Link href="/model-card" className="text-primary underline">Read the full model card</Link>. Generated report: <code>docs/evaluation_report.md</code>.</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
