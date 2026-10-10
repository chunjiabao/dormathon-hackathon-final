"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { API_BASE_URL, SUPABASE_ANON_KEY, SUPABASE_ENABLED, SUPABASE_URL } from "./config";

/**
 * TokenGuard browser auth. The frontend only ever holds a TokenGuard/Supabase *user* access token;
 * provider (Anthropic) keys never reach the browser.
 *  - Hosted: Supabase Auth (email + password); the backend verifies the JWT via JWKS.
 *  - Local demo: POST /auth/dev-login issues a short-lived dev token (disabled in production).
 */
const DEV_TOKEN_KEY = "tg_dev_token";
let supabase: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (!SUPABASE_ENABLED) return null;
  supabase ??= createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return supabase;
}

function readDevToken(): string | null {
  try {
    return window.localStorage.getItem(DEV_TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  const sb = getSupabase();
  if (sb) {
    const { data } = await sb.auth.getSession();
    if (data.session?.access_token) return data.session.access_token;
  }
  return readDevToken();
}

export async function signInDev(role: "owner" | "viewer"): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/dev-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) throw new Error(res.status === 404 ? "Demo sign-in is disabled in this environment." : "Sign-in failed.");
  const body = (await res.json()) as { access_token: string };
  window.localStorage.setItem(DEV_TOKEN_KEY, body.access_token);
}

export async function signInWithPassword(email: string, password: string): Promise<void> {
  const sb = getSupabase();
  if (!sb) throw new Error("Supabase Auth is not configured.");
  const { error } = await sb.auth.signInWithPassword({ email, password });
  if (error) throw new Error(error.message);
}

export async function signOut(): Promise<void> {
  try {
    window.localStorage.removeItem(DEV_TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
  await getSupabase()?.auth.signOut();
}

export async function devLoginAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/health`);
    const body = await res.json();
    return Boolean(body.demo_mode);
  } catch {
    return false;
  }
}
