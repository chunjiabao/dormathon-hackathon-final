"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { devLoginAvailable, signInDev, signInWithPassword } from "@/lib/auth";
import { SUPABASE_ENABLED } from "@/lib/config";

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [demo, setDemo] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    devLoginAvailable().then(setDemo);
  }, []);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
      qc.clear();
      router.replace("/overview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm shadow-[var(--shadow-soft)]">
        <CardHeader>
          <span className="mb-2 grid size-9 place-items-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" aria-hidden />
          </span>
          <CardTitle className="text-xl">Sign in to TokenGuard</CardTitle>
          <CardDescription>Predict AI spend early and approve safe savings.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {SUPABASE_ENABLED && (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                run("password", () => signInWithPassword(email, password));
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" autoComplete="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" autoComplete="current-password" required value={password}
                  onChange={(e) => setPassword(e.target.value)} />
              </div>
              <Button type="submit" className="w-full" disabled={busy !== null}>
                {busy === "password" && <Loader2 className="size-4 animate-spin" />} Sign in
              </Button>
            </form>
          )}

          {SUPABASE_ENABLED && demo && <Separator />}

          {demo === null && !SUPABASE_ENABLED && <p className="text-sm text-muted-foreground">Checking API…</p>}
          {demo && (
            <div className="space-y-2">
              <p className="eyebrow">Local demo accounts</p>
              <Button className="w-full" onClick={() => run("owner", () => signInDev("owner"))} disabled={busy !== null}>
                {busy === "owner" && <Loader2 className="size-4 animate-spin" />} Continue as demo owner
              </Button>
              <Button variant="outline" className="w-full" onClick={() => run("viewer", () => signInDev("viewer"))}
                disabled={busy !== null}>
                {busy === "viewer" && <Loader2 className="size-4 animate-spin" />} Continue as viewer (read-only)
              </Button>
              <p className="text-xs text-muted-foreground">
                Demo sign-in only works while the API runs with DEMO_MODE=true; it is disabled in production.
              </p>
            </div>
          )}
          {demo === false && !SUPABASE_ENABLED && (
            <Alert>
              <AlertDescription>
                No sign-in method is available: the API is unreachable or demo mode is off, and Supabase Auth is not
                configured (NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY).
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
