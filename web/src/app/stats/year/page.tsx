"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, BookOpen, BookMarked, Sparkles, ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

type Book = {
  book_id: number; book_source: string; title: string;
  author: string | null; author_id: number | null; author_ids: number[];
  has_cover: boolean; date_read: string | null;
};
type Review = {
  year: number; total_books: number; by_month: number[];
  by_format: { digital: number; physical: number };
  top_authors: { name: string; count: number; id: number | null }[];
  top_genres: { name: string; count: number; id: number | null }[];
  books: Book[];
};

const coverFor = (b: Book) =>
  b.book_source === "native" ? `/api/native/books/${b.book_id}/cover` : `/api/covers/${b.book_id}`;
const hrefFor = (b: Book) =>
  b.book_source === "native" ? `/books/${b.book_id}?source=native` : `/books/${b.book_id}`;

export default function YearReviewPage() {
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [data, setData] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [openAuthor, setOpenAuthor] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.yearReview(year).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [year]);

  const maxMonth = data ? Math.max(1, ...data.by_month) : 1;
  const totalFmt = data ? data.by_format.digital + data.by_format.physical : 0;
  const digitalPct = totalFmt ? Math.round((data!.by_format.digital / totalFmt) * 100) : 0;

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <a href="/stats" className="inline-flex items-center gap-2 mb-6 hover:underline" style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Statistics
        </a>

        {/* Year selector */}
        <div className="flex items-center justify-center gap-4 mb-2">
          <button onClick={() => setYear(y => y - 1)} className="p-1 hover:opacity-70" style={{ color: "var(--parchment-dim)" }}><ChevronLeft className="w-5 h-5" /></button>
          <h1 style={{ fontFamily: "var(--serif)", fontSize: "2.4rem", color: "var(--parchment)" }}>{year}</h1>
          <button onClick={() => setYear(y => Math.min(thisYear, y + 1))} disabled={year >= thisYear}
            className="p-1 hover:opacity-70 disabled:opacity-20" style={{ color: "var(--parchment-dim)" }}><ChevronRight className="w-5 h-5" /></button>
        </div>
        <p className="text-center mb-8 uppercase tracking-[0.3em]" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--gold-light)" }}>
          Year in Review
        </p>

        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
        ) : !data || data.total_books === 0 ? (
          <div className="text-center py-20" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.6 }}>
            No finished books recorded for {year} yet.
          </div>
        ) : (
          <div className="space-y-8">
            {/* Hero number */}
            <div className="text-center rounded-sm py-8 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
              <Sparkles className="w-5 h-5 mx-auto mb-3" style={{ color: "var(--gold)" }} />
              <div style={{ fontFamily: "var(--serif)", fontSize: "4rem", lineHeight: 1, color: "var(--gold-light)" }}>{data.total_books}</div>
              <div className="mt-2 uppercase tracking-widest" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)" }}>books finished</div>
            </div>

            {/* Monthly bars */}
            <div>
              <SectionLabel>By month</SectionLabel>
              <div className="flex items-end justify-between gap-1.5 h-28 px-1">
                {data.by_month.map((n, i) => (
                  <div key={i} className="flex-1 flex flex-col items-center justify-end gap-1.5 h-full">
                    {n > 0 && <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)" }}>{n}</span>}
                    <div className="w-full rounded-sm transition-all" style={{ height: `${(n / maxMonth) * 100}%`, minHeight: n > 0 ? 4 : 0, background: n > 0 ? "var(--gold)" : "transparent" }} />
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>{MONTHS[i]}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Format split */}
            <div>
              <SectionLabel>Digital vs. physical</SectionLabel>
              <div className="flex h-7 rounded-sm overflow-hidden" style={{ background: "var(--ink-muted)" }}>
                {data.by_format.digital > 0 && <div style={{ width: `${digitalPct}%`, background: "var(--gold)" }} />}
              </div>
              <div className="flex justify-between mt-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)" }}>
                <span className="inline-flex items-center gap-1"><BookOpen className="w-3 h-3" style={{ color: "var(--gold)" }} /> {data.by_format.digital} digital</span>
                <span className="inline-flex items-center gap-1"><BookMarked className="w-3 h-3" /> {data.by_format.physical} physical</span>
              </div>
            </div>

            {/* Top authors — click to expand just the books read THIS year by that author */}
            {data.top_authors.length > 0 && (
              <div>
                <SectionLabel>Most-read authors</SectionLabel>
                <div className="space-y-2">
                  {data.top_authors.map((a, i) => {
                    const open = openAuthor === a.name;
                    const theirBooks = data.books.filter(b =>
                      a.id != null ? b.author_ids.includes(a.id) : b.author === a.name);
                    return (
                      <div key={a.name}>
                        <button onClick={() => setOpenAuthor(open ? null : a.name)}
                          className="flex items-center gap-3 w-full text-left hover:opacity-80">
                          <span style={{ fontFamily: "var(--serif)", fontSize: "1rem", color: "var(--gold-light)", width: "1.2rem" }}>{i + 1}</span>
                          <span className="flex-1 truncate" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment)" }}>{a.name}</span>
                          <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>{a.count} {a.count === 1 ? "book" : "books"}</span>
                          <ChevronDown className="w-3.5 h-3.5" style={{ color: "var(--parchment-dim)", transform: open ? "rotate(180deg)" : "none" }} />
                        </button>
                        {open && (
                          <div className="space-y-2 mt-2 ml-7">
                            {theirBooks.map(b => <BookRow key={`${b.book_source}-${b.book_id}`} b={b} />)}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Top genres */}
            {data.top_genres.length > 0 && (
              <div>
                <SectionLabel>Top genres</SectionLabel>
                <div className="flex flex-wrap gap-2">
                  {data.top_genres.map(g => (
                    <a key={g.name} href={g.id ? `/?tag_id=${g.id}` : undefined}
                       className={`px-3 py-1 rounded-full ${g.id ? "hover:border-[var(--gold-dim)]" : "cursor-default"}`}
                       style={{ background: "var(--ink-soft)", border: "1px solid var(--ink-muted)", fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment)" }}>
                      {g.name} <span style={{ color: "var(--gold-light)" }}>{g.count}</span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Books finished — each links to its page; author links to the library */}
            {data.books.length > 0 && (
              <div>
                <SectionLabel>Books finished ({data.books.length})</SectionLabel>
                <div className="space-y-2">
                  {data.books.map(b => <BookRow key={`${b.book_source}-${b.book_id}`} b={b} />)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="uppercase tracking-widest mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
      {children}
    </div>
  );
}

function BookRow({ b }: { b: Book }) {
  return (
    <div className="flex items-center gap-3 p-2.5 rounded-sm border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
      <a href={hrefFor(b)} className="shrink-0">
        {b.has_cover
          ? <img src={coverFor(b)} alt="" className="w-8 h-12 object-cover rounded-sm" />
          : <div className="w-8 h-12 rounded-sm" style={{ background: "var(--ink-muted)" }} />}
      </a>
      <div className="min-w-0 flex-1">
        <a href={hrefFor(b)} className="block truncate hover:text-[var(--gold-light)]"
           style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>{b.title}</a>
        {b.author && (
          <a href={b.author_id ? `/?author_id=${b.author_id}` : undefined}
             className={`block truncate ${b.author_id ? "hover:text-[var(--gold-light)]" : "cursor-default"}`}
             style={{ fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.8 }}>{b.author}</a>
        )}
      </div>
      {b.date_read && (
        <span className="shrink-0" style={{ fontFamily: "var(--mono)", fontSize: "0.66rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{b.date_read}</span>
      )}
    </div>
  );
}
