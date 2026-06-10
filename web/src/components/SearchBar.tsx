"use client";
import { useState, useTransition, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, X } from "lucide-react";
import clsx from "clsx";

export function SearchBar({ defaultValue }: { defaultValue?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [value, setValue] = useState(defaultValue ?? "");
  const [mode, setMode] = useState<"titles" | "content">("titles");
  const [pending, start] = useTransition();

  const submit = (v: string) => {
    if (mode === "content") {
      if (v.trim()) start(() => router.push(`/?view=search&q=${encodeURIComponent(v)}`));
      return;
    }
    const p = new URLSearchParams(searchParams.toString());
    if (v) { p.set("search", v); p.delete("view"); } else { p.delete("search"); }
    p.delete("page");
    start(() => router.push(`/?${p}`));
  };

  return (
    <div className="flex items-center gap-2 w-full max-w-lg">
      <select value={mode} onChange={e => setMode(e.target.value as any)}
        className="h-9 px-2 text-xs rounded-sm border focus:outline-none shrink-0"
        style={{ background: "var(--ink-muted)", borderColor: "var(--ink-muted)", color: "var(--parchment-dim)", fontFamily: "var(--mono)" }}
        title="Search scope">
        <option value="titles">Titles</option>
        <option value="content">Full Text</option>
      </select>
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 opacity-40" style={{color:"var(--parchment-dim)"}} />
        <input type="text" value={value} onChange={e=>setValue(e.target.value)}
          onKeyDown={e=>e.key==="Enter"&&submit(value)}
          placeholder={mode === "content" ? "Search inside book text…" : "Search titles, authors…"}
          className={clsx("w-full h-9 pl-9 pr-8 text-sm rounded-sm border focus:outline-none transition-colors",pending&&"opacity-60")}
          style={{background:"var(--ink-muted)",borderColor:"var(--ink-muted)",color:"var(--parchment)",fontFamily:"var(--body)"}} />
        {value && (
          <button onClick={()=>{setValue("");submit("");}} className="absolute right-2.5 top-1/2 -translate-y-1/2 opacity-30 hover:opacity-70">
            <X className="w-3.5 h-3.5" style={{color:"var(--parchment-dim)"}} />
          </button>
        )}
      </div>
    </div>
  );
}

const PAGE = 50;

export function FullTextSearchBar() {
  const sp = useSearchParams();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [searchedQ, setSearchedQ] = useState("");
  const [loading, setLoading] = useState(false);

  const runSearch = async (q: string, offset: number, append: boolean) => {
    if (!q.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=${PAGE}&offset=${offset}`);
      const data = await res.json();
      setTotal(data.total);
      setSearchedQ(data.query);
      setItems(prev => append ? [...prev, ...data.results] : data.results);
    } finally { setLoading(false); }
  };
  const search = () => runSearch(query, 0, false);

  // Auto-run when arriving from the top search bar (?q=).
  useEffect(() => {
    const q0 = sp.get("q");
    if (q0) { setQuery(q0); runSearch(q0, 0, false); }
  }, [sp]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <div>
        <h2 style={{fontFamily:"var(--serif)",fontSize:"1.8rem",color:"var(--parchment)"}} className="mb-1">Full-Text Search</h2>
        <p style={{fontFamily:"var(--body)",fontSize:"0.9rem",color:"var(--parchment-dim)"}} className="opacity-50">Search inside the actual content of your books.</p>
      </div>
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-lg">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 opacity-40" style={{color:"var(--parchment-dim)"}} />
          <input type="text" value={query} onChange={e=>setQuery(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&search()}
            placeholder="Search inside books…"
            className="w-full pl-10 pr-4 py-2.5 text-sm rounded-sm border focus:outline-none"
            style={{background:"var(--ink-muted)",borderColor:"var(--ink-muted)",color:"var(--parchment)",fontFamily:"var(--body)"}} />
        </div>
        <button onClick={search} disabled={loading}
          className="px-5 py-2.5 text-sm rounded-sm transition-colors disabled:opacity-40"
          style={{background:"var(--gold-dim)",color:"var(--gold-light)",fontFamily:"var(--mono)"}}>
          {loading?"…":"Search"}
        </button>
      </div>
      {total !== null && (
        <div>
          <div className="mb-4 opacity-40" style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)"}}>
            Showing {items.length.toLocaleString()} of {total.toLocaleString()} matches for "{searchedQ}"
          </div>
          <div className="space-y-3">
            {items.map((r:any,i:number) => {
              const isPdf = (r.format || "").toUpperCase() === "PDF";
              const readHref = `/books/${r.book_id}/read?${isPdf ? "fmt=pdf&" : ""}q=${encodeURIComponent(searchedQ)}`;
              return (
                <div key={i} className="flex gap-4 p-4 rounded-sm border transition-colors"
                  style={{background:"var(--ink-soft)",borderColor:"var(--ink-muted)"}}>
                  {r.has_cover && r.cover_url && <img src={r.cover_url.replace(/^https?:\/\/[^/]+/, "")} alt={r.title} className="w-10 h-14 object-cover rounded-sm shrink-0 cover-shadow" />}
                  <div className="min-w-0 flex-1">
                    <div style={{fontFamily:"var(--serif)",fontSize:"1rem",color:"var(--parchment)"}}>{r.title}</div>
                    <div className="text-xs mb-2 opacity-50" style={{fontFamily:"var(--body)",color:"var(--parchment-dim)"}}>{r.authors.join(", ")} · {r.format}</div>
                    <div className="text-sm leading-relaxed line-clamp-3 opacity-60 mb-2" style={{fontFamily:"var(--body)",fontStyle:"italic",color:"var(--parchment-dim)"}}>{r.excerpt}</div>
                    <div className="flex gap-3" style={{fontFamily:"var(--mono)",fontSize:"0.7rem"}}>
                      <a href={readHref} className="inline-flex items-center gap-1 hover:underline" style={{color:"var(--gold-light)"}}>
                        <Search className="w-3 h-3" /> {isPdf ? "Open in reader" : "Read & find in book"}
                      </a>
                      <a href={`/books/${r.book_id}`} className="hover:underline" style={{color:"var(--parchment-dim)"}}>Details</a>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {items.length < total && (
            <div className="flex justify-center mt-5">
              <button onClick={() => runSearch(searchedQ, items.length, true)} disabled={loading}
                className="px-5 py-2 text-sm rounded-sm border transition-colors hover:border-[var(--gold-dim)] disabled:opacity-40"
                style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)", color: "var(--parchment-dim)", fontFamily: "var(--mono)" }}>
                {loading ? "Loading…" : `Load more (${(total - items.length).toLocaleString()} more)`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
