"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { RefreshCw, Loader2, Trash2, ArrowLeft, CheckCircle, AlertTriangle, Upload, BookPlus } from "lucide-react";

const FIELD_LABELS: Record<string, string> = {
  title: "Title", authors: "Authors", comment: "Description", series: "Series",
  series_index: "Series #", tags: "Tags", publisher: "Publisher",
  pubdate: "Published", rating: "Rating", isbn: "ISBN",
};

export default function SyncPage() {
  const [items, setItems] = useState<any[]>([]);
  const [uploads, setUploads] = useState<any[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [uploadingBusy, setUploadingBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.calibrePending().then(d => { setItems(d.items); setUploads(d.uploads || []); setCount(d.count); }).catch(() => {}).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const onUpload = async (file: File) => {
    setUploadingBusy(true); setResult(null);
    try { await api.uploadCalibreBook(file); load(); }
    catch (e: any) { setResult(e.message ?? "Upload failed"); }
    finally { setUploadingBusy(false); }
  };
  const discardUpload = async (id: number) => { await api.discardUpload(id); load(); };

  const doSync = async () => {
    setSyncing(true); setResult(null);
    try {
      const r = await api.syncToCalibre();
      setConfirming(false);
      const failed = r.failed?.length ?? 0;
      const added = (r as any).added ?? 0;
      const parts = [];
      if (r.synced) parts.push(`updated ${r.synced}`);
      if (added) parts.push(`added ${added}`);
      setResult(`${parts.join(", ") || "Nothing"} in Calibre${failed ? ` · ${failed} failed` : ""}.`);
      load();
    } catch (e: any) {
      setResult(e.message ?? "Sync failed");
    } finally { setSyncing(false); }
  };

  const discard = async (bookId: number) => {
    await api.discardCalibreEdits(bookId);
    load();
  };

  const fmtValue = (field: string, v: any) => Array.isArray(v) ? v.join(", ") : String(v ?? "");

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <a href="/" className="inline-flex items-center gap-2 mb-6 hover:underline"
           style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>

        <div className="flex items-center gap-2 mb-1">
          <RefreshCw className="w-5 h-5" style={{ color: "var(--gold)" }} />
          <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }}>Sync to Calibre</h1>
        </div>
        <p style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.75 }} className="mb-6">
          Edits are saved in Bibliocapsa instantly and shown everywhere. They stay <em>pending</em> here until you
          deliberately push them to your Calibre library.
        </p>

        {/* Sync action */}
        <div className="rounded-sm p-5 mb-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <div style={{ fontFamily: "var(--serif)", fontSize: "1.1rem", color: "var(--parchment)" }}>
                {count} pending change{count === 1 ? "" : "s"}
              </div>
              <div style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                Writes these changes into your Calibre library. Your edits stay safe in Bibliocapsa either way.
              </div>
              {result && <div className="mt-2" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>{result}</div>}
            </div>
            <button onClick={() => setConfirming(true)} disabled={count === 0 || syncing}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
              <RefreshCw className="w-4 h-4" /> Sync now
            </button>
          </div>
        </div>

        {/* Confirm dialog */}
        {confirming && (
          <div className="fixed inset-0 z-50 flex items-center justify-center px-4" style={{ background: "rgba(0,0,0,0.6)" }} onClick={() => !syncing && setConfirming(false)}>
            <div className="w-full max-w-md rounded-sm border p-5" style={{ background: "var(--ink-soft)", borderColor: "var(--gold-dim)" }} onClick={e => e.stopPropagation()}>
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-5 h-5" style={{ color: "var(--gold-light)" }} />
                <span style={{ fontFamily: "var(--serif)", fontSize: "1.15rem", color: "var(--parchment)" }}>Write to Calibre?</span>
              </div>
              <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment-dim)" }}>
                This writes <strong style={{ color: "var(--parchment)" }}>{count} change{count === 1 ? "" : "s"}</strong> into your Calibre library.
                <br /><br />
                <strong style={{ color: "var(--gold-light)" }}>Make sure Calibre is closed</strong> before continuing, or the write may fail.
              </p>
              <div className="flex items-center justify-end gap-3">
                <button onClick={() => setConfirming(false)} disabled={syncing}
                  style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--parchment-dim)" }} className="px-3 py-2 hover:underline disabled:opacity-50">Cancel</button>
                <button onClick={doSync} disabled={syncing}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
                  style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                  {syncing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} Calibre is closed — Sync
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Upload a new book */}
        <input ref={fileRef} type="file" className="hidden"
          accept=".epub,.pdf,.mobi,.azw3,.azw,.fb2,.txt,.cbz,.cbr,.docx,.rtf"
          onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
        <button onClick={() => fileRef.current?.click()} disabled={uploadingBusy}
          className="w-full mb-6 flex items-center justify-center gap-2 px-4 py-3 rounded-sm border border-dashed transition-colors hover:border-[var(--gold-dim)] disabled:opacity-50"
          style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
          {uploadingBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          Upload a new book (added to Calibre on sync)
        </button>

        {/* Pending new books */}
        {uploads.length > 0 && (
          <div className="mb-6">
            <div className="uppercase tracking-widest mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
              New books to add ({uploads.length})
            </div>
            <div className="space-y-2">
              {uploads.map(u => (
                <div key={u.id} className="flex items-center gap-3 p-3 rounded-sm border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                  <BookPlus className="w-4 h-4 shrink-0" style={{ color: "var(--gold)" }} />
                  <div className="flex-1 min-w-0">
                    <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>{u.title}</div>
                    <div className="truncate" style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                      {u.authors ? `${u.authors} · ` : ""}{(u.format || "").toUpperCase()} · {Math.round((u.size || 0) / 1024)} KB
                    </div>
                  </div>
                  <button onClick={() => discardUpload(u.id)} title="Discard"
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-sm shrink-0"
                    style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", border: "1px solid transparent" }}>
                    <Trash2 className="w-3.5 h-3.5" /> Discard
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
        ) : items.length === 0 && uploads.length === 0 ? (
          <div className="text-center py-12" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.5 }}>
            <CheckCircle className="w-8 h-8 mx-auto mb-3" style={{ opacity: 0.4 }} />
            No pending changes. Everything is in sync.
          </div>
        ) : items.length === 0 ? null : (
          <div className="space-y-3">
            {items.map((it) => (
              <div key={it.book_id} className="p-4 rounded-sm border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <a href={`/books/${it.book_id}`} className="hover:underline"
                     style={{ fontFamily: "var(--serif)", fontSize: "1rem", color: "var(--parchment)" }}>
                    {it.fields.title ?? `Book #${it.book_id}`}
                  </a>
                  <button onClick={() => discard(it.book_id)} title="Discard these edits"
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-sm shrink-0 transition-colors hover:border-[var(--ink-muted)]"
                    style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", border: "1px solid transparent" }}>
                    <Trash2 className="w-3.5 h-3.5" /> Discard
                  </button>
                </div>
                <div className="space-y-1">
                  {Object.entries(it.fields).map(([field, v]) => (
                    <div key={field} className="flex gap-2" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem" }}>
                      <span style={{ color: "var(--gold-light)", minWidth: "5.5rem" }}>{FIELD_LABELS[field] ?? (field.startsWith("custom:") ? `#${field.slice(7)}` : field)}</span>
                      <span className="truncate" style={{ color: "var(--parchment-dim)" }}>{fmtValue(field, v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
