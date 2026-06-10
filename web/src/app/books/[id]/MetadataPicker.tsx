"use client";

import { useState, useEffect } from "react";
import type { BookDetail } from "@/lib/api";
import { api } from "@/lib/api";
import { Sparkles, X, Loader2, Check } from "lucide-react";

/** Admin: look up missing metadata for a Calibre book from external sources and
 *  fill ONLY the empty fields into the pending overlay (reviewed before sync). */
export function MetadataPicker({ book }: { book: BookDetail }) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cands, setCands] = useState<any[]>([]);
  const [applying, setApplying] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {}); }, []);

  // What's currently missing on this book — only these get filled.
  const missing = {
    comment: !book.comment,
    pubdate: !book.pubdate || String(book.pubdate).startsWith("0101"),
    publisher: !book.publisher,
    isbn: !book.isbn,
    series: !book.series,
    tags: book.tags.length === 0,
  };
  const missingList = Object.entries(missing).filter(([, v]) => v).map(([k]) => k);

  const search = async () => {
    setOpen(true); setLoading(true); setMsg(null);
    try {
      const c = await api.lookupMetadata(book.title, book.authors[0]?.name);
      setCands(c);
    } catch { setCands([]); }
    finally { setLoading(false); }
  };

  const apply = async (c: any) => {
    setApplying(true); setMsg(null);
    const payload: Record<string, unknown> = {};
    if (missing.comment && c.description) payload.comment = c.description;
    if (missing.pubdate && c.published_date) payload.pubdate = String(c.published_date);
    if (missing.publisher && c.publisher) payload.publisher = c.publisher;
    if (missing.isbn && c.isbn) payload.isbn = c.isbn;
    if (missing.series && c.series) { payload.series = c.series; if (c.series_index != null) payload.series_index = c.series_index; }
    if (c.rating) api.setCommunityRating(book.id, c.rating);  // store community rating regardless
    if (Object.keys(payload).length === 0) {
      if (c.rating) { setMsg("Saved community rating."); setTimeout(() => window.location.reload(), 700); return; }
      setMsg("Nothing to fill from this match."); setApplying(false); return;
    }
    try {
      await api.editCalibreBook(book.id, payload);
      setMsg(`Queued ${Object.keys(payload).length} field(s) — review on Sync.`);
      setTimeout(() => window.location.reload(), 900);
    } catch (e: any) { setMsg(e.message ?? "Could not apply"); setApplying(false); }
  };

  if (!isAdmin || missingList.length === 0) return null;

  return (
    <>
      <button onClick={search}
        className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
        style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
        <Sparkles className="w-3.5 h-3.5" /> Find missing metadata
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto py-10 px-4" style={{ background: "rgba(0,0,0,0.6)" }} onClick={() => setOpen(false)}>
          <div className="w-full max-w-2xl rounded-sm border p-5" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }} onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.2rem", color: "var(--parchment)" }}>Find metadata</span>
              <button onClick={() => setOpen(false)} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
            </div>
            <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
              Missing: <span style={{ color: "var(--gold-light)" }}>{missingList.join(", ")}</span>. Pick a match — only those empty fields are filled, queued for review on Sync.
            </p>

            {msg && <div className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>{msg}</div>}

            {loading ? (
              <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
            ) : cands.length === 0 ? (
              <div className="text-center py-10" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.6 }}>No matches found.</div>
            ) : (
              <div className="space-y-2">
                {cands.map((c, i) => (
                  <div key={i} className="p-3 rounded-sm border" style={{ background: "var(--ink)", borderColor: "var(--ink-muted)" }}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>{c.title}</div>
                        <div style={{ fontFamily: "var(--body)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
                          {(c.authors || []).join(", ")}{c.published_date ? ` · ${c.published_date}` : ""}{c.series ? ` · ${c.series}` : ""}
                        </div>
                        <div className="flex gap-2 mt-1" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                          <span style={{ color: "var(--gold-light)" }}>{c.source}</span>
                          {c.isbn && <span>ISBN {c.isbn}</span>}
                          {c.description && <span>has description</span>}
                        </div>
                        {c.description && <div className="mt-1 line-clamp-2" style={{ fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.7 }}>{c.description}</div>}
                      </div>
                      <button onClick={() => apply(c)} disabled={applying}
                        className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
                        style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                        <Check className="w-3.5 h-3.5" /> Use
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
