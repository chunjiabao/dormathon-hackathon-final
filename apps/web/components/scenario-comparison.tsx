import { ArrowDown, ArrowRight, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { DataSourceBadge } from "@/components/data-source-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatMYR, formatNum, formatPct } from "@/lib/format";
import type { Scenario } from "@/lib/types";

export function ScenarioComparison({ baseline, cache }: { baseline: Scenario; cache: Scenario }) {
  const b = baseline.baseline_forecast;
  const s = cache.scenario_forecast;
  const sens = cache.savings_sensitivity_myr;
  return (
    <div className="grid items-stretch gap-4 md:grid-cols-[1fr_auto_1fr]">
      <Card className="gap-0 py-0 shadow-[var(--shadow-soft)]">
        <CardContent className="space-y-2 p-5">
          <p className="eyebrow">Baseline · no action</p>
          <p className="tabular text-[28px] font-bold tracking-tight">{formatMYR(b.total_myr)}</p>
          <p className="text-xs text-muted-foreground">
            Month-end forecast ({formatMYR(b.lower_myr)} – {formatMYR(b.upper_myr)}). Identical to the persisted forecast run.
          </p>
          <dl className="tabular space-y-1 pt-2 text-[13px]">
            <div className="flex justify-between"><dt className="text-muted-foreground">Observed to date</dt><dd>{formatMYR(b.observed_to_date_myr)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Remaining forecast</dt><dd>{formatMYR(b.predicted_remaining_myr)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">of which static FAQs (target apps)</dt><dd>{formatMYR(cache.details.faq_forecast_cost_myr)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Budget</dt><dd>{formatMYR(cache.budget_myr)}</dd></div>
          </dl>
        </CardContent>
      </Card>
      <div className="hidden items-center md:flex" aria-hidden>
        <ArrowRight className="size-5 text-muted-foreground" />
      </div>
      <div className="flex justify-center md:hidden" aria-hidden>
        <ArrowDown className="size-5 text-muted-foreground" />
      </div>
      <Card className="gap-0 border-primary/30 py-0 shadow-[var(--shadow-soft)]">
        <CardContent className="space-y-2 p-5">
          <div className="flex items-center justify-between gap-2">
            <p className="eyebrow">With approved-FAQ caching</p>
            <DataSourceBadge origin={cache.evidence_type} />
          </div>
          <p className="tabular text-[28px] font-bold tracking-tight text-primary">{formatMYR(s.total_myr)}</p>
          <p className="text-xs">
            {cache.within_budget_after ? (
              <span className="text-success">Central forecast within budget after this change.</span>
            ) : (
              <span className="flex items-center gap-1 text-warning">
                <TriangleAlert className="size-3.5" /> Still above the {formatMYR(cache.budget_myr)} budget.
              </span>
            )}
          </p>
          <dl className="tabular space-y-1 pt-2 text-[13px]">
            <div className="flex justify-between"><dt className="text-muted-foreground">Gross avoided provider cost</dt><dd>{formatMYR(cache.gross_savings_myr)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">− Cache overhead (assumed)</dt><dd>{formatMYR(cache.overhead_myr)}</dd></div>
            <div className="flex justify-between font-semibold"><dt>Net savings</dt><dd className={cache.net_savings_myr > 0 ? "text-success" : "text-danger"}>{formatMYR(cache.net_savings_myr)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Sensitivity (hit rates ±)</dt><dd>{formatMYR(sens.low)} – {formatMYR(sens.high)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">With forecast interval</dt><dd>{formatMYR(sens.forecast_interval.low)} – {formatMYR(sens.forecast_interval.high)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Predicted cache hits</dt><dd>{formatNum(cache.details.predicted_hits)} of {formatNum(cache.details.predicted_faq_requests)} FAQ requests</dd></div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

export function QualityChecklist({ cache }: { cache: Scenario }) {
  return (
    <ul className="space-y-2.5" aria-label="Quality gate checks">
      <li className="flex items-center gap-2">
        <span className="font-semibold">Quality gate:</span>
        <Badge variant={cache.quality_gate.status === "pass" ? "default" : "destructive"}>{cache.quality_gate.status}</Badge>
      </li>
      {cache.quality_gate.checks.map((c) => (
        <li key={c.id} className="flex gap-2 text-[13px]">
          {c.passed ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-label="passed" />
          ) : c.required ? (
            <CircleX className="mt-0.5 size-4 shrink-0 text-danger" aria-label="failed" />
          ) : (
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-label="warning" />
          )}
          <span>
            <span className="text-muted-foreground">{c.detail}</span>
            {!c.required && <span className="ml-1 text-xs text-muted-foreground">(advisory)</span>}
          </span>
        </li>
      ))}
      <li className="pt-1 text-xs text-muted-foreground">
        Hit-rate share shown: {formatPct(cache.assumptions.eligible_share * cache.assumptions.safe_hit_rate)} of static-FAQ
        requests in {cache.assumptions.target_apps.length} app(s).
      </li>
    </ul>
  );
}
