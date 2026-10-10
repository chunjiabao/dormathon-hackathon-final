"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { useMe } from "@/lib/queries";
import { AppSidebar } from "./app-sidebar";
import { ErrorState, LoadingBlock } from "./states";
import { Topbar } from "./topbar";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [hasToken, setHasToken] = useState<boolean | null>(null);
  const me = useMe();

  useEffect(() => {
    getAccessToken().then((t) => {
      setHasToken(Boolean(t));
      if (!t) router.replace("/login");
    });
  }, [router]);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);

  if (hasToken === null || (hasToken && me.isLoading)) {
    return (
      <div className="mx-auto max-w-6xl p-8">
        <LoadingBlock rows={4} />
      </div>
    );
  }
  if (!hasToken) return null;

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r bg-[#f6f5f4] md:block">
        <div className="sticky top-0 h-screen overflow-y-auto">
          <AppSidebar />
        </div>
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-64 bg-[#f6f5f4] p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <AppSidebar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setOpen(true)} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8">
          {me.isError && !(me.error instanceof ApiError && me.error.status === 401) ? (
            <ErrorState error={me.error} onRetry={() => me.refetch()} />
          ) : me.data && me.data.memberships.length === 0 ? (
            <ErrorState error={new ApiError(403, "no_workspace", "Your account is not a member of any workspace.")} />
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
