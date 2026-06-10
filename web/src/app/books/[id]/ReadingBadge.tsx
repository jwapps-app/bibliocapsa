"use client";

import { useEffect, useState } from "react";
import { BookOpen, X, Loader2 } from "lucide-react";

/** Shows "Currently reading · NN%" if the signed-in user has KOReader progress
 *  for this book (synced via KOSync). Renders nothing otherwise. Includes a
 *  "mark unread" action that clears the progress. */
export function ReadingBadge({ bookId }: { bookId: number }) {
  const [pct, setPct] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    fetch("/api/reading/current")
      .then(r => (r.ok ? r.json() : []))
      .then((rows: any[]) => {
        const hit = rows.find(b => b.book_id === bookId && b.book_source === "calibre");
        if (hit && hit.percentage != null) setPct(hit.percentage);
      })
      .catch(() => {});
  }, [bookId]);

  const reset = async () => {
    if (!confirm("Remove this book from Currently Reading and reset its progress to unread?")) return;
    setBusy(true);
    try {
      await fetch(`/api/reading/book/${bookId}`, { method: "DELETE" });
      setDone(true);
    } finally { setBusy(false); }
  };

  if (done || pct == null) return null;
  const p = Math.min(100, Math.round(pct * 100));

  return (
    <div className="mb-4" style={{ maxWidth: "20rem" }}>
      <div className="flex items-center gap-2 px-3 py-2 rounded-sm"
           style={{ background: "rgba(107,78,30,0.18)", border: "1px solid var(--gold-dim)" }}>
        <BookOpen className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--gold-light)" }} />
        <div className="flex-1 min-w-0">
          <div style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--gold-light)" }}>
            Currently reading · {p}%
          </div>
          <div className="mt-1 rounded-full" style={{ height: "3px", background: "var(--ink-muted)" }}>
            <div className="rounded-full" style={{ height: "3px", width: `${p}%`, background: "var(--gold)" }} />
          </div>
        </div>
      </div>
      <button onClick={reset} disabled={busy}
        className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm border transition-colors hover:border-[var(--parchment-dim)]"
        style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)" }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />} Mark as unread / reset
      </button>
    </div>
  );
}
