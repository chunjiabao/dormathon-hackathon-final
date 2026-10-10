"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, LogOut, Menu, RefreshCw, UserRound, Wallet } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut } from "@/lib/auth";
import { formatMYR } from "@/lib/format";
import { useMe, useSettings } from "@/lib/queries";

function currentPeriod(): string {
  return new Date().toLocaleDateString("en-MY", { month: "long", year: "numeric", timeZone: "Asia/Kuala_Lumpur" });
}

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const qc = useQueryClient();
  const fetching = useIsFetching();
  const router = useRouter();
  const me = useMe();
  const settings = useSettings();
  const m = me.data?.memberships[0];

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur md:px-8">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenu} aria-label="Open navigation">
        <Menu className="size-5" />
      </Button>
      <div className="hidden items-center gap-1.5 text-[13px] text-muted-foreground sm:flex">
        <CalendarDays className="size-4" aria-hidden />
        <span>Budget period: {currentPeriod()} (Asia/Kuala_Lumpur)</span>
      </div>
      <div className="ml-auto flex items-center gap-1.5">
        <span className="flex items-center gap-1.5 rounded-md border bg-card px-2.5 py-1 text-[13px]">
          <Wallet className="size-3.5 text-muted-foreground" aria-hidden />
          <span className="text-muted-foreground">Budget</span>
          <span className="tabular font-semibold">
            {settings.data ? formatMYR(settings.data.monthly_budget_myr) : "…"}
          </span>
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Refresh data"
          onClick={() => qc.invalidateQueries()}
          disabled={fetching > 0}
        >
          <RefreshCw className={fetching > 0 ? "size-4 animate-spin" : "size-4"} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="User menu">
              <UserRound className="size-4.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel className="font-normal">
              <p className="truncate text-sm font-medium">{me.data?.email ?? "Signed in"}</p>
              <p className="text-xs capitalize text-muted-foreground">
                {m ? `${m.role} · ${m.workspace_name}` : "No workspace"}
              </p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={async () => {
                await signOut();
                qc.clear();
                router.replace("/login");
              }}
            >
              <LogOut className="size-4" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
