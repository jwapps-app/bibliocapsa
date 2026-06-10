"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { Plus, X } from "lucide-react";

type Entry = { id: number; date_read: string | null; source: string | null; ts: number };

/** Per-user running list of read dates for a book (digital or physical).
 *  Add a date, adjust one (e.g. fix what KOReader missed), or delete it.
 *  Re-fetches whenever `refreshKey` changes (so the Read toggle can refresh it). */
export function ReadHistory({ source, bookId, refreshKey = 0 }:
  { source: "calibre" | "native"; bookId: number; refreshKey?: number }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.readHistory(source, bookId).then(e => { setEntries(e); setLoaded(true); }).catch(() => setLoaded(true));
  }, [source, bookId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const addToday = async () => {
    if (busy) return;
    setBusy(true);
    try { await api.addReadDate(source, bookId, new Date().toISOString().slice(0, 10)); load(); }
    finally { setBusy(false); }
  };
  const edit = async (id: number, date: string) => {
    setEntries(es => es.map(e => e.id === id ? { ...e, date_read: date } : e));  // optimistic
    await api.editReadDate(id, date || null);
  };
  const remove = async (id: number) => {
    setEntries(es => es.filter(e => e.id !== id));  // optimistic
    await api.deleteReadDate(id);
  };

  if (!loaded) return null;

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="uppercase tracking-widest" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
          Read history{entries.length > 1 ? ` · ${entries.length}×` : ""}
        </span>
        <button onClick={addToday} disabled={busy}
          className="inline-flex items-center gap-1 transition-colors hover:text-[var(--gold-light)]"
          style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)" }}
          title="Add a read date">
          <Plus className="w-3 h-3" /> add date
        </button>
      </div>

      {entries.length === 0 ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
          No read dates yet.
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {entries.map(e => (
            <div key={e.id} className="flex items-center gap-2">
              <input type="date" value={e.date_read ?? ""}
                onChange={ev => edit(e.id, ev.target.value)}
                className="px-1.5 py-1 rounded-sm"
                style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)", color: "var(--parchment)", fontFamily: "var(--mono)", fontSize: "0.68rem" }} />
              {e.source && e.source !== "manual" && (
                <span style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.45 }}>{e.source}</span>
              )}
              <button onClick={() => remove(e.id)} title="Remove this date"
                className="transition-colors hover:text-red-400"
                style={{ color: "var(--parchment-dim)", opacity: 0.5 }}>
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
