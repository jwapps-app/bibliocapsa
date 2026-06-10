"use client";

import { useState, useEffect, useRef } from "react";
import { ArrowLeft, Loader2, Check, Upload, BookPlus } from "lucide-react";
import { api } from "@/lib/api";

export default function NewBookPage() {
  const [mode, setMode] = useState<"physical" | "digital">("physical");
  const [isAdmin, setIsAdmin] = useState(false);
  const [f, setF] = useState({
    title: "", author: "", isbn: "", isbn13: "", publisher: "", published_date: "",
    page_count: "", language: "en", location: "", categories: "", description: "", cover_url: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Digital upload (admin → queued for Calibre via Sync).
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  useEffect(() => { api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {}); }, []);

  const onUpload = async (file: File) => {
    setUploading(true); setUploadMsg(null);
    try {
      const rec = await api.uploadCalibreBook(file);
      setUploadMsg(`Uploaded "${rec.title}". Review and push it to Calibre on the Sync page.`);
    } catch (e: any) { setUploadMsg(e.message ?? "Upload failed"); }
    finally { setUploading(false); }
  };

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF(p => ({ ...p, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.title.trim()) { setError("Title is required"); return; }
    setBusy(true); setError(null);
    try {
      const book = await api.createNativeBook({
        title: f.title.trim(),
        author: f.author || null,
        isbn: f.isbn || null,
        isbn13: f.isbn13 || null,
        publisher: f.publisher || null,
        published_date: f.published_date || null,
        page_count: f.page_count.trim() ? Number(f.page_count) : null,
        language: f.language || "en",
        location: f.location || null,
        categories: f.categories.split(",").map(c => c.trim()).filter(Boolean),
        description: f.description || null,
        cover_url: f.cover_url.trim() || null,
        format: "physical",
      });
      window.location.href = `/books/${book.id}?source=native`;
    } catch (err: any) {
      setError(err.message ?? "Could not add book");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-lg">
        <a href="/?format=physical" className="inline-flex items-center gap-2 mb-6 hover:underline"
           style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }} className="mb-3">Add a book</h1>

        {/* Physical / Digital tabs */}
        {isAdmin && (
          <div className="flex gap-2 mb-5">
            {([["physical", "Physical", BookPlus], ["digital", "Digital (upload)", Upload]] as const).map(([m, label, Icon]) => (
              <button key={m} onClick={() => setMode(m)}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border transition-colors"
                style={{ fontFamily: "var(--mono)", fontSize: "0.72rem",
                         borderColor: mode === m ? "var(--gold)" : "var(--ink-muted)",
                         color: mode === m ? "var(--gold-light)" : "var(--parchment-dim)",
                         background: mode === m ? "rgba(107,78,30,0.2)" : "transparent" }}>
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
        )}

        {mode === "digital" ? (
          <div>
            <p style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-5">
              Upload an ebook file (EPUB, PDF, MOBI, AZW3…). It's queued and added to your Calibre library on the next <a href="/sync" className="underline">Sync to Calibre</a>.
            </p>
            <input ref={fileRef} type="file" className="hidden"
              accept=".epub,.pdf,.mobi,.azw3,.azw,.fb2,.txt,.cbz,.cbr,.docx,.rtf"
              onChange={e => { const file = e.target.files?.[0]; if (file) onUpload(file); e.target.value = ""; }} />
            <button onClick={() => fileRef.current?.click()} disabled={uploading}
              className="w-full flex items-center justify-center gap-2 px-4 py-6 rounded-sm border border-dashed transition-colors hover:border-[var(--gold-dim)] disabled:opacity-50"
              style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
              {uploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Upload className="w-5 h-5" />}
              {uploading ? "Uploading…" : "Choose an ebook file to upload"}
            </button>
            {uploadMsg && (
              <div className="mt-4 p-3 rounded-sm" style={{ background: "var(--ink-soft)", fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)" }}>
                {uploadMsg} {uploadMsg.startsWith("Uploaded") && <a href="/sync" className="underline">Go to Sync →</a>}
              </div>
            )}
          </div>
        ) : (
        <>
        <p style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-6">
          Manually add a physical book to your library. You can add a cover and refine details after, or run enrichment by ISBN.
        </p>

        <form onSubmit={submit}>
          <Field label="Title"><input className="bc-input" value={f.title} onChange={set("title")} autoFocus /></Field>
          <Field label="Author"><input className="bc-input" value={f.author} onChange={set("author")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="ISBN"><input className="bc-input" value={f.isbn} onChange={set("isbn")} /></Field>
            <Field label="ISBN-13"><input className="bc-input" value={f.isbn13} onChange={set("isbn13")} /></Field>
            <Field label="Publisher"><input className="bc-input" value={f.publisher} onChange={set("publisher")} /></Field>
            <Field label="Published date"><input className="bc-input" value={f.published_date} onChange={set("published_date")} placeholder="e.g. 2019" /></Field>
            <Field label="Pages"><input className="bc-input" value={f.page_count} onChange={set("page_count")} inputMode="numeric" /></Field>
            <Field label="Location"><input className="bc-input" value={f.location} onChange={set("location")} placeholder="Shelf, room…" /></Field>
          </div>
          <Field label="Categories (comma-separated)"><input className="bc-input" value={f.categories} onChange={set("categories")} /></Field>
          <Field label="Cover image URL (optional)"><input className="bc-input" value={f.cover_url} onChange={set("cover_url")} placeholder="https://… (paste a cover image link)" /></Field>
          <Field label="Description"><textarea className="bc-input resize-y" rows={4} value={f.description} onChange={set("description")} /></Field>

          {error && <div className="mb-4" style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "#d98a8a" }}>{error}</div>}

          <button type="submit" disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Add book
          </button>
        </form>
        </>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="uppercase tracking-widest mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{label}</div>
      {children}
    </div>
  );
}
