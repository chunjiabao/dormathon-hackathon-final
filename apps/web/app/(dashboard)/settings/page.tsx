"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Loader2, RefreshCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { DataSourceBadge } from "@/components/data-source-badge";
import { OwnerButton } from "@/components/owner-button";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { ErrorState, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ApiError, api } from "@/lib/api";
import { appLabel, formatMYR } from "@/lib/format";
import { useHealth, usePolicies, useRole, useSettings } from "@/lib/queries";
import type { Policy } from "@/lib/types";

function errToast(e: unknown) {
  toast.error(e instanceof ApiError ? e.message : "Request failed");
}

function Confirm({ open, onOpenChange, title, body, confirm, onConfirm, busy, destructive }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; body: string; confirm: string;
  onConfirm: () => void; busy: boolean; destructive?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{body}</DialogDescription></DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={destructive ? "destructive" : "default"} onClick={onConfirm} disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />} {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PolicyEditor({ p }: { p: Policy }) {
  const qc = useQueryClient();
  const { isOwner } = useRole();
  const [threshold, setThreshold] = useState(p.similarity_threshold);
  const [ttl, setTtl] = useState(String(p.ttl_hours));
  useEffect(() => { setThreshold(p.similarity_threshold); setTtl(String(p.ttl_hours)); }, [p]);
  const save = useMutation({
    mutationFn: (body: Parameters<typeof api.patchPolicy>[1]) => api.patchPolicy(p.id, body),
    onSuccess: () => { toast.success(`${appLabel(p.application)} policy updated (audited)`); qc.invalidateQueries(); },
    onError: errToast,
  });
  const ttlNum = Number(ttl);
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{appLabel(p.application)}</span>
        <Badge variant={p.enabled ? "default" : "outline"}>{p.enabled ? "Enabled" : "Off (enable via Decision Lab approval)"}</Badge>
      </div>
      <div className="space-y-1.5">
        <div className="flex justify-between text-[13px]"><Label htmlFor={`thr-${p.id}`}>Similarity threshold</Label><span className="tabular font-semibold">{threshold.toFixed(2)}</span></div>
        <Slider id={`thr-${p.id}`} min={0.95} max={0.99} step={0.01} value={[threshold]} disabled={!isOwner}
          onValueChange={([v]) => setThreshold(v)} onValueCommit={([v]) => v !== p.similarity_threshold && save.mutate({ similarity_threshold: v })}
          aria-label="Similarity threshold" />
        <p className="text-xs text-muted-foreground">Safe range 0.95–0.99. Higher = fewer semantic hits, fewer risks. Changing it clears cached answers.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor={`ttl-${p.id}`} className="text-[13px]">Cache TTL (hours)</Label>
          <Input id={`ttl-${p.id}`} type="number" min={1} max={168} className="w-28" value={ttl} disabled={!isOwner}
            onChange={(e) => setTtl(e.target.value)} />
        </div>
        <OwnerButton size="sm" variant="outline" disabled={save.isPending || ttlNum === p.ttl_hours || ttlNum < 1 || ttlNum > 168}
          onClick={() => save.mutate({ ttl_hours: ttlNum })}>Save TTL</OwnerButton>
        <div className="ml-auto flex items-center gap-2">
          <Label htmlFor={`ho-${p.id}`} className="text-[13px]">10% holdout</Label>
          <Switch id={`ho-${p.id}`} checked={p.holdout_enabled} disabled={!isOwner || save.isPending}
            onCheckedChange={(v) => save.mutate({ holdout_enabled: v })} />
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const qc = useQueryClient();
  const s = useSettings();
  const policies = usePolicies();
  const health = useHealth();
  const [budget, setBudget] = useState("");
  const [newKey, setNewKey] = useState<{ app: string; key: string } | null>(null);
  const [confirm, setConfirm] = useState<null | "faq" | "reset">(null);
  useEffect(() => { if (s.data) setBudget(String(s.data.monthly_budget_myr)); }, [s.data]);

  const saveBudget = useMutation({
    mutationFn: () => api.patchSettings({ monthly_budget_myr: Number(budget) }),
    onSuccess: () => { toast.success("Budget saved. Re-run the forecast to update risk."); qc.invalidateQueries(); },
    onError: errToast,
  });
  const rotate = useMutation({
    mutationFn: (appId: string) => api.rotateKey(appId),
    onSuccess: (r) => {
      setNewKey({ app: s.data?.applications.find((a) => a.id === r.application_id)?.name ?? "", key: r.api_key });
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: errToast,
  });
  const faq = useMutation({
    mutationFn: api.invalidateFaq,
    onSuccess: (r) => { toast.success(`Knowledge version is now ${r.knowledge_version}; cached answers invalidated.`); setConfirm(null); qc.invalidateQueries(); },
    onError: errToast,
  });
  const reset = useMutation({
    mutationFn: api.demoReset,
    onSuccess: () => { toast.success("Demo operational data cleared (audit log kept)."); setConfirm(null); qc.invalidateQueries(); },
    onError: errToast,
  });

  if (s.isLoading) return <LoadingBlock rows={4} />;
  if (s.isError) return <ErrorState error={s.error} onRetry={() => s.refetch()} />;
  const d = s.data!;
  const budgetNum = Number(budget);
  const budgetValid = budget !== "" && budgetNum >= 0 && budgetNum <= 1_000_000;

  return (
    <>
      <PageHeader title="Settings" description={`${d.name} · you are ${d.role === "owner" ? "the owner" : "a viewer (read-only)"}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent className="space-y-4">
            <SectionTitle>Budget & currency</SectionTitle>
            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-1">
                <Label htmlFor="budget">Monthly budget (MYR)</Label>
                <Input id="budget" type="number" min={0} step="1" value={budget} onChange={(e) => setBudget(e.target.value)} disabled={d.role !== "owner"} />
              </div>
              <OwnerButton onClick={() => saveBudget.mutate()} disabled={!budgetValid || budgetNum === d.monthly_budget_myr || saveBudget.isPending}>Save</OwnerButton>
            </div>
            <div className="space-y-1">
              <Label htmlFor="currency">Display currency</Label>
              <Select value="MYR" disabled>
                <SelectTrigger id="currency" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="MYR">MYR (Malaysian ringgit)</SelectItem></SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Only MYR is supported in this MVP. Provider prices are in USD and converted at a fixed demo rate of{" "}
                {d.fx_myr_per_usd_demo} MYR/USD (not a live rate). Pricing catalog {d.pricing_catalog_version}.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent className="space-y-3">
            <SectionTitle>Data sources</SectionTitle>
            <ul className="space-y-2 text-[13px]">
              <li className="flex items-center justify-between"><span className="flex items-center gap-2"><DataSourceBadge origin="synthetic" /> Seeded history</span><span className="tabular">{d.data_sources.synthetic_days} days</span></li>
              <li className="flex items-center justify-between"><span className="flex items-center gap-2"><DataSourceBadge origin="real" /> Gateway requests</span><span className="tabular">{d.data_sources.real_requests}</span></li>
              <li className="flex items-center justify-between"><span className="flex items-center gap-2"><DataSourceBadge origin={d.provider_mode === "mock" ? "mock" : "live"} /> Provider mode</span><span>{d.provider_mode}</span></li>
            </ul>
            <p className="text-xs text-muted-foreground">
              Synthetic and live data are never presented as equivalent evidence: every chart and metric carries one of these labels.
            </p>
            <div className="border-t pt-3">
              <p className="eyebrow mb-2">Demo data</p>
              {health.data?.demo_mode ? (
                <OwnerButton variant="destructive" size="sm" onClick={() => setConfirm("reset")}>
                  <Trash2 className="size-3.5" /> Delete demo operational data
                </OwnerButton>
              ) : (
                <Button variant="destructive" size="sm" disabled title="Only available in local/dev demo mode.">
                  <Trash2 className="size-3.5" /> Delete demo data (dev only)
                </Button>
              )}
              <p className="mt-1 text-xs text-muted-foreground">Clears usage, forecasts, anomalies and recommendations; the audit log is immutable and kept. Available only with DEMO_MODE=true.</p>
            </div>
          </CardContent>
        </Card>

        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent className="space-y-3">
            <SectionTitle>Applications & integration</SectionTitle>
            <ul className="divide-y text-[13px]">
              {d.applications.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 py-2.5">
                  <span>
                    <span className="font-medium">{appLabel(a.name)}</span>
                    <span className="ml-2 font-mono text-[11px] text-muted-foreground">{a.id.slice(0, 8)}…</span>
                    <span className="ml-2 text-xs text-muted-foreground">{a.has_api_key ? "API key set" : "no API key"}</span>
                  </span>
                  <OwnerButton size="sm" variant="outline" onClick={() => rotate.mutate(a.id)} disabled={rotate.isPending}>
                    <KeyRound className="size-3.5" /> {a.has_api_key ? "Rotate key" : "Create key"}
                  </OwnerButton>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Send <code>POST /api/v1/chat</code> with header <code>X-App-Key</code>. Keys are hashed; the full key is shown once.
              Your Anthropic key stays on the TokenGuard server and is never sent to browsers.
            </p>
          </CardContent>
        </Card>

        <Card className="py-5 shadow-[var(--shadow-soft)]">
          <CardContent className="space-y-3">
            <SectionTitle aside={<Badge variant="secondary">FAQ version {d.knowledge_version}</Badge>}>Safe cache policy</SectionTitle>
            {policies.isLoading && <LoadingBlock rows={1} />}
            {policies.isError && <ErrorState error={policies.error} onRetry={() => policies.refetch()} />}
            {policies.data?.items.map((p) => <PolicyEditor key={p.id} p={p} />)}
            <OwnerButton variant="outline" size="sm" onClick={() => setConfirm("faq")}>
              <RefreshCcw className="size-3.5" /> Invalidate cached answers (new FAQ version)
            </OwnerButton>
          </CardContent>
        </Card>
      </div>

      <Dialog open={newKey !== null} onOpenChange={(o) => !o && setNewKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New API key for {appLabel(newKey?.app)}</DialogTitle>
            <DialogDescription>Copy it now. It will not be shown again; only a hash is stored. The previous key no longer works.</DialogDescription>
          </DialogHeader>
          <div className="flex gap-2">
            <Input readOnly value={newKey?.key ?? ""} className="font-mono text-xs" aria-label="New API key" />
            <Button variant="outline" size="icon" aria-label="Copy key"
              onClick={() => { navigator.clipboard.writeText(newKey?.key ?? ""); toast.success("Copied"); }}>
              <Copy className="size-4" />
            </Button>
          </div>
          <DialogFooter><Button onClick={() => setNewKey(null)}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Confirm open={confirm === "faq"} onOpenChange={(o) => !o && setConfirm(null)} title="Invalidate cached answers?"
        body="This bumps the knowledge version. Cached answers stop matching immediately and every question goes to Anthropic until FAQ entries are re-approved for the new version."
        confirm="Invalidate" busy={faq.isPending} onConfirm={() => faq.mutate()} />
      <Confirm open={confirm === "reset"} onOpenChange={(o) => !o && setConfirm(null)} title="Delete demo operational data?"
        body={`Clears usage history, forecasts, anomalies, scenarios and recommendations for this workspace and disables cache policies. The audit log is kept. Budget ${formatMYR(d.monthly_budget_myr)} is unchanged.`}
        confirm="Delete demo data" destructive busy={reset.isPending} onConfirm={() => reset.mutate()} />
    </>
  );
}
