"use client";

import { useState, useEffect, useRef } from "react";
import { VirtuosoGrid } from "react-virtuoso";
import { Check } from "lucide-react";
import { COLS_CLASS } from "@/lib/grid";

/** Virtualized grid for a shelf's books (can be large, e.g. "Highly Rated").
 *  Only on-screen cards are rendered; windows into the existing <main> scroller. */
export function ShelfGrid({ books, cols }: { books: any[]; cols: number }) {
  const [scrollParent, setScrollParent] = useState<HTMLElement | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setScrollParent((anchorRef.current?.closest("main") as HTMLElement) ?? null);
  }, []);

  const cls = `grid ${COLS_CLASS[cols] ?? "grid-cols-3"} gap-2.5 md:gap-7`;

  return (
    <div ref={anchorRef}>
      {scrollParent ? (
        <VirtuosoGrid
          data={books}
          customScrollParent={scrollParent}
          overscan={800}
          listClassName={cls}
          itemContent={(_i, book) => <ShelfCard book={book} />}
        />
      ) : (
        <div className={cls}>
          {books.slice(0, 24).map((book, i) => <ShelfCard key={i} book={book} />)}
        </div>
      )}
    </div>
  );
}

function ShelfCard({ book }: { book: any }) {
  return (
    <a href={book.book_source === "native" ? `/books/${book.book_id}?source=native` : `/books/${book.book_id}`}
      className="group flex flex-col">
      <div className="relative aspect-[2/3] w-full overflow-hidden rounded-sm cover-shadow group-hover:cover-shadow-hover transition-all duration-300 group-hover:-translate-y-1">
        {book.has_cover && book.cover_url ? (
          <img src={book.cover_url.replace(/^https?:\/\/[^/]+/, "")} alt={book.title}
            className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <div className="no-cover w-full h-full flex items-center justify-center p-3">
            <p className="text-center leading-tight" style={{ fontFamily: "var(--serif)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.5 }}>{book.title}</p>
          </div>
        )}
        {book.series_name && book.series_index != null && (
          <div className="absolute top-1.5 left-1.5 w-6 h-6 rounded-sm flex items-center justify-center" style={{ background: "rgba(0,0,0,0.75)" }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--gold-light)" }}>
              {book.series_index % 1 === 0 ? Math.floor(book.series_index) : book.series_index}
            </span>
          </div>
        )}
        {(book.has_physical || book.book_source === "native" || book.reading_status === "read") && (() => {
          const isNative = book.book_source === "native";
          const isDual = !isNative && book.has_physical;
          const isRead = book.reading_status === "read";
          return (
            <div style={{ position: "absolute", top: "6px", right: "6px", display: "flex", gap: "4px", alignItems: "center", zIndex: 10 }}>
              {(isDual || isNative) && (
                <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
                  {isDual && <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#4a9aba", boxShadow: "0 0 0 1px rgba(0,0,0,0.5),0 0 4px rgba(74,154,186,0.8)" }} />}
                  <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#c9933a", boxShadow: "0 0 0 1px rgba(0,0,0,0.5),0 0 4px rgba(201,147,58,0.8)" }} />
                </div>
              )}
              {isRead && (
                <div title="Read" style={{ width: "17px", height: "17px", borderRadius: "50%", background: "var(--gold)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 0 1px rgba(0,0,0,0.55)" }}>
                  <Check style={{ width: "11px", height: "11px", color: "var(--ink)", strokeWidth: 3.5 }} />
                </div>
              )}
            </div>
          );
        })()}
        {book.percentage != null && (
          <div className="absolute bottom-0 left-0 right-0">
            <div style={{ height: "4px", background: "rgba(0,0,0,0.6)" }}>
              <div style={{ height: "4px", width: `${Math.min(100, Math.round(book.percentage * 100))}%`, background: "var(--gold)" }} />
            </div>
            <div style={{ background: "rgba(0,0,0,0.6)", fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--gold-light)", textAlign: "center", padding: "1px 0" }}>
              {Math.round(book.percentage * 100)}%
            </div>
          </div>
        )}
      </div>
      <div className="mt-2 px-0.5">
        <div className="leading-tight line-clamp-2" style={{ fontFamily: "var(--serif)", fontSize: "0.85rem", color: "var(--parchment)" }}>{book.title}</div>
        <div className="truncate mt-0.5" style={{ fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}>{(book.authors || []).join(", ")}</div>
        {book.book_source === "native" && (
          <div style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", letterSpacing: "0.06em", color: "#c9933a", opacity: 0.8, marginTop: "2px" }}>
            physical{book.location ? ` · ${book.location}` : ""}
          </div>
        )}
      </div>
    </a>
  );
}
