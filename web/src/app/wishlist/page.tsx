"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, Search, Plus, X, Bookmark } from "lucide-react";

type Item = { id: number; title: string; author: string | null; isbn: string | null; cover_url: string | null; notes: string | null; book_id: number | null; book_source: string | null };

const olCover = (isbn?: string | null) => isbn ? `https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg?default=false` : null;
const authorStr = (a: any) => Array.isArray(a) ? a.join(", ") : (a || "");

export default function WishlistPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  const load = () => api.wishlist().then(setItems).catch(() => setItems([])).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const search = async () => {
    if (!title.trim()) return;
    setSearching(true); setResults(null);
    try { setResults(await api.lookupMetadata(title.trim(), author.trim() || undefined)); }
    finally { setSearching(false); }
  };

  const add = async (item: { title: string; author?: string; isbn?: string; cover_url?: string }) => {
    await api.addWishlist(item);
    setTitle(""); setAuthor(""); setResults(null);
    load();
  };

  const addManual = () => title.trim() && add({ title: title.trim(), author: author.trim() || undefined });

  const remove = async (id: number) => { await api.removeWishlist(id); setItems(items.filter(i => i.id !== id)); };

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <a href="/" className="inline-flex items-center gap-2 mb-6 hover:underline" style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>
        <h1 className="flex items-center gap-2 mb-1" style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }}>
          <Bookmark className="w-5 h-5" style={{ color: "var(--gold)" }} /> Want to Read
        </h1>
        <p className="mb-6" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.75 }}>
          Books you'd like to read but don't own yet.
        </p>

        {/* Add */}
        <div className="rounded-sm p-4 mb-8 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex flex-col sm:flex-row gap-2">
            <input className="bc-input flex-1" placeholder="Title" value={title}
              onChange={e => setTitle(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
            <input className="bc-input sm:w-44" placeholder="Author (optional)" value={author}
              onChange={e => setAuthor(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
            <button onClick={search} disabled={!title.trim() || searching}
              className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-sm disabled:opacity-40"
              style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.75rem" }}>
              {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />} Search
            </button>
          </div>

          {results && (
            <div className="mt-3 space-y-2">
              {results.length === 0 ? (
                <div className="text-center py-2" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
                  No matches found. <button onClick={addManual} className="hover:underline" style={{ color: "var(--gold-light)" }}>Add "{title}" anyway →</button>
                </div>
              ) : results.slice(0, 6).map((c, i) => {
                const cover = c.cover_url || olCover(c.isbn);
                return (
                  <div key={i} className="flex items-center gap-3 p-2 rounded-sm" style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)" }}>
                    {cover
                      ? <img src={cover} alt="" className="w-8 h-12 object-cover rounded-sm shrink-0" onError={e => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
                      : <div className="w-8 h-12 rounded-sm shrink-0" style={{ background: "var(--ink-muted)" }} />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.92rem", color: "var(--parchment)" }}>{c.title}</div>
                      <div className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.76rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                        {authorStr(c.author)} · {c.source}
                      </div>
                    </div>
                    <button onClick={() => add({ title: c.title, author: authorStr(c.author) || undefined, isbn: c.isbn || undefined, cover_url: cover || undefined })}
                      className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-sm hover:opacity-80"
                      style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>
                      <Plus className="w-3 h-3" /> Add
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* List */}
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
        ) : items.length === 0 ? (
          <div className="text-center py-12" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.6 }}>
            Nothing on your want-to-read list yet. Search above to add something.
          </div>
        ) : (
          <>
            <div className="uppercase tracking-widest mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
              {items.length} {items.length === 1 ? "book" : "books"}
            </div>
            <div className="space-y-2">
              {items.map(it => {
                const cover = it.book_id
                  ? (it.book_source === "native" ? `/api/native/books/${it.book_id}/cover` : `/api/covers/${it.book_id}`)
                  : (it.cover_url || olCover(it.isbn));
                return (
                  <div key={it.id} className="flex items-center gap-3 p-2.5 rounded-sm border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                    {cover
                      ? <img src={cover} alt="" className="w-9 h-14 object-cover rounded-sm shrink-0" onError={e => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
                      : <div className="w-9 h-14 rounded-sm shrink-0" style={{ background: "var(--ink-muted)" }} />}
                    <div className="min-w-0 flex-1">
                      {it.book_id ? (
                        <a href={`/books/${it.book_id}${it.book_source === "native" ? "?source=native" : ""}`}
                           className="truncate block hover:text-[var(--gold-light)]"
                           style={{ fontFamily: "var(--serif)", fontSize: "0.98rem", color: "var(--parchment)" }}>{it.title}</a>
                      ) : (
                        <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.98rem", color: "var(--parchment)" }}>{it.title}</div>
                      )}
                      <div className="truncate flex items-center gap-1.5" style={{ fontFamily: "var(--body)", fontSize: "0.8rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                        {it.author}{it.book_id ? <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--gold-light)", opacity: 0.8 }}>· in library</span> : null}
                      </div>
                    </div>
                    <button onClick={() => remove(it.id)} title="Remove" className="shrink-0 p-1.5 rounded-sm hover:bg-[rgba(180,80,80,0.2)]" style={{ color: "var(--parchment-dim)" }}>
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
