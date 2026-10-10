import fs from "node:fs/promises";
import path from "node:path";
import Link from "next/link";

export default async function ModelCardPage() {
  const card = await fs.readFile(path.resolve(process.cwd(), "../../docs/model_card.md"), "utf8");
  return (
    <main className="mx-auto max-w-4xl space-y-5 px-4 py-8 md:px-8">
      <Link href="/evaluation" className="text-sm text-primary hover:underline">← Back to Evaluation</Link>
      <h1 className="text-2xl font-semibold">Model card</h1>
      <pre className="whitespace-pre-wrap break-words rounded-lg border bg-card p-5 font-sans text-sm leading-relaxed">{card}</pre>
    </main>
  );
}
