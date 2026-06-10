"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { VirtuosoGrid } from "react-virtuoso";
import type { BookSummary } from "@/lib/api";
import { BookCard } from "./BookCard";
import { COLS_CLASS } from "@/lib/grid";

interface Props {
  initialItems: BookSummary[];
  initialTotal: number;
  pageSize: number;
  fetchParams: Record<string, string | number | undefined>;
  cols?: number;
}

interface Ctx { loading: boolean; hasMore: boolean; count: number; onVisible?: () => void; }

function Footer({ context }: { context?: Ctx }) {
  const ref = useRef<HTMLDivElement>(null);
  // Trigger loading when the footer nears the viewport. More reliable than
  // Virtuoso's endReached on iOS Safari with a custom scroll parent.
  useEffect(() => {
    const el = ref.current;
    if (!el || !context?.onVisible) return;
    const io = new IntersectionObserver(
      entries => { if (entries[0].isIntersecting && context.hasMore && !context.loading) context.onVisible?.(); },
      { rootMargin: "800px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [context?.onVisible, context?.hasMore, context?.loading]);
  return (
    <div ref={ref} className="flex justify-center py-8 mt-2">
      {context?.loading && (
        <div className="flex items-center gap-2" style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
          <div className="w-1 h-1 rounded-full animate-bounce" style={{ background: "var(--gold)", animationDelay: "0ms" }} />
          <div className="w-1 h-1 rounded-full animate-bounce" style={{ background: "var(--gold)", animationDelay: "150ms" }} />
          <div className="w-1 h-1 rounded-full animate-bounce" style={{ background: "var(--gold)", animationDelay: "300ms" }} />
        </div>
      )}
      {context && !context.hasMore && context.count > 0 && (
        <div style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.3 }}>
          — {context.count.toLocaleString()} books —
        </div>
      )}
    </div>
  );
}

export function InfiniteBooks({ initialItems, initialTotal, pageSize, fetchParams, cols = 3 }: Props) {
  const [items, setItems] = useState<BookSummary[]>(initialItems);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(initialItems.length < initialTotal);
  const [scrollParent, setScrollParent] = useState<HTMLElement | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);

  // Window into the existing page scroller (the <main> element) so the sticky
  // header and sidebar layout are preserved.
  useEffect(() => {
    setScrollParent((anchorRef.current?.closest("main") as HTMLElement) ?? null);
  }, []);

  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return;
    setLoading(true);
    try {
      const nextPage = page + 1;
      const qs = new URLSearchParams(
        Object.entries({ ...fetchParams, page: nextPage, page_size: pageSize })
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      const res = await fetch(`/api/books?${qs}`);
      const data = await res.json();
      setItems(prev => {
        const existing = new Set(prev.map(b => b.id));
        const fresh = data.items.filter((b: BookSummary) => !existing.has(b.id));
        return [...prev, ...fresh];
      });
      setPage(nextPage);
      setHasMore(items.length + data.items.length < data.total);
    } catch (e) {
      console.error("Failed to load more books", e);
    } finally {
      setLoading(false);
    }
  }, [loading, hasMore, page, fetchParams, pageSize, items.length]);

  // Reset when the filter/search changes.
  useEffect(() => {
    setItems(initialItems);
    setPage(1);
    setHasMore(initialItems.length < initialTotal);
  }, [JSON.stringify(fetchParams), initialItems, initialTotal]);

  return (
    <div ref={anchorRef}>
      {scrollParent ? (
        <VirtuosoGrid
          data={items}
          customScrollParent={scrollParent}
          endReached={loadMore}
          overscan={800}
          context={{ loading, hasMore, count: items.length, onVisible: loadMore }}
          listClassName={`grid ${COLS_CLASS[cols] ?? "grid-cols-3"} gap-2.5 md:gap-7`}
          itemContent={(_index, book) => <BookCard book={book} />}
          components={{ Footer }}
        />
      ) : (
        // SSR / pre-mount fallback (also shown if no scroll parent is found) so
        // the library is never blank; Virtuoso takes over once mounted.
        <div className={`grid ${COLS_CLASS[cols] ?? "grid-cols-3"} gap-2.5 md:gap-7`}>
          {items.map(book => <BookCard key={book.id} book={book} />)}
        </div>
      )}
    </div>
  );
}
