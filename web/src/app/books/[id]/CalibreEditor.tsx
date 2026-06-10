"use client";

import { useState, useEffect } from "react";
import type { BookDetail } from "@/lib/api";
import { api } from "@/lib/api";
import { TagInput, Autocomplete } from "@/components/MetaInputs";
import { Pencil, X, Check, Loader2 } from "lucide-react";

/** Admin-only editor for Calibre metadata. Edits write to the Postgres overlay
 *  (shown instantly, pending until "Sync to Calibre"). */
export function CalibreEditor({ book }: { book: BookDetail }) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [seriesSuggestions, setSeriesSuggestions] = useState<string[]>([]);
  const [customCols, setCustomCols] = useState<{ label: string; name: string; datatype: string; is_multiple: boolean }[]>([]);
  const [cv, setCv] = useState<Record<string, string>>({});           // current custom values (as input strings)
  const [customInitial, setCustomInitial] = useState<Record<string, string>>({});

  useEffect(() => {
    api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {});
    api.tags().then(ts => setTagSuggestions(ts.map(t => t.name))).catch(() => {});
    api.series({ page_size: 5000 }).then(ss => setSeriesSuggestions(ss.map(s => s.name))).catch(() => {});
    api.customColumns().then(cols => {
      setCustomCols(cols);
      const init: Record<string, string> = {};
      cols.forEach(col => {
        const e = (book.custom || []).find(x => x.label === col.label);
        init[col.label] = toInput(col.datatype, e?.value);
      });
      setCustomInitial(init);
      setCv(init);
    }).catch(() => {});
  }, [book]);

  // Snapshot of the values as loaded — we diff against this so only *changed*
  // fields get queued (a one-letter title edit = 1 pending change, not 10).
  const initial = {
    title: book.title ?? "",
    authors: book.authors.map(a => a.name).join(", "),
    series: book.series?.name ?? "",
    series_index: book.series?.series_index != null ? String(book.series.series_index) : "",
    tags: book.tags.map(t => t.name),
    publisher: book.publisher ?? "",
    pubdate: book.pubdate ?? "",
    rating: book.rating ? Math.round(book.rating) : 0,
    isbn: book.isbn ?? "",
    comment: book.comment ?? "",
  };
  const [f, setF] = useState(initial);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF(p => ({ ...p, [k]: e.target.value }));

  async function save() {
    setBusy(true); setError(null);
    const list = (s: string) => s.split(",").map(x => x.trim()).filter(Boolean);

    // Only record fields that actually changed.
    const changed: Record<string, unknown> = {};
    if (f.title.trim() !== initial.title.trim()) changed.title = f.title.trim();
    if (f.authors !== initial.authors) changed.authors = list(f.authors);
    if (f.series.trim() !== initial.series.trim()) changed.series = f.series.trim() || null;
    if (f.series_index.trim() !== initial.series_index.trim()) changed.series_index = f.series_index.trim() ? Number(f.series_index) : null;
    if (JSON.stringify(f.tags) !== JSON.stringify(initial.tags)) changed.tags = f.tags;
    if (f.publisher.trim() !== initial.publisher.trim()) changed.publisher = f.publisher.trim() || null;
    if (f.pubdate.trim() !== initial.pubdate.trim()) changed.pubdate = f.pubdate.trim() || null;
    if (f.rating !== initial.rating) changed.rating = f.rating || null;
    if (f.isbn.trim() !== initial.isbn.trim()) changed.isbn = f.isbn.trim() || null;
    if (f.comment !== initial.comment) changed.comment = f.comment || null;

    // Custom columns (only changed ones).
    const customChanged: Record<string, unknown> = {};
    for (const col of customCols) {
      if ((cv[col.label] ?? "") !== (customInitial[col.label] ?? "")) {
        customChanged[col.label] = fromInput(col.datatype, cv[col.label] ?? "");
      }
    }
    if (Object.keys(customChanged).length) changed.custom = customChanged;

    if (Object.keys(changed).length === 0) { setEditing(false); setBusy(false); return; }
    try {
      await api.editCalibreBook(book.id, changed);
      window.location.reload();
    } catch (e: any) { setError(e.message ?? "Save failed"); setBusy(false); }
  }

  if (!isAdmin) return null;

  if (!editing) {
    return (
      <button onClick={() => setEditing(true)}
        className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
        style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
        <Pencil className="w-3.5 h-3.5" /> Edit metadata
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto py-10 px-4" style={{ background: "rgba(0,0,0,0.6)" }} onClick={() => setEditing(false)}>
      <div className="w-full max-w-lg rounded-sm border p-5" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <span style={{ fontFamily: "var(--serif)", fontSize: "1.2rem", color: "var(--parchment)" }}>Edit metadata</span>
          <button onClick={() => setEditing(false)} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
        </div>
        <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
          Saves instantly to Bibliocapsa and queues as a pending change — your Calibre library isn&apos;t touched until you Sync.
        </p>

        <Field label="Title"><input className="bc-input" value={f.title} onChange={set("title")} /></Field>
        <Field label="Authors (comma-separated)"><input className="bc-input" value={f.authors} onChange={set("authors")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Series">
            <Autocomplete value={f.series} suggestions={seriesSuggestions}
              onChange={v => setF(p => ({ ...p, series: v }))}
              onPick={async (name) => {
                const next = await api.seriesNextIndex(name);
                setF(p => ({ ...p, series: name, series_index: String(next) }));
              }} />
          </Field>
          <Field label="Series #"><input className="bc-input" value={f.series_index} onChange={set("series_index")} inputMode="decimal" /></Field>
          <Field label="Publisher"><input className="bc-input" value={f.publisher} onChange={set("publisher")} /></Field>
          <Field label="Published date"><input className="bc-input" value={f.pubdate} onChange={set("pubdate")} placeholder="YYYY-MM-DD" /></Field>
          <Field label="ISBN"><input className="bc-input" value={f.isbn} onChange={set("isbn")} /></Field>
          <Field label="Rating (0–5)"><input className="bc-input" value={String(f.rating)} onChange={e => setF(p => ({ ...p, rating: Math.max(0, Math.min(5, Number(e.target.value) || 0)) }))} inputMode="numeric" /></Field>
        </div>
        <Field label="Tags">
          <TagInput value={f.tags} suggestions={tagSuggestions}
            onChange={tags => setF(p => ({ ...p, tags }))} />
        </Field>
        <Field label="Description"><textarea className="bc-input resize-y" rows={5} value={f.comment} onChange={set("comment")} /></Field>

        {/* Calibre custom columns (dynamic) */}
        {customCols.length > 0 && (
          <>
            <div className="uppercase tracking-widest mt-1 mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--gold-light)", opacity: 0.7 }}>
              Custom columns
            </div>
            <div className="grid grid-cols-2 gap-3">
              {customCols.map(col => (
                <Field key={col.label} label={col.name}>
                  {col.datatype === "bool" ? (
                    <select className="bc-input" value={cv[col.label] ?? ""} onChange={e => setCv(p => ({ ...p, [col.label]: e.target.value }))}>
                      <option value="">—</option>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  ) : col.datatype === "datetime" ? (
                    <input className="bc-input" type="date" value={cv[col.label] ?? ""} onChange={e => setCv(p => ({ ...p, [col.label]: e.target.value }))} />
                  ) : (
                    <input className="bc-input"
                      inputMode={(col.datatype === "int" || col.datatype === "float") ? "decimal" : undefined}
                      value={cv[col.label] ?? ""} onChange={e => setCv(p => ({ ...p, [col.label]: e.target.value }))} />
                  )}
                </Field>
              ))}
            </div>
          </>
        )}

        {error && <div className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "#d98a8a" }}>{error}</div>}

        <div className="flex items-center gap-3">
          <button onClick={save} disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Save change
          </button>
          <button onClick={() => setEditing(false)} disabled={busy} style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }} className="hover:underline disabled:opacity-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

function toInput(dt: string, value: any): string {
  if (value === undefined || value === null) return "";
  if (dt === "bool") return value === true ? "yes" : value === false ? "no" : "";
  if (dt === "datetime") { const s = String(value); return s.length >= 10 ? s.slice(0, 10) : s; }
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}
function fromInput(dt: string, s: string): any {
  const t = s.trim();
  if (dt === "bool") return t === "yes" ? true : t === "no" ? false : null;
  if (dt === "int" || dt === "float") return t === "" ? null : Number(t);
  return t === "" ? null : t;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="uppercase tracking-widest mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{label}</div>
      {children}
    </div>
  );
}
