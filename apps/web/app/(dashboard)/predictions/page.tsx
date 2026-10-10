"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { DataSourceBadge } from "@/components/data-source-badge";
import { CumulativeChart, DailyChart } from "@/components/forecast-chart";
import { MetricCard } from "@/components/metric-card";
import { OwnerButton } from "@/components/owner-button";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingCards } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, api } from "@/lib/api";
import { appLabel, categoryLabel, formatDateTime, formatDay, formatMYR, formatMetric, formatPct, titleCase } from "@/lib/format";
import { useDrivers, useForecast } from "@/lib/queries";
import { RISK } from "@/lib/risk";
import type { Forecast } from "@/lib/types";

const MODEL_LABELS: Record<string, string> = {
  hist_gradient_boosting: "HistGradientBoosting (candidate)",
  seasonal_naive_7: "Seasonal naive (t-7)",
  naive_previous_day: "Previous-day naive",
  rolling_mean_7: "7-day rolling mean",
};

function HowItWorks({ f }: { f: Forecast }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm">
          <BookOpen className="size-4" /> How the forecast works
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>How the forecast works</SheetTitle>
          <SheetDescription>Every number on this page is computed by code from your usage history.</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6 text-[13px] leading-relaxed">
          <section>
            <h3 className="mb-1">What is predicted</h3>
            <p>
              Daily estimated provider cost for each application × request category. Month-end total = actual cost of
              complete days this month (counted once) + the forecast for every remaining day, including today.
            </p>
          </section>
          <section>
            <h3 className="mb-1">Model choice</h3>
            <p>
              Each run compares three baselines and a HistGradientBoosting model on rolling-origin backtests over the last
              28 complete days (retrained at each origin). The candidate is used only if it beats seasonal naive on WAPE;
              otherwise the baseline ships. This run: <strong>{MODEL_LABELS[f.model_name] ?? f.model_name}</strong>.
            </p>
            {f.metrics.selection_reason && <p className="mt-1 text-muted-foreground">{f.metrics.selection_reason}.</p>}
          </section>
          <section>
            <h3 className="mb-1">Features (no leakage)</h3>
            <p>
              Lags at t-1, t-7, t-14; 7/14/28-day rolling means and deviations of values strictly before each day; weekday,
              day of month, trend and model mix. Injected anomaly labels are never used.
            </p>
          </section>
          <section>
            <h3 className="mb-1">Uncertainty</h3>
            <p>
              The shaded band is a 90% empirical interval from backtest residuals. It is not a guarantee: coverage drops
              when usage shifts suddenly (campaigns, outages, prompt changes). Budget risk uses fixed thresholds on the
              bounds, not a probability.
            </p>
          </section>
          <section>
            <h3 className="mb-1">Data used</h3>
            <ul className="list-disc space-y-0.5 pl-5">
              {Object.entries(f.data_mix).map(([origin, m]) => (
                <li key={origin}>
                  <span className="capitalize">{origin}</span>: {m.days} days ({m.first_day} → {m.last_day}),{" "}
                  {formatPct(m.cost_share)} of cost
                </li>
              ))}
            </ul>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function PredictionsPage() {
  const qc = useQueryClient();
  const fq = useForecast();
  const f = fq.data && fq.data.status !== "no_forecast" ? (fq.data as Forecast) : null;
  const drivers = useDrivers(f?.status === "ok" ? f.id : undefined);
  const run = useMutation({
    mutationFn: api.runForecast,
    onSuccess: (r) => {
      toast.success(`Forecast updated (${MODEL_LABELS[r.model_name] ?? r.model_name})`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Forecast failed"),
  });

  const runButton = (
    <OwnerButton onClick={() => run.mutate()} disabled={run.isPending} reason="Only the workspace owner can trigger a forecast run.">
      {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
      {run.isPending ? "Running (≈10 s)…" : "Run forecast"}
    </OwnerButton>
  );

  return (
    <>
      <PageHeader
        title="Predictions"
        description="Daily cost forecast to month-end with uncertainty, segment breakdown and baseline comparison."
        actions={
          <>
            {f?.status === "ok" && <HowItWorks f={f} />}
            {runButton}
          </>
        }
        badges={f ? <><DataSourceBadge origin={f.evidence_type} /><DataSourceBadge origin="forecast" /></> : undefined}
      />
      {fq.isLoading && <LoadingCards />}
      {fq.isError && <ErrorState error={fq.error} onRetry={() => fq.refetch()} />}
      {fq.data?.status === "no_forecast" && (
        <EmptyState title="No forecast has been run" action={runButton}>
          Seed the synthetic demo history (scripts/seed_demo.py) or send traffic, then run a forecast.
        </EmptyState>
      )}
      {f?.status === "insufficient_data" && (
        <EmptyState title="Insufficient history" action={runButton}>
          {String(f.assumptions.reason ?? "Not enough daily history to forecast reliably.")}
        </EmptyState>
      )}
      {f?.status === "ok" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Observed to date" value={formatMYR(f.observed_to_date_myr)}
              sub={`Complete days through ${formatDay(f.training_cutoff)}`} />
            <MetricCard label="Remaining forecast" value={formatMYR(f.predicted_remaining_myr)}
              sub={`From ${formatDay(String(f.assumptions.forecast_from ?? ""))} to month-end`} badge={<DataSourceBadge origin="forecast" />} />
            <MetricCard label="Month-end total" value={formatMYR(f.forecast_total_myr)}
              sub={`${formatMYR(f.lower_myr)} – ${formatMYR(f.upper_myr)} · 90% interval`} tone={RISK[f.budget_risk].tone}
              help={RISK[f.budget_risk].help} />
            <MetricCard label="Budget crossing" value={f.budget_crossing_date ? formatDay(f.budget_crossing_date) : "Not crossed"}
              sub={f.budget_crossing_date ? `Central forecast passes ${formatMYR(f.budget_myr)}` : `Central forecast stays under ${formatMYR(f.budget_myr)}`}
              help="Shown only if the cumulative actual + central forecast curve crosses the budget within this month." />
          </div>

          <Card className="py-5 shadow-[var(--shadow-soft)]">
            <CardContent>
              <Tabs defaultValue="daily">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-[15px]">Forecast</h2>
                  <TabsList>
                    <TabsTrigger value="daily">Daily</TabsTrigger>
                    <TabsTrigger value="cumulative">Cumulative</TabsTrigger>
                  </TabsList>
                </div>
                <TabsContent value="daily"><DailyChart forecast={f} /></TabsContent>
                <TabsContent value="cumulative"><CumulativeChart forecast={f} /></TabsContent>
              </Tabs>
              <p className="mt-3 text-xs text-muted-foreground">
                Next 7 days: {formatMYR(f.next_7_days_myr)} · training cutoff {formatDay(f.training_cutoff)} · generated{" "}
                {formatDateTime(f.generated_at)} · {MODEL_LABELS[f.model_name] ?? f.model_name}
                {Number(f.assumptions.data_gap_days) > 0 && ` · ${f.assumptions.data_gap_days} day(s) without data were forecast`}
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-5">
            <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-3">
              <CardContent>
                <SectionTitle aside={drivers.data?.reconciles_with_forecast ? <Badge variant="secondary">Reconciles with total</Badge> : undefined}>
                  Remaining spend by segment
                </SectionTitle>
                {drivers.isLoading && <LoadingCards count={1} />}
                {drivers.isError && <ErrorState error={drivers.error} />}
                {drivers.data && (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="eyebrow">Application</TableHead>
                          <TableHead className="eyebrow">Category</TableHead>
                          <TableHead className="eyebrow text-right">Forecast</TableHead>
                          <TableHead className="eyebrow text-right">Share</TableHead>
                          <TableHead className="eyebrow text-right">vs run rate</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {drivers.data.segments.map((s) => (
                          <TableRow key={`${s.application}-${s.request_category}`}>
                            <TableCell>{appLabel(s.application)}</TableCell>
                            <TableCell>{categoryLabel(s.request_category)}</TableCell>
                            <TableCell className="tabular text-right">{formatMYR(s.predicted_remaining_myr)}</TableCell>
                            <TableCell className="tabular text-right">{formatPct(s.share, 1)}</TableCell>
                            <TableCell className={`tabular text-right ${s.increment_vs_run_rate_myr > 0 ? "text-warning" : "text-muted-foreground"}`}>
                              {s.increment_vs_run_rate_myr >= 0 ? "+" : "−"}{formatMYR(Math.abs(s.increment_vs_run_rate_myr))}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <p className="mt-2 text-xs text-muted-foreground">{drivers.data.method}</p>
                  </div>
                )}
              </CardContent>
            </Card>
            <Card className="py-5 shadow-[var(--shadow-soft)] lg:col-span-2">
              <CardContent>
                <SectionTitle>Model vs baselines (this run)</SectionTitle>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="eyebrow">Model</TableHead>
                      <TableHead className="eyebrow text-right">WAPE</TableHead>
                      <TableHead className="eyebrow text-right">MAE</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(f.metrics.calibration_scores ?? {}).map(([m, s]) => (
                      <TableRow key={m} className={m === f.model_name ? "bg-accent/60" : undefined}>
                        <TableCell className="text-[13px]">
                          {MODEL_LABELS[m] ?? titleCase(m)} {m === f.model_name && <Badge className="ml-1">used</Badge>}
                        </TableCell>
                        <TableCell className="tabular text-right">{formatMetric(s.wape)}</TableCell>
                        <TableCell className="tabular text-right">{formatMetric(s.mae, 2)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <p className="mt-2 text-xs text-muted-foreground">
                  Workspace-level daily cost, backtested on {f.metrics.calibration_window?.join(" → ")} (
                  {f.metrics.calibration_origins} origins, retrained per origin). Lower is better. Held-out evaluation is on
                  the Evaluation page.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
