"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { DataSourceBadge } from "@/components/data-source-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_ITEMS } from "@/lib/nav";
import { useHealth, useMe } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function AppSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const me = useMe();
  const health = useHealth();
  const ws = me.data?.memberships[0];
  const h = health.data;

  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-5 p-3">
      <div className="flex items-center gap-2 px-2 pt-2">
        <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
          <ShieldCheck className="size-4.5" aria-hidden />
        </span>
        <span className="text-[15px] font-bold tracking-tight">TokenGuard</span>
      </div>

      <Tooltip>
        <TooltipTrigger asChild>
          <div
            tabIndex={0}
            className="mx-1 flex cursor-default items-center justify-between rounded-md border bg-card px-2.5 py-2 text-left"
          >
            <span className="min-w-0">
              <span className="eyebrow block">Workspace</span>
              <span className="block truncate text-[13px] font-medium">{ws?.workspace_name ?? "…"}</span>
            </span>
            {ws && <span className="rounded-sm bg-muted px-1.5 py-0.5 text-[11px] capitalize">{ws.role}</span>}
          </div>
        </TooltipTrigger>
        <TooltipContent side="right">One workspace per account in this MVP.</TooltipContent>
      </Tooltip>

      <ul className="flex flex-1 flex-col gap-0.5">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex items-center gap-2.5 rounded-sm px-2.5 py-1.5 text-[13.5px] transition-colors",
                  active
                    ? "bg-accent font-medium text-accent-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-primary"
                    : "text-foreground/80 hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="space-y-2 border-t px-2 pt-3 text-xs" data-testid="provenance">
        <p className="eyebrow">Data provenance</p>
        <div className="flex flex-wrap gap-1">
          <DataSourceBadge origin="synthetic" />
          <DataSourceBadge origin="real" />
          <DataSourceBadge origin="forecast" />
        </div>
        <div className="space-y-0.5 pt-1 text-muted-foreground" data-testid="api-status">
          {health.isLoading && <p>Checking API…</p>}
          {health.isError && <p className="text-danger">API unreachable</p>}
          {h && (
            <>
              <p>
                API{" "}
                <span className={h.status === "ok" ? "text-success" : "text-warning"}>{h.status}</span> ·{" "}
                {h.environment}
              </p>
              <p>
                Anthropic:{" "}
                <span className={h.dependencies.anthropic.mode === "mock" ? "text-warning" : "text-success"}>
                  {h.dependencies.anthropic.mode === "mock" ? "mock mode" : "live"}
                </span>
              </p>
              <p>Embeddings: {h.dependencies.embeddings.semantic_matching}</p>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
