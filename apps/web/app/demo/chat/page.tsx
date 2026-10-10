import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { DemoChat } from "@/components/demo-chat";

export const metadata = { title: "Sweet Crumbs BakeryBot · Demo" };

export default function DemoChatPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-6 md:py-10">
      <div className="flex items-center justify-between">
        <Link href="/overview" className="flex items-center gap-1 text-[13px] text-primary hover:underline">
          <ArrowLeft className="size-3.5" /> TokenGuard dashboard
        </Link>
      </div>
      <div role="note" className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-[13px] text-[#92400e]">
        <strong>Demo only.</strong> Sweet Crumbs Bakery is fictitious. Prices, hours and availability are illustrative; no
        real orders, payments or personal data are processed.
      </div>
      <DemoChat />
    </main>
  );
}
