"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import type { NativeBook, NativeBookUpdate } from "@/lib/api";
import { api } from "@/lib/api";
import {
  Calendar, Building2, Hash, MapPin, FileText,
  Star, Pencil, Upload, Trash2, X, Check, Loader2, RefreshCw,
} from "lucide-react";
import { AddToShelf } from "@/components/AddToShelf";
import { BackLink } from "@/components/BackLink";
import { ReadHistory } from "@/components/ReadHistory";

export function NativeBookDetail({ book: initial }: { book: NativeBook }) {
  const router = useRouter();
  const [book, setBook] = useState<NativeBook>(initial);
  const [editing, setEditing] = useState(false);
  const [coverVer, setCoverVer] = useState(0); // cache-buster after cover changes
  const [histRefresh, setHistRefresh] = useState(0);

  const coverSrc = `/api/native/books/${book.id}/cover${coverVer ? `?v=${coverVer}` : ""}`;
  const pubYear = book.published_date
    ? (book.published_date.match(/\d{4}/)?.[0] ?? book.published_date)
    : null;

  // Persist a field change to the backend and update local state.
  async function patch(body: NativeBookUpdate) {
    const updated = await api.updateNativeBook(book.id, body);
    setBook(updated);
    if ("reading_status" in body) setHistRefresh(r => r + 1);  // a new Read may have logged a date
    router.refresh();
    return updated;
  }

  return (
    <div className="min-h-screen">
      <div className="px-6 py-4 pl-16 lg:pl-6 border-b flex items-center justify-between"
           style={{ borderColor: "var(--ink-muted)" }}>
        <BackLink fallback="/?format=physical" />
        {!editing && (
          <button onClick={() => setEditing(true)}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
            style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)",
                     borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
            <Pencil className="w-3.5 h-3.5" />
            Edit details
          </button>
        )}
      </div>

      <div className="max-w-4xl mx-auto px-6 py-10">
        {editing ? (
          <EditForm
            book={book}
            onCoverChanged={(b) => { setBook(b); setCoverVer((v) => v + 1); router.refresh(); }}
            onSave={async (body) => { await patch(body); setEditing(false); }}
            onCancel={() => setEditing(false)}
            coverSrc={coverSrc}
          />
        ) : (
          <div className="flex flex-col sm:flex-row gap-6 sm:gap-10 items-start">
            {/* Cover (uploaded image, or a generated one when none exists) */}
            <div className="shrink-0 w-40 sm:w-44 mx-auto sm:mx-0">
              <img src={coverSrc} alt={book.title}
                className="w-full rounded-sm cover-shadow border" style={{ borderColor: "var(--ink-muted)" }} />

              {/* Physical ownership badge */}
              <div className="mt-4 flex items-center gap-2 px-3 py-2 rounded-sm"
                   style={{ background: "rgba(107,78,30,0.18)", border: "1px solid var(--gold-dim)" }}>
                <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#c9933a" }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--gold-light)" }}>
                  Physical copy
                </span>
              </div>
            </div>

            {/* Details */}
            <div className="flex-1 min-w-0">
              <h1 className="leading-tight mb-2"
                  style={{ fontFamily: "var(--serif)", fontSize: "2rem", fontWeight: 400, color: "var(--parchment)" }}>
                {book.title}
              </h1>

              {book.author && (
                <div className="block mb-4"
                  style={{ fontFamily: "var(--body)", fontSize: "1.15rem", fontStyle: "italic", color: "var(--parchment-dim)" }}>
                  {book.author}
                </div>
              )}

              {/* Rating — inline editable */}
              <div className="mb-4">
                <StarRating
                  value={book.rating ?? 0}
                  onChange={(r) => patch({ rating: r === book.rating ? null : r })}
                />
              </div>

              {/* Reading status (Unread / Reading / Read) + read history */}
              <div className="mb-4">
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  {([["", "Unread"], ["reading", "Reading"], ["read", "Read"]] as const).map(([val, label]) => {
                    const active = (book.reading_status ?? "") === val;
                    return (
                      <button key={label}
                        onClick={() => patch({
                          reading_status: val || null,
                          ...(val === "read" && !book.date_read ? { date_read: new Date().toISOString().slice(0, 10) } : {}),
                        })}
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
                {book.reading_status === "read" && (
                  <ReadHistory source="native" bookId={book.id} refreshKey={histRefresh} />
                )}
              </div>

              {/* Meta row */}
              <div className="flex flex-wrap gap-4 mb-5">
                {pubYear && <MetaItem icon={<Calendar className="w-3.5 h-3.5" />} label={String(pubYear)} />}
                {book.publisher && <MetaItem icon={<Building2 className="w-3.5 h-3.5" />} label={book.publisher} />}
                {book.page_count ? <MetaItem icon={<FileText className="w-3.5 h-3.5" />} label={`${book.page_count} pp`} /> : null}
                {(book.isbn13 || book.isbn) && <MetaItem icon={<Hash className="w-3.5 h-3.5" />} label={book.isbn13 || book.isbn || ""} />}
                {book.location && <MetaItem icon={<MapPin className="w-3.5 h-3.5" />} label={book.location} />}
              </div>

              {book.categories && book.categories.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-6">
                  {book.categories.map((c) => (
                    <span key={c} className="tag-pill">{c}</span>
                  ))}
                </div>
              )}

              <hr className="gold-rule mb-6" />

              <div className="mb-6">
                <AddToShelf bookId={book.id} bookSource="native" />
              </div>

              {book.description && (
                <div className="leading-relaxed"
                     style={{ fontFamily: "var(--body)", fontSize: "1rem", color: "var(--parchment-dim)" }}>
                  {book.description}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inline star rating ────────────────────────────────────────────────────────
function StarRating({ value, onChange, size = "w-5 h-5" }: {
  value: number; onChange?: (r: number) => void; size?: string;
}) {
  const [hover, setHover] = useState(0);
  const interactive = !!onChange;
  const shown = hover || value;
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <button
          key={s}
          type="button"
          disabled={!interactive}
          onClick={() => onChange?.(s)}
          onMouseEnter={() => interactive && setHover(s)}
          onMouseLeave={() => interactive && setHover(0)}
          className={interactive ? "cursor-pointer transition-transform hover:scale-110" : "cursor-default"}
          style={{ background: "none", border: "none", padding: 0, lineHeight: 0 }}
          aria-label={`${s} star${s > 1 ? "s" : ""}`}
        >
          <Star
            className={`${size} ${s <= shown ? "fill-[var(--gold)] text-[var(--gold)]" : ""}`}
            style={s > shown ? { color: "var(--ink-muted)" } : {}}
          />
        </button>
      ))}
      {interactive && value > 0 && (
        <button type="button" onClick={() => onChange?.(0)}
          className="ml-2 transition-colors hover:text-[var(--parchment-dim)]"
          style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--ink-muted)" }}>
          clear
        </button>
      )}
    </div>
  );
}

// ── Edit form ─────────────────────────────────────────────────────────────────
function EditForm({ book, onSave, onCancel, onCoverChanged, coverSrc }: {
  book: NativeBook;
  onSave: (body: NativeBookUpdate) => Promise<void>;
  onCancel: () => void;
  onCoverChanged: (b: NativeBook) => void;
  coverSrc: string;
}) {
  const [f, setF] = useState({
    title: book.title ?? "",
    author: book.author ?? "",
    description: book.description ?? "",
    publisher: book.publisher ?? "",
    published_date: book.published_date ?? "",
    page_count: book.page_count != null ? String(book.page_count) : "",
    isbn: book.isbn ?? "",
    isbn13: book.isbn13 ?? "",
    language: book.language ?? "",
    format: book.format ?? "physical",
    location: book.location ?? "",
    categories: (book.categories ?? []).join(", "),
    rating: book.rating ?? 0,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coverBusy, setCoverBusy] = useState(false);
  const [coverUrl, setCoverUrl] = useState("");

  async function handleCoverUrl() {
    if (!coverUrl.trim()) return;
    setCoverBusy(true); setError(null);
    try {
      const updated = await api.updateNativeBook(book.id, { cover_url: coverUrl.trim() });
      setHasCover(true); setCoverUrl(""); onCoverChanged(updated);
    } catch (e: any) { setError(e.message ?? "Could not set cover from URL"); }
    finally { setCoverBusy(false); }
  }
  const [hasCover, setHasCover] = useState(!!book.cover_url);
  const fileRef = useRef<HTMLInputElement>(null);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));

  async function handleUpload(file: File) {
    setCoverBusy(true); setError(null);
    try {
      const updated = await api.uploadNativeCover(book.id, file);
      setHasCover(true);
      onCoverChanged(updated);
    } catch (e: any) {
      setError(e.message ?? "Cover upload failed");
    } finally {
      setCoverBusy(false);
    }
  }

  async function handleRemoveCover() {
    setCoverBusy(true); setError(null);
    try {
      const updated = await api.deleteNativeCover(book.id);
      setHasCover(false);
      onCoverChanged(updated);
    } catch (e: any) {
      setError(e.message ?? "Could not remove cover");
    } finally {
      setCoverBusy(false);
    }
  }

  async function handleRegenerate() {
    setCoverBusy(true); setError(null);
    try {
      const updated = await api.regenerateNativeCover(book.id);
      onCoverChanged(updated);
    } catch (e: any) {
      setError(e.message ?? "Could not regenerate cover");
    } finally {
      setCoverBusy(false);
    }
  }

  async function submit() {
    if (!f.title.trim()) { setError("Title is required"); return; }
    setSaving(true); setError(null);
    const body: NativeBookUpdate = {
      title: f.title.trim(),
      author: f.author || null,
      description: f.description || null,
      publisher: f.publisher || null,
      published_date: f.published_date || null,
      page_count: f.page_count.trim() ? Number(f.page_count) : null,
      isbn: f.isbn || null,
      isbn13: f.isbn13 || null,
      language: f.language || null,
      format: f.format || "physical",
      location: f.location || null,
      categories: f.categories.split(",").map((c) => c.trim()).filter(Boolean),
      rating: f.rating || null,
    };
    try {
      await onSave(body);
    } catch (e: any) {
      setError(e.message ?? "Save failed");
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col sm:flex-row gap-6 sm:gap-10 items-start">
      {/* Cover column (uploaded image, or a generated one when none exists) */}
      <div className="shrink-0 w-40 sm:w-44 mx-auto sm:mx-0">
        <img src={coverSrc} alt={f.title}
          className="w-full rounded-sm cover-shadow border" style={{ borderColor: "var(--ink-muted)" }} />

        <input ref={fileRef} type="file" accept="image/*" className="hidden"
          onChange={(e) => { const file = e.target.files?.[0]; if (file) handleUpload(file); e.target.value = ""; }} />

        <div className="mt-3 space-y-2">
          <button type="button" disabled={coverBusy} onClick={() => fileRef.current?.click()}
            className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)",
                     borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
            {coverBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {hasCover ? "Replace cover" : "Upload cover"}
          </button>
          {!hasCover && (
            <button type="button" disabled={coverBusy} onClick={handleRegenerate}
              className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)] disabled:opacity-50"
              style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)",
                       borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
              {coverBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Generate new cover
            </button>
          )}
          {hasCover && (
            <button type="button" disabled={coverBusy} onClick={handleRemoveCover}
              className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--ink-muted)] disabled:opacity-50"
              style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)",
                       borderColor: "var(--ink-muted)", background: "transparent" }}>
              <Trash2 className="w-3.5 h-3.5" />
              Remove cover
            </button>
          )}
          <div className="flex gap-1.5">
            <input value={coverUrl} onChange={e => setCoverUrl(e.target.value)} placeholder="…or paste image URL"
              className="flex-1 px-2 py-1.5 rounded-sm outline-none"
              style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)", color: "var(--parchment)", fontFamily: "var(--mono)", fontSize: "0.62rem" }} />
            <button type="button" disabled={coverBusy || !coverUrl.trim()} onClick={handleCoverUrl}
              className="px-2 rounded-sm border disabled:opacity-40"
              style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
              Set
            </button>
          </div>
        </div>
      </div>

      {/* Form column */}
      <div className="flex-1 min-w-0">
        <Field label="Title">
          <input value={f.title} onChange={set("title")} className="bc-input" />
        </Field>
        <Field label="Author">
          <input value={f.author} onChange={set("author")} className="bc-input" />
        </Field>

        <div className="mb-4">
          <Label>Rating</Label>
          <StarRating value={f.rating} onChange={(r) => setF((p) => ({ ...p, rating: r === p.rating ? 0 : r }))} />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Publisher"><input value={f.publisher} onChange={set("publisher")} className="bc-input" /></Field>
          <Field label="Published date"><input value={f.published_date} onChange={set("published_date")} className="bc-input" placeholder="e.g. 2019 or 2019-05-01" /></Field>
          <Field label="Pages"><input value={f.page_count} onChange={set("page_count")} className="bc-input" inputMode="numeric" /></Field>
          <Field label="Language"><input value={f.language} onChange={set("language")} className="bc-input" /></Field>
          <Field label="ISBN"><input value={f.isbn} onChange={set("isbn")} className="bc-input" /></Field>
          <Field label="ISBN-13"><input value={f.isbn13} onChange={set("isbn13")} className="bc-input" /></Field>
          <Field label="Format"><input value={f.format} onChange={set("format")} className="bc-input" /></Field>
          <Field label="Location"><input value={f.location} onChange={set("location")} className="bc-input" /></Field>
        </div>

        <Field label="Categories (comma-separated)">
          <input value={f.categories} onChange={set("categories")} className="bc-input" />
        </Field>

        <Field label="Description">
          <textarea value={f.description} onChange={set("description")} rows={6} className="bc-input resize-y" />
        </Field>

        {error && (
          <div className="mb-4" style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "#d98a8a" }}>
            {error}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button type="button" disabled={saving} onClick={submit}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)",
                     borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Save changes
          </button>
          <button type="button" disabled={saving} onClick={onCancel}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--ink-muted)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--parchment-dim)",
                     borderColor: "var(--ink-muted)", background: "transparent" }}>
            <X className="w-4 h-4" />
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="uppercase tracking-widest mb-1.5"
         style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function MetaItem({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-1.5"
         style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
      {icon}
      <span>{label}</span>
    </div>
  );
}
