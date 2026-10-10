"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { OwnerButton } from "@/components/owner-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError, api } from "@/lib/api";
import { appLabel, formatMYR, formatPct } from "@/lib/format";
import type { Recommendation } from "@/lib/types";

export function ApprovalDialog({ rec }: { rec: Recommendation }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [holdout, setHoldout] = useState(false);
  const s = rec.scenario;
  const approve = useMutation({
    mutationFn: () => api.approve(rec.id, rec.version, holdout),
    onSuccess: () => {
      toast.success("Approved: FAQ caching is now enabled for the target applications.");
      setOpen(false);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Approval failed"),
  });
  const blocked = rec.superseded || rec.status !== "proposed" || rec.action_type !== "enable_semantic_cache";

  return (
    <>
      <OwnerButton onClick={() => setOpen(true)} disabled={blocked} reason="Only the workspace owner can approve changes.">
        <ShieldCheck className="size-4" /> Approve & enable
      </OwnerButton>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Enable approved-FAQ caching?</DialogTitle>
            <DialogDescription>
              Matching customer questions will be answered from your approved FAQ answers without calling Anthropic.
              You can disable this at any time; every change is audited.
            </DialogDescription>
          </DialogHeader>
          {s && (
            <div className="space-y-4 text-[13px]">
              <section className="rounded-md border p-3">
                <p className="eyebrow mb-2">Estimated effect this month</p>
                <dl className="tabular space-y-1">
                  <div className="flex justify-between"><dt>Forecast now</dt><dd>{formatMYR(s.baseline_forecast.total_myr)}</dd></div>
                  <div className="flex justify-between"><dt>Forecast with caching</dt><dd>{formatMYR(s.scenario_forecast.total_myr)}</dd></div>
                  <div className="flex justify-between font-semibold"><dt>Net savings</dt><dd>{formatMYR(s.net_savings_myr)} ({formatMYR(s.savings_sensitivity_myr.low)} – {formatMYR(s.savings_sensitivity_myr.high)})</dd></div>
                  <div className="flex justify-between"><dt>Budget</dt><dd>{formatMYR(s.budget_myr)} {s.within_budget_after ? "(met)" : "(still exceeded)"}</dd></div>
                </dl>
              </section>
              <section>
                <p className="eyebrow mb-1">Assumptions</p>
                <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                  <li>Eligible share of static-FAQ requests: {formatPct(s.assumptions.eligible_share)} ({s.assumptions.sources.eligible_share})</li>
                  <li>Safe hit rate among eligible: {formatPct(s.assumptions.safe_hit_rate)} ({s.assumptions.sources.safe_hit_rate})</li>
                  <li>Overhead: {formatMYR(s.assumptions.overhead_per_lookup_myr, true)} per lookup + {formatMYR(s.assumptions.fixed_daily_myr)} per app per day (assumed)</li>
                  <li>Applications: {s.assumptions.target_apps.map(appLabel).join(", ")}</li>
                </ul>
              </section>
              <section>
                <p className="eyebrow mb-1">Quality risks</p>
                <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                  <li>Similarity matching can still be wrong for phrasings not in the test set; only approved FAQ answers are ever returned.</li>
                  <li>Personal, order-specific, time-sensitive, numeric and non-English questions always go to Anthropic.</li>
                  <li>Savings are estimates; measure them after activation (Decision Lab → Measurement).</li>
                </ul>
              </section>
              <div className="flex items-start justify-between gap-3 rounded-md bg-muted/60 p-3">
                <div>
                  <Label htmlFor="holdout">Keep a 10% holdout group</Label>
                  <p className="text-xs text-muted-foreground">
                    Sends a fixed 10% of eligible questions to Anthropic anyway, so savings can be measured against a
                    control group. Slightly reduces savings.
                  </p>
                </div>
                <Switch id="holdout" checked={holdout} onCheckedChange={setHoldout} />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
              {approve.isPending && <Loader2 className="size-4 animate-spin" />} Approve & enable
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
