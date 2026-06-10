"use client";

import { useState } from "react";
import { Send, Check, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

export function SendToKindle({ bookId }: { bookId: number }) {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const send = async () => {
    setState("sending"); setMsg(null);
    try {
      const r = await api.sendToKindle(bookId);
      setState("sent");
      setMsg(`Sent to ${r.sent_to}`);
      setTimeout(() => { setState("idle"); setMsg(null); }, 4000);
    } catch (e: any) {
      setState("idle");
      setMsg(e.message ?? "Send failed");
      setTimeout(() => setMsg(null), 6000);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      <button onClick={send} disabled={state === "sending"}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold-dim)] disabled:opacity-50"
        style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)",
                 borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
        {state === "sending" ? <Loader2 className="w-4 h-4 animate-spin" /> : state === "sent" ? <Check className="w-4 h-4" /> : <Send className="w-4 h-4" />}
        {state === "sent" ? "Sent" : "Send to Kindle"}
      </button>
      {msg && <span style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)" }}>{msg}</span>}
    </div>
  );
}
