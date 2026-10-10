import { Info } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function MetricCard({
  label,
  value,
  sub,
  help,
  tone = "default",
  badge,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  help?: string;
  tone?: "default" | "warning" | "danger" | "success";
  badge?: React.ReactNode;
}) {
  return (
    <Card className="gap-0 py-0 shadow-[var(--shadow-soft)]">
      <CardContent className="space-y-1.5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="eyebrow flex items-center gap-1">
            {label}
            {help && (
              <Tooltip>
                <TooltipTrigger aria-label={`About ${label}`} className="text-muted-foreground hover:text-foreground">
                  <Info className="size-3.5" />
                </TooltipTrigger>
                <TooltipContent className="max-w-72">{help}</TooltipContent>
              </Tooltip>
            )}
          </span>
          {badge}
        </div>
        <div
          className={cn(
            "tabular text-[26px] font-bold leading-tight tracking-tight",
            tone === "warning" && "text-warning",
            tone === "danger" && "text-danger",
            tone === "success" && "text-success",
          )}
        >
          {value}
        </div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}
