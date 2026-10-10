"use client";

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDay, formatMYR } from "@/lib/format";
import type { Forecast } from "@/lib/types";

const C = {
  actual: "var(--chart-actual)",
  forecast: "var(--chart-forecast)",
  band: "var(--chart-band)",
  budget: "var(--chart-budget)",
  scenario: "var(--chart-scenario)",
};

const axis = { fontSize: 11, fill: "#71717a" };

type Row = {
  day: string;
  actual?: number;
  forecast?: number;
  band?: [number, number];
  scenario?: number;
};

function TooltipBox({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number | number[]; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-[var(--shadow-soft)]">
      <p className="mb-1 font-medium">{formatDay(label)}</p>
      {payload.map((p) => (
        <p key={p.name} className="tabular flex justify-between gap-4">
          <span style={{ color: p.color }}>{p.name}</span>
          <span>
            {Array.isArray(p.value) ? `${formatMYR(p.value[0])} – ${formatMYR(p.value[1])}` : formatMYR(p.value)}
          </span>
        </p>
      ))}
    </div>
  );
}

/**
 * Cumulative month-to-date actual vs forecast. The band is the run's calibrated month-end interval,
 * scaled in proportion to the cumulative forecast (zero width at the last observed day).
 */
export function CumulativeChart({
  forecast,
  scenarioNetSavings,
  height = 280,
}: {
  forecast: Forecast;
  scenarioNetSavings?: number;
  height?: number;
}) {
  const series = (forecast.series ?? []).filter((r) => r.kind === "actual" || r.in_month !== false);
  const remaining = forecast.predicted_remaining_myr || 1;
  const qLow = (forecast.forecast_total_myr - forecast.lower_myr) / remaining;
  const qHigh = (forecast.upper_myr - forecast.forecast_total_myr) / remaining;
  let cum = 0;
  let cumF = 0;
  const rows: Row[] = [];
  for (const r of series) {
    if (r.kind === "actual") {
      cum += r.cost_myr;
      rows.push({ day: r.day, actual: round(cum) });
    } else {
      if (cumF === 0 && rows.length) {
        const last = rows[rows.length - 1];
        last.forecast = last.actual;
        last.band = [last.actual!, last.actual!];
        if (scenarioNetSavings !== undefined) last.scenario = last.actual;
      }
      cumF += r.cost_myr;
      const row: Row = {
        day: r.day,
        forecast: round(cum + cumF),
        band: [round(cum + cumF * (1 - qLow)), round(cum + cumF * (1 + qHigh))],
      };
      if (scenarioNetSavings !== undefined) row.scenario = round(cum + cumF - scenarioNetSavings * (cumF / remaining));
      rows.push(row);
    }
  }
  return (
    <figure aria-label="Cumulative spend: actual versus forecast, with budget line">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#ececea" vertical={false} />
          <XAxis dataKey="day" tick={axis} tickFormatter={(d) => formatDay(d, false)} minTickGap={24} />
          <YAxis tick={axis} width={58} tickFormatter={(v) => `RM${v}`} />
          <Tooltip content={<TooltipBox />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area dataKey="band" name="Forecast interval" fill={C.band} stroke="none" fillOpacity={0.55} isAnimationActive={false} />
          <Line dataKey="actual" name="Actual (cumulative)" stroke={C.actual} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="forecast" name="Forecast (cumulative)" stroke={C.forecast} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          {scenarioNetSavings !== undefined && (
            <Line dataKey="scenario" name="With FAQ caching (simulated)" stroke={C.scenario} strokeWidth={2} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
          )}
          <ReferenceLine y={forecast.budget_myr} stroke={C.budget} strokeDasharray="4 3"
            label={{ value: `Budget ${formatMYR(forecast.budget_myr)}`, position: "insideTopLeft", fontSize: 11, fill: "#b45309" }} />
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="mt-1 text-xs text-muted-foreground">
        MYR, cumulative for the calendar month. Shaded: {Math.round((forecast.metrics.interval_quantiles?.level ?? 0.9) * 100)}%
        empirical month-end interval interpolated across forecast days; it may under-cover when usage shifts.
        {scenarioNetSavings !== undefined && " The caching curve distributes month-end net savings in proportion to forecast spend; it is an illustration of the monthly estimate."}
      </figcaption>
    </figure>
  );
}

/** Daily actual cost bars + daily forecast line with its interval. */
export function DailyChart({ forecast, height = 260 }: { forecast: Forecast; height?: number }) {
  const rows: Row[] = (forecast.series ?? []).map((r) =>
    r.kind === "actual"
      ? { day: r.day, actual: round(r.cost_myr) }
      : { day: r.day, forecast: round(r.cost_myr), band: [round(r.lower_myr ?? 0), round(r.upper_myr ?? 0)] },
  );
  return (
    <figure aria-label="Daily cost: actual and forecast">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#ececea" vertical={false} />
          <XAxis dataKey="day" tick={axis} tickFormatter={(d) => formatDay(d, false)} minTickGap={24} />
          <YAxis tick={axis} width={52} tickFormatter={(v) => `RM${v}`} />
          <Tooltip content={<TooltipBox />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area dataKey="band" name="Daily interval" fill={C.band} stroke="none" fillOpacity={0.55} isAnimationActive={false} />
          <Bar dataKey="actual" name="Actual daily cost" fill={C.actual} radius={[3, 3, 0, 0]} maxBarSize={16} isAnimationActive={false} />
          <Line dataKey="forecast" name="Forecast daily cost" stroke={C.forecast} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="mt-1 text-xs text-muted-foreground">MYR per day. Bars are observed; the line is forecast.</figcaption>
    </figure>
  );
}

function round(v: number) {
  return Math.round(v * 100) / 100;
}
