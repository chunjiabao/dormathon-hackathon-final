"use client";

import { Cake, Loader2, Send, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { formatMYR, titleCase } from "@/lib/format";
import type { ChatResponse, ChatSession } from "@/lib/types";
import { cn } from "@/lib/utils";

type Msg = { role: "user" | "bot"; text: string; meta?: ChatResponse; error?: string };

const SAMPLES = [
  "What time do you open?",
  "When are you open?",
  "Do you deliver?",
  "Are you open on Sunday?",
  "How much is Chocolate Cake?",
  "Is my order ready?",
  "Can I order a cake for 50 people?",
];

const PILL: Record<ChatResponse["cache_status"], { label: string; cls: string }> = {
  exact_hit: { label: "Safe cache hit · no Anthropic call", cls: "bg-success/10 text-success border-success/30" },
  semantic_hit: { label: "Safe semantic hit · no Anthropic call", cls: "bg-success/10 text-success border-success/30" },
  miss: { label: "Anthropic call", cls: "bg-accent text-accent-foreground border-primary/25" },
  bypass: { label: "Cache bypassed (unsafe to reuse) · Anthropic call", cls: "bg-warning/10 text-warning border-warning/30" },
  error: { label: "Error", cls: "bg-danger/10 text-danger border-danger/30" },
};

function Meta({ m }: { m: ChatResponse }) {
  const pill = PILL[m.cache_status];
  const label = m.provider_mode === "mock" ? pill.label.replace(/Anthropic call/g, "Mock response") : pill.label;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground" data-testid="chat-meta">
      <span className={cn("rounded-full border px-2 py-0.5 font-semibold", pill.cls)}>{label}</span>
      {m.provider_mode === "mock" && <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-warning">mock provider</span>}
      <span className="tabular">{m.usage.input_tokens + m.usage.output_tokens} tokens · {formatMYR(m.estimated_cost_myr, true)}</span>
      {m.cache_decision && <span title="Safe-cache gate decision">{titleCase(m.cache_decision.replace(/^shadow_/, "shadow: "))}</span>}
      {m.similarity !== null && m.cache_status === "semantic_hit" && <span>similarity {m.similarity.toFixed(3)}</span>}
    </div>
  );
}

export function DemoChat() {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  async function newSession() {
    try {
      const s = await api.chatSession();
      setSession(s);
      setSessionError(null);
      return s;
    } catch (e) {
      setSessionError(e instanceof ApiError ? e.message : "Could not start a chat session.");
      return null;
    }
  }
  useEffect(() => { newSession(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages]);

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setBusy(true);
    try {
      let s = session ?? (await newSession());
      if (!s) throw new ApiError(0, "no_session", "Chat is unavailable right now.");
      let res: ChatResponse;
      try {
        res = await api.chat(s.token, s.application_id, msg);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) throw e;
        s = await newSession(); // token expired: renew once
        if (!s) throw e;
        res = await api.chat(s.token, s.application_id, msg);
      }
      setMessages((m) => [...m, { role: "bot", text: res.reply, meta: res }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "bot", text: "", error: e instanceof ApiError ? e.message : "Something went wrong." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="overflow-hidden py-0 shadow-[var(--shadow-soft)]">
      <CardHeader className="flex flex-row items-center gap-3 border-b bg-[#fff7ed] py-4">
        <span className="grid size-10 place-items-center rounded-full bg-[#dd5b00] text-white"><Cake className="size-5" aria-hidden /></span>
        <div>
          <p className="font-bold">Sweet Crumbs Bakery</p>
          <p className="text-xs text-muted-foreground">BakeryBot · fictitious demo business · Mon–Sat 10:00–18:00</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        {sessionError && (
          <div role="alert" className="space-y-2 rounded-md bg-danger/10 p-3 text-sm text-danger">
            <p>{sessionError}</p>
            <Button variant="outline" size="sm" onClick={() => newSession()}>Retry chat connection</Button>
          </div>
        )}
        <div className="min-h-64 space-y-4" aria-live="polite">
          {messages.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">Ask about opening hours, delivery or cakes, or try a question that must not be cached.</p>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-sm break-words bg-primary px-3.5 py-2 text-[14px] text-primary-foreground">{m.text}</p>
              </div>
            ) : (
              <div key={i} className="max-w-[85%]">
                {m.error ? (
                  <p className="rounded-2xl rounded-bl-sm bg-danger/10 px-3.5 py-2 text-[14px] text-danger">{m.error}</p>
                ) : (
                  <p className="rounded-2xl rounded-bl-sm break-words bg-muted px-3.5 py-2 text-[14px] leading-relaxed">{m.text}</p>
                )}
                {m.meta && <Meta m={m.meta} />}
              </div>
            ),
          )}
          {busy && <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> BakeryBot is typing…</p>}
          <div ref={endRef} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {SAMPLES.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy || !session}
              className="rounded-full border bg-card px-3 py-1 text-xs hover:bg-accent disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <Input value={input} onChange={(e) => setInput(e.target.value)} maxLength={1000} placeholder="Type a question…" aria-label="Message" disabled={!session} />
          <Button type="submit" disabled={busy || !input.trim() || !session} aria-label="Send"><Send className="size-4" /></Button>
        </form>
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Zap className="size-3" /> The grey line under each answer is TokenGuard telemetry for the demo, not part of the customer reply.
          No payment details are collected; orders are handled by staff.
        </p>
      </CardContent>
    </Card>
  );
}
