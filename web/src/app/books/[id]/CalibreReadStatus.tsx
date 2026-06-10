"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { ReadHistory } from "@/components/ReadHistory";

/** Read/Unread + Date Read for a digital (Calibre) book. Stored in Bibliocapsa's
 *  own store; if an admin has mapped a Calibre Yes/No column it also queues an
 *  overlay edit that exports back to Calibre on the next Sync. Admins can edit;
 *  members see the status read-only. */
export function CalibreReadStatus({ bookId, status }:
  { bookId: number; status?: string | null }) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [st, setSt] = useState<string | null>(status ?? null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => { api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {}); }, []);

  const save = async (next: string | null) => {
    if (!isAdmin || busy) return;
    setBusy(true);
    try {
      await api.setCalibreReadStatus(bookId, { status: next });
      setSt(next);
      setRefresh(r => r + 1);  // a new Read may have auto-logged a date
    } finally { setBusy(false); }
  };

  // Member, unread → show nothing (keeps the page clean).
  if (!isAdmin && !st) return null;

  // Member, read/reading → compact read-only badge + their own read history.
  if (!isAdmin) {
    const label = st === "read" ? "Read" : "Reading";
    return (
      <div className="mb-4">
        <div style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>{label}</div>
        {st === "read" && <div className="mt-2"><ReadHistory source="calibre" bookId={bookId} refreshKey={refresh} /></div>}
      </div>
    );
  }

  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {([["", "Unread"], ["reading", "Reading"], ["read", "Read"]] as const).map(([val, label]) => {
          const active = (st ?? "") === val;
          return (
            <button key={label} disabled={busy}
              onClick={() => save(val || null)}
              className="px-3 py-1.5 rounded-sm border transition-colors"
              style={{ fontFamily: "var(--mono)", fontSize: "0.72rem",
                       color: active ? "var(--gold-light)" : "var(--parchment-dim)",
                       borderColor: active ? "var(--gold)" : "var(--ink-muted)",
                       background: active ? "rgba(107,78,30,0.2)" : "transparent" }}>
              {label}
            </button>
          );
        })}
      </div>
      {st === "read" && <ReadHistory source="calibre" bookId={bookId} refreshKey={refresh} />}
    </div>
  );
}
