"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowUpDown, Download } from "lucide-react";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataSourceBadge } from "@/components/data-source-badge";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { appLabel, calendarDaysAgo, categoryLabel, formatDateTime, formatDay, formatMYR, formatNum } from "@/lib/format";
import { useUsageDaily } from "@/lib/queries";
import type { RequestRow, UsageDailyRow } from "@/lib/types";

type Metric = "cost_myr" | "requests" | "tokens" | "cache_hits";
const METRICS: Record<Metric, { label: string; unit: string }> = {
  cost_myr: { label: "Estimated cost", unit: "MYR" },
  requests: { label: "Requests", unit: "requests" },
  tokens: { label: "Tokens (in + out)", unit: "tokens" },
  cache_hits: { label: "Cache hits", unit: "hits" },
};

function FilterSelect({ id, label, value, onChange, options }: {
  id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="eyebrow">{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent>
          {options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  );
}

function csvCell(value: unknown) {
  const text = String(value ?? "");
  const safe = /^[=+@\-\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '\"\"')}"`;
}

function toCsv(rows: UsageDailyRow[]) {
  const cols: (keyof UsageDailyRow)[] = ["day", "application", "request_category", "model", "data_origin", "requests",
    "input_tokens", "output_tokens", "cost_myr", "cache_hits", "retry_requests"];
  return [cols.join(","), ...rows.map((r) => cols.map((c) => csvCell(r[c])).join(","))].join("\n");
}

export default function UsagePage() {
  const [from, setFrom] = useState(() => calendarDaysAgo(60));
  const [to, setTo] = useState(() => calendarDaysAgo(0));
  const [origin, setOrigin] = useState("all");
  const [app, setApp] = useState("all");
  const [category, setCategory] = useState("all");
  const [model, setModel] = useState("all");
  const [metric, setMetric] = useState<Metric>("cost_myr");
  const [sortKey, setSortKey] = useState<keyof RequestRow>("occurred_at");
  const [sortAsc, setSortAsc] = useState(false);

  const daily = useUsageDaily({ from, to, data_origin: origin === "all" ? undefined : origin });
  const rows = useMemo(
    () => (daily.data?.items ?? []).filter((r) =>
      (app === "all" || r.application === app) && (category === "all" || r.request_category === category) &&
      (model === "all" || r.model === model)),
    [daily.data, app, category, model],
  );
  const models = useMemo(() => [...new Set((daily.data?.items ?? []).map((r) => r.model))].sort(), [daily.data]);
  const chart = useMemo(() => {
    const byDay = new Map<string, { day: string; synthetic: number; real: number }>();
    for (const r of rows) {
      const v = metric === "tokens" ? r.input_tokens + r.output_tokens : r[metric];
      const e = byDay.get(r.day) ?? { day: r.day, synthetic: 0, real: 0 };
      e[r.data_origin] += v;
      byDay.set(r.day, e);
    }
    return [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));
  }, [rows, metric]);
  const totals = useMemo(() => rows.reduce((t, r) => ({
    cost: t.cost + r.cost_myr, requests: t.requests + r.requests, tokens: t.tokens + r.input_tokens + r.output_tokens,
    hits: t.hits + r.cache_hits,
  }), { cost: 0, requests: 0, tokens: 0, hits: 0 }), [rows]);

  const requestFilters = {
    from, to,
    application: app === "all" ? undefined : app,
    model: model === "all" ? undefined : model,
    request_category: category === "all" ? undefined : category,
    data_origin: origin === "all" ? undefined : origin,
  };
  const requests = useInfiniteQuery({
    queryKey: ["usageRequests", requestFilters],
    queryFn: ({ pageParam }) => api.usageRequests(pageParam, requestFilters),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const reqRows = useMemo(() => {
    const all = requests.data?.pages.flatMap((p) => p.items) ?? [];
    return [...all].sort((a, b) => {
      const x = a[sortKey] ?? "";
      const y = b[sortKey] ?? "";
      return (x < y ? -1 : x > y ? 1 : 0) * (sortAsc ? 1 : -1);
    });
  }, [requests.data, sortKey, sortAsc]);

  function download() {
    const blob = new Blob([toCsv(rows)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tokenguard-usage-${from}-to-${to}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const SortHead = ({ k, label, right }: { k: keyof RequestRow; label: string; right?: boolean }) => (
    <TableHead className={right ? "text-right" : undefined}>
      <button className="eyebrow inline-flex items-center gap-1 hover:text-foreground"
        onClick={() => (sortKey === k ? setSortAsc(!sortAsc) : (setSortKey(k), setSortAsc(false)))}>
        {label} <ArrowUpDown className="size-3" />
      </button>
    </TableHead>
  );

  return (
    <>
      <PageHeader
        title="Usage Explorer"
        description="Daily tokens, cost, requests and cache hits, with every row labelled by origin. No prompts are stored or shown."
        actions={<Button variant="outline" onClick={download} disabled={!rows.length}><Download className="size-4" /> Export CSV (aggregates)</Button>}
      />
      <Card className="mb-4 py-4 shadow-[var(--shadow-soft)]">
        <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <div className="space-y-1">
            <Label htmlFor="from" className="eyebrow">From</Label>
            <Input id="from" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="to" className="eyebrow">To</Label>
            <Input id="to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </div>
          <FilterSelect id="origin" label="Origin" value={origin} onChange={setOrigin}
            options={[["all", "All origins"], ["synthetic", "Synthetic"], ["real", "Gateway traffic"]]} />
          <FilterSelect id="app" label="Application" value={app} onChange={setApp}
            options={[["all", "All apps"], ["bakery_demo", appLabel("bakery_demo")], ["tuition_demo", appLabel("tuition_demo")], ["retail_demo", appLabel("retail_demo")]]} />
          <FilterSelect id="category" label="Category" value={category} onChange={setCategory}
            options={[["all", "All categories"], ...["static_faq", "order_enquiry", "complex_support", "other"].map((c) => [c, categoryLabel(c)] as [string, string])]} />
          <FilterSelect id="model" label="Model" value={model} onChange={setModel}
            options={[["all", "All models"], ...models.map((m) => [m, m.replace("claude-", "")] as [string, string])]} />
          <FilterSelect id="metric" label="Chart metric" value={metric} onChange={(v) => setMetric(v as Metric)}
            options={Object.entries(METRICS).map(([k, v]) => [k, v.label] as [string, string])} />
        </CardContent>
      </Card>

      {daily.isLoading && <LoadingBlock rows={2} />}
      {daily.isError && <ErrorState error={daily.error} onRetry={() => daily.refetch()} />}
      {daily.data && (
        <Card className="mb-6 py-5 shadow-[var(--shadow-soft)]">
          <CardContent>
            <SectionTitle aside={<span className="tabular text-xs text-muted-foreground">
              {formatMYR(totals.cost)} · {formatNum(totals.requests)} requests · {formatNum(totals.tokens)} tokens · {formatNum(totals.hits)} cache hits
            </span>}>
              Daily {METRICS[metric].label.toLowerCase()} ({METRICS[metric].unit})
            </SectionTitle>
            {chart.length === 0 ? (
              <EmptyState title="No usage for these filters" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#ececea" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#71717a" }} tickFormatter={(d) => formatDay(d, false)} minTickGap={24} />
                  <YAxis tick={{ fontSize: 11, fill: "#71717a" }} width={56}
                    tickFormatter={(v) => (metric === "cost_myr" ? `RM${v}` : formatNum(v))} />
                  <Tooltip formatter={(v: number, n: string) => [metric === "cost_myr" ? formatMYR(v) : formatNum(v), n]}
                    labelFormatter={(d) => formatDay(String(d))} contentStyle={{ fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="synthetic" name="Synthetic" stackId="o" fill="#d6c7a8" isAnimationActive={false} />
                  <Bar dataKey="real" name="Gateway traffic" stackId="o" fill="var(--chart-forecast)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="py-5 shadow-[var(--shadow-soft)]">
        <CardContent>
          <p className="mb-3 text-xs text-muted-foreground">Filters apply to both charts and requests. Sorting applies to loaded requests; load more to include older rows. Gateway traffic may use the mock provider.</p>
          <SectionTitle aside={<span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {reqRows.length} loaded of {requests.data?.pages[0]?.total ?? 0} matching <DataSourceBadge origin="real" />
          </span>}>
            Gateway requests (metadata only)
          </SectionTitle>
          {requests.isLoading && <LoadingBlock rows={3} />}
          {requests.isError && <ErrorState error={requests.error} onRetry={() => requests.refetch()} />}
          {requests.data && reqRows.length === 0 && (
            <EmptyState title="No gateway requests for these filters">Adjust the filters or use the Demo Chatbot to send traffic.</EmptyState>
          )}
          {reqRows.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortHead k="occurred_at" label="Time" />
                    <SortHead k="application" label="App" />
                    <SortHead k="request_category" label="Category" />
                    <SortHead k="cache_status" label="Cache" />
                    <SortHead k="model" label="Model / provider" />
                    <SortHead k="input_tokens" label="Input tokens" right />
                    <SortHead k="estimated_cost_myr" label="Cost" right />
                    <SortHead k="latency_ms" label="Latency" right />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reqRows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="whitespace-nowrap text-xs">{formatDateTime(r.occurred_at)}</TableCell>
                      <TableCell className="text-[13px]">{appLabel(r.application)}</TableCell>
                      <TableCell className="text-[13px]">{categoryLabel(r.request_category)}</TableCell>
                      <TableCell>
                        <Badge variant={r.cache_status.endsWith("hit") ? "default" : r.cache_status === "error" ? "destructive" : "secondary"}>
                          {r.cache_status.replace("_", " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">
                        {r.provider === "tokenguard-cache" ? "approved FAQ" : r.model.replace("claude-", "")}
                        {r.provider_mode === "mock" && r.provider !== "tokenguard-cache" && <span className="ml-1 text-warning">(mock)</span>}
                      </TableCell>
                      <TableCell className="tabular text-right text-[13px]">{formatNum(r.input_tokens)} in / {formatNum(r.output_tokens)} out</TableCell>
                      <TableCell className="tabular text-right text-[13px]">{formatMYR(r.estimated_cost_myr, true)}</TableCell>
                      <TableCell className="tabular text-right text-[13px]">{r.latency_ms} ms</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {requests.hasNextPage && (
            <Button variant="outline" size="sm" className="mt-3" onClick={() => requests.fetchNextPage()} disabled={requests.isFetchingNextPage}>
              Load more
            </Button>
          )}
        </CardContent>
      </Card>
    </>
  );
}
