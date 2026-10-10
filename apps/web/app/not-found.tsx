import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-6">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link href="/overview" className="text-accent underline">
        Back to Overview
      </Link>
    </main>
  );
}
