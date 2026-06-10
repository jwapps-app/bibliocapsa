"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Clock } from "lucide-react";

const fmtH = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

/** KOReader reading sessions for this Calibre book (current user). Renders only
 *  when the user has stats for it. */
export function ReadingSessions({ bookId }: { bookId: number }) {
  const [data, setData] = useState<any>(null);

  useEffect(() => { api.bookStats(bookId).then(setData).catch(() => {}); }, [bookId]);

  if (!data?.found || !data.sessions?.length) return null;

  const pct = data.book_pages ? Math.min(100, Math.round((data.total_pages / data.book_pages) * 100)) : null;

  return (
    <div className="mb-6">
      <div className="uppercase tracking-widest mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
        Your reading
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 mb-3" style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment)" }}>
        <span><Clock className="w-3.5 h-3.5 inline mr-1" style={{ color: "var(--gold)" }} />{fmtH(data.total_seconds)} read</span>
        <span style={{ color: "var(--parchment-dim)" }}>{data.total_pages}{data.book_pages ? ` / ${data.book_pages}` : ""} pages{pct != null ? ` · ${pct}%` : ""}</span>
        <span style={{ color: "var(--parchment-dim)" }}>{data.sessions.length} sessions</span>
      </div>
      <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
        {data.sessions.slice(0, 40).map((s: any, i: number) => (
          <div key={i} className="flex items-center justify-between px-2.5 py-1.5 rounded-sm"
            style={{ background: "var(--ink-soft)", fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
            <span>{new Date(s.start * 1000).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}</span>
            <span><span style={{ color: "var(--gold-light)" }}>{fmtH(s.seconds)}</span> · {s.pages} pp</span>
          </div>
        ))}
      </div>
    </div>
  );
}
