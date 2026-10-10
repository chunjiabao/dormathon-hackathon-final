import { formatMYR, formatPct } from "@/lib/format";
import type { DriverRow } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Horizontal share bars for forecast cost drivers (attribution of the forecast, not causation). */
export function DriverBreakdown({ rows, showIncrement = true }: { rows: DriverRow[]; showIncrement?: boolean }) {
  const max = Math.max(...rows.map((r) => r.predicted_remaining_myr), 0.0001);
  return (
    <ul className="space-y-3" aria-label="Predicted remaining spend by category">
      {rows.map((r) => {
        const inc = r.increment_vs_run_rate_myr;
        return (
          <li key={`${r.application ?? ""}-${r.request_category}`} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span className="font-medium">{r.label}</span>
              <span className="tabular text-muted-foreground">
                <span className="font-semibold text-foreground">{formatMYR(r.predicted_remaining_myr)}</span> ·{" "}
                {formatPct(r.share)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", r.request_category === "static_faq" ? "bg-primary" : "bg-foreground/60")}
                style={{ width: `${(r.predicted_remaining_myr / max) * 100}%` }}
              />
            </div>
            {showIncrement && (
              <p className="tabular text-xs text-muted-foreground">
                {inc >= 0 ? "+" : "−"}
                {formatMYR(Math.abs(inc))} vs recent 14-day run rate ({formatMYR(r.recent_run_rate_reference_myr)})
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
