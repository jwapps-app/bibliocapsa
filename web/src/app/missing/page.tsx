"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, ChevronRight, SearchX, Sparkles, XCircle } from "lucide-react";

const FIELDS = [
  ["description", "Description"],
  ["pubdate", "Published date"],
  ["series", "Series"],
  ["publisher", "Publisher"],
  ["isbn", "ISBN"],
  ["tags", "Tags"],
] as const;

export default function MissingPage() {
  const [field, setField] = useState("description");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; items: { id: number; title: string; author: string }[] }>({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);

  const [job, setJob] = useState<any>(null);
  const poll = useRef<any>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.missingBooks(field, page).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [field, page]);
  useEffect(() => { load(); }, [load]);

  // Track the bulk job (resume polling if one is already running).
  const refreshJob = useCallback(async () => {
    const s = await api.enrichStatus();
    setJob(s);
    if (s && !s.running && poll.current) { clearInterval(poll.current); poll.current = null; load(); }
  }, [load]);
  useEffect(() => {
    refreshJob();
    return () => { if (poll.current) clearInterval(poll.current); };
  }, [refreshJob]);

  const startJob = async (force = false) => {
    try {
      await api.startEnrich(force);
      poll.current = setInterval(refreshJob, 2000);
      refreshJob();
    } catch (e) { /* already running */ refreshJob(); }
  };
  const cancelJob = async () => { await api.cancelEnrich(); refreshJob(); };

  const pages = Math.ceil(data.total / 50) || 1;
  const running = job?.running;

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <a href="/" className="inline-flex items-center gap-2 mb-6 hover:underline"
           style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }} className="mb-1">Missing metadata</h1>
        <p style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.75 }} className="mb-5">
          Digital books missing a field. Open one and use <em>Find missing metadata</em> to look it up and queue the fill for Sync.
        </p>

        {/* Auto-fill (bulk) */}
        <div className="rounded-sm p-4 mb-5 border" style={{ background: "var(--ink-soft)", borderColor: running ? "var(--gold-dim)" : "var(--ink-muted)" }}>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Auto-fill missing metadata</div>
              <div style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                Sweeps books with no description, matches by title/author, and queues confident matches for review on <a href="/sync" className="underline">Sync</a>. Books already tried are remembered and skipped next time.
              </div>
            </div>
            {running ? (
              <button onClick={cancelJob} className="shrink-0 inline-flex items-center gap-2 px-3 py-2 rounded-sm border"
                style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "#d98a8a", borderColor: "var(--ink-muted)" }}>
                <XCircle className="w-4 h-4" /> Stop
              </button>
            ) : (
              <div className="shrink-0 flex flex-col items-end gap-1">
                <button onClick={() => startJob(false)} className="inline-flex items-center gap-2 px-3 py-2 rounded-sm border transition-colors hover:border-[var(--gold)]"
                  style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                  <Sparkles className="w-4 h-4" /> Auto-fill new
                </button>
                <button onClick={() => startJob(true)} className="hover:underline"
                  style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                  rescan all (incl. skipped)
                </button>
              </div>
            )}
          </div>
          {job && (job.running || job.processed > 0) && (
            <div className="mt-3">
              <div className="h-1.5 rounded-full overflow-hidden mb-1.5" style={{ background: "var(--ink-muted)" }}>
                <div className="h-full" style={{ width: `${job.total ? Math.round(100 * job.processed / job.total) : 0}%`, background: "var(--gold)" }} />
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)" }}>
                {job.processed}/{job.total} scanned · {job.filled} queued · {job.no_match} no match{job.skipped ? ` · ${job.skipped} previously tried` : ""}
                {running && job.current ? ` · ${String(job.current).slice(0, 40)}…` : ""}
                {!running && job.finished_at ? " · done" : ""}
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5 mb-4">
          {FIELDS.map(([key, label]) => (
            <button key={key} onClick={() => { setField(key); setPage(1); }}
              className="px-3 py-1 rounded-sm border"
              style={{ fontFamily: "var(--mono)", fontSize: "0.68rem",
                       borderColor: field === key ? "var(--gold)" : "var(--ink-muted)",
                       color: field === key ? "var(--gold-light)" : "var(--parchment-dim)", background: "transparent" }}>
              {label}
            </button>
          ))}
        </div>

        <div className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
          {data.total.toLocaleString()} books missing {FIELDS.find(f => f[0] === field)?.[1].toLowerCase()}
        </div>

        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
        ) : data.items.length === 0 ? (
          <div className="text-center py-12" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.5 }}>
            <SearchX className="w-8 h-8 mx-auto mb-3" style={{ opacity: 0.4 }} /> None — all set.
          </div>
        ) : (
          <div className="space-y-1.5">
            {data.items.map(b => (
              <a key={b.id} href={`/books/${b.id}`}
                className="flex items-center justify-between gap-3 p-3 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                <div className="min-w-0">
                  <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>{b.title}</div>
                  <div className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>{b.author}</div>
                </div>
                <ChevronRight className="w-4 h-4 shrink-0" style={{ color: "var(--parchment-dim)", opacity: 0.5 }} />
              </a>
            ))}
          </div>
        )}

        {pages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-6" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="disabled:opacity-30 hover:underline">← Prev</button>
            <span>{page} / {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(p => p + 1)} className="disabled:opacity-30 hover:underline">Next →</button>
          </div>
        )}
      </div>
    </div>
  );
}
