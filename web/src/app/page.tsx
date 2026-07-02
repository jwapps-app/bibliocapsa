import { cookies } from "next/headers";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import { SearchBar, FullTextSearchBar } from "@/components/SearchBar";
import { InfiniteBooks } from "@/components/InfiniteBooks";
import { ColumnPicker } from "@/components/ColumnPicker";
import { LibraryUrlRecorder } from "@/components/LibraryUrlRecorder";
import { ShelfGrid } from "@/components/ShelfGrid";
import { ReadFilter } from "@/components/ReadFilter";
import { SyncButton } from "@/components/SyncButton";
import { LendingView } from "@/components/LendingView";
import { colsClass } from "@/lib/grid";
import { Search, Layers, Type, User, CalendarPlus, CalendarCheck, Calendar, ArrowUpDown, ArrowUp, ArrowDown, Combine } from "lucide-react";
import Link from "next/link";

/** Icon for each sort key (custom date columns fall back to a calendar). */
function SortIcon({ k, className }: { k: string; className?: string }) {
  const Icon = k === "title" ? Type
    : k === "author" ? User
    : k === "series" ? Layers
    : k === "added" ? CalendarPlus
    : k === "date_read" ? CalendarCheck
    : Calendar;
  return <Icon className={className} />;
}

/** Icon-based sort control (shared by desktop and mobile). Date sorts default to
 *  newest-first; text sorts to A→Z. The active sort shows a direction arrow. */
function SortRow({ searchParams, activeSort, activeDir, sortOptions }: {
  searchParams: Record<string, string | undefined>;
  activeSort: string; activeDir: string;
  sortOptions: { key: string; label: string }[];
}) {
  const rest = Object.fromEntries(Object.entries(searchParams).filter(([, v]) => v) as [string, string][]);
  return (
    <div className="flex items-center gap-3 flex-wrap"
      style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
      <ArrowUpDown className="w-4 h-4" style={{ opacity: 0.5 }} />
      {sortOptions.map(o => {
        const active = activeSort === o.key;
        const dateSort = o.key === "added" || o.key === "date_read" || o.key.startsWith("custom:");
        const nextDir = active ? (activeDir === "asc" ? "desc" : "asc") : (dateSort ? "desc" : "asc");
        return (
          <Link key={o.key}
            href={`/?${new URLSearchParams({ ...rest, sort_by: o.key, sort_dir: nextDir })}`}
            title={`Sort by ${o.label}${active ? (activeDir === "desc" ? " (newest/Z first)" : " (oldest/A first)") : ""}`}
            aria-label={`Sort by ${o.label}`}
            className="flex items-center gap-0.5 transition-colors"
            style={{ color: active ? "var(--gold-light)" : "var(--parchment-dim)" }}>
            <SortIcon k={o.key} className="w-[1.35rem] h-[1.35rem]" />
            {active && (activeDir === "desc" ? <ArrowDown className="w-3.5 h-3.5" /> : <ArrowUp className="w-3.5 h-3.5" />)}
          </Link>
        );
      })}
    </div>
  );
}

interface PageProps {
  searchParams: Promise<{
    search?: string; view?: string; shelf?: string;
    series_id?: string; author_id?: string; tag_id?: string;
    sort_by?: string; sort_dir?: string; collapse?: string;
    format?: string; cols?: string; custom?: string; read?: string;
  }>;
}

export default async function HomePage({ searchParams: searchParamsPromise }: PageProps) {
  const searchParams = await searchParamsPromise;
  const view = searchParams.view;
  const collapse = searchParams.collapse === "1";
  // URL ?cols wins (shareable/explicit); otherwise fall back to the saved cookie,
  // then the default 7 (desktop target; the grid steps down on smaller screens).
  const savedCols = (await cookies()).get("cols")?.value;
  const cols = Math.min(8, Math.max(2, Number(searchParams.cols ?? savedCols ?? 7)));
  const PAGE_SIZE = 48;

  // Default sort: when viewing Read books, newest-read first; otherwise most
  // recently added first. Series view keeps series order. Users can override.
  const readActive = searchParams.read === "read";
  const defaultSort = searchParams.series_id ? "series_index" : readActive ? "date_read" : "added";
  const defaultDir  = searchParams.series_id ? "asc" : "desc";
  const activeSort = searchParams.sort_by ?? defaultSort;
  const activeDir  = searchParams.sort_dir ?? defaultDir;

  const fetchParams: Record<string, string | number | undefined> = {
    search:          searchParams.search,
    series_id:       searchParams.series_id ? Number(searchParams.series_id) : undefined,
    author_id:       searchParams.author_id ? Number(searchParams.author_id) : undefined,
    tag_id:          searchParams.tag_id    ? Number(searchParams.tag_id)    : undefined,
    sort_by:         activeSort,
    sort_dir:        activeDir,
    collapse_series: collapse ? 1 : undefined,
    format_filter:   searchParams.format ?? "all",
    custom_filter:   searchParams.custom,
    read_filter:     searchParams.read,
    page_size:       PAGE_SIZE,
  };

  // One fully-parallel round: fetch only what the requested view needs. This
  // used to fetch series/authors/tags (page_size up to 5000) on EVERY load and
  // serialize the books query behind all of them.
  const [health, seriesList, authorsList, tagsList, customCols, readingMap, books] = await Promise.all([
    api.health().catch(() => null),
    view === "series"  ? api.series({ page_size: 300 })  : Promise.resolve([]),
    view === "authors" ? api.authors({ page_size: 300 }) : Promise.resolve([]),
    view === "tags"    ? api.tags()                      : Promise.resolve([]),
    !view ? api.customColumns().catch(() => []) : Promise.resolve([]),
    !view ? api.getReadingMap().catch(() => null) : Promise.resolve(null),
    !view ? api.books({ ...fetchParams, page: 1 }).catch(() => null) : Promise.resolve(null),
  ]);
  // Unified "Date read" sort spans digital (mapped Calibre date column) + physical.
  // Other datetime columns still become extra sort options, but skip the mapped
  // one (it's represented by the unified option).
  const mappedDateLabel = readingMap?.date ?? null;
  const dateSorts = customCols
    .filter(c => c.datatype === "datetime" && c.label !== mappedDateLabel)
    .map(c => ({ key: `custom:${c.label}`, label: c.name }));
  const sortOptions = [
    { key: "title", label: "Title" }, { key: "author", label: "Author" },
    { key: "added", label: "Date added" }, { key: "date_read", label: "Date read" }, ...dateSorts,
  ];

  const activeFilter = searchParams.series_id || searchParams.author_id || searchParams.tag_id || searchParams.search || searchParams.custom || searchParams.read;

  return (
    <div className="flex h-screen overflow-hidden w-full max-w-full">
      <LibraryUrlRecorder />
      <Sidebar currentParams={searchParams as Record<string,string|undefined>}
        bookCount={health?.book_count} />

      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Header */}
        <header className="sticky top-0 z-20 border-b px-6 py-3 pl-14 lg:pl-6"
          style={{background:"rgba(var(--ink-rgb),0.92)",backdropFilter:"blur(8px)",borderColor:"var(--ink-muted)"}}>
          <div className="flex items-center gap-4">
            <SearchBar defaultValue={searchParams.search} />
            <div className="ml-auto flex items-center gap-3">
              <SyncButton />
              <div className="hidden lg:flex items-center gap-3"
                style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)"}}>
                {health?.book_count && <span>{health.book_count.toLocaleString()} books</span>}
                <div className={`w-1.5 h-1.5 rounded-full ${health?.status==="ok"?"bg-emerald-500":"bg-red-500"}`} />
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 px-3 py-4 md:px-6 md:py-6">
          {view==="series"  && <SeriesView series={seriesList as any} cols={cols} />}
          {view==="authors" && <AuthorsView authors={authorsList} />}
          {view==="tags"    && <TagsView tags={tagsList} />}
          {view==="search"  && <FullTextSearchBar />}
          {view==="lending" && <LendingView />}
          {view==="shelf"   && searchParams.shelf && <ShelfView shelfId={Number(searchParams.shelf)} cols={cols} />}

          {!view && books && (
            <>
              {/* Toolbar */}
              <div className="mb-6">
                {/* ── Mobile: count, then a single wrapping row of controls ── */}
                <div className="lg:hidden space-y-2">
                  <CountBreadcrumb activeFilter={!!activeFilter} total={books.total} />
                  <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
                    <ColumnPicker current={cols} />
                    <FormatFilter searchParams={searchParams} />
                    <ReadFilter searchParams={searchParams} />
                    <SortRow searchParams={searchParams} activeSort={activeSort} activeDir={activeDir} sortOptions={sortOptions} />
                  </div>
                </div>

                {/* ── Desktop: single row ── */}
                <div className="hidden lg:flex items-center justify-between gap-3">
                  <CountBreadcrumb activeFilter={!!activeFilter} total={books.total} />
                  <div className="flex items-center gap-4">
                    <ColumnPicker current={cols} />
                    <FormatFilter searchParams={searchParams} />
                    <ReadFilter searchParams={searchParams} />
                    <div className="w-px h-5" style={{ background: "var(--ink-muted)" }} />
                    <Link href={`/?${new URLSearchParams({
                        ...Object.fromEntries(Object.entries(searchParams).filter(([,v])=>v) as [string,string][]),
                        collapse: collapse ? "0" : "1", page: "1",
                      })}`}
                      title={collapse ? "Series collapsed — click to show all" : "Collapse series to one cover"}
                      aria-label="Collapse series"
                      className="flex items-center transition-colors"
                      style={{ color: collapse ? "var(--gold-light)" : "var(--parchment-dim)" }}>
                      <Combine className="w-5 h-5" />
                    </Link>
                    <SortRow searchParams={searchParams} activeSort={activeSort} activeDir={activeDir} sortOptions={sortOptions} />
                  </div>
                </div>
              </div>

              {books.items.length===0 ? (
                <div className="flex flex-col items-center justify-center py-24 gap-3">
                  <Search className="w-8 h-8" style={{color:"var(--parchment-dim)",opacity:0.3}} />
                  <p style={{fontFamily:"var(--serif)",fontSize:"1.2rem",color:"var(--parchment-dim)",opacity:0.5}}>
                    No books found
                  </p>
                </div>
              ) : (
                <InfiniteBooks
                  initialItems={books.items}
                  initialTotal={books.total}
                  pageSize={PAGE_SIZE}
                  fetchParams={fetchParams}
                  cols={cols}
                />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function CountBreadcrumb({ activeFilter, total }: { activeFilter: boolean; total: number }) {
  return (
    <div className="min-w-0 truncate" style={{fontFamily:"var(--mono)",fontSize:"0.75rem",color:"var(--parchment-dim)"}}>
      {activeFilter ? (
        <span>
          <Link href="/" style={{color:"var(--gold-light)"}} className="hover:underline">← All books</Link>
          <span style={{opacity:0.5}}> · {total.toLocaleString()} results</span>
        </span>
      ) : (
        <span style={{opacity:0.7}}>{total.toLocaleString()} books</span>
      )}
    </div>
  );
}

function FormatFilter({ searchParams }: { searchParams: Awaited<PageProps["searchParams"]> }) {
  const active = searchParams.format ?? "all";
  const rest = Object.fromEntries(Object.entries(searchParams).filter(([,v])=>v) as [string,string][]);
  return (
    <div className="flex items-center gap-1.5">
      <span style={{fontFamily:"var(--mono)",fontSize:"0.6rem",opacity:0.5}}>format</span>
      <div className="flex items-center gap-1" style={{fontFamily:"var(--mono)",fontSize:"0.65rem"}}>
        {(["all","digital","physical"] as const).map(f => (
          <Link key={f} href={`/?${new URLSearchParams({ ...rest, format: f, page: "1" })}`}
            className="px-2 py-1 rounded-sm transition-colors capitalize"
            style={{
              background: active===f ? "rgba(107,78,30,0.4)" : "transparent",
              color: active===f ? "var(--gold-light)" : "var(--parchment-dim)",
              border: `1px solid ${active===f ? "var(--gold-dim)" : "var(--ink-muted)"}`,
            }}>
            {f}
          </Link>
        ))}
      </div>
    </div>
  );
}

function SeriesView({ series, cols }: { series: any[]; cols: number }) {
  return (
    <div>
      <SectionTitle title="Series" count={series.length} />
      <div className={`grid ${colsClass(cols)} gap-2.5 md:gap-7 stagger`}>
        {series.map((s:any) => (
          <Link key={s.id} href={`/?series_id=${s.id}`} className="group flex flex-col fade-up">
            <div className="relative aspect-[2/3] w-full overflow-hidden rounded-sm cover-shadow group-hover:cover-shadow-hover transition-all duration-300 group-hover:-translate-y-1">
              {s.first_book_has_cover && s.first_book_cover_url ? (
                <img
                  src={s.first_book_cover_url.replace(/^https?:\/\/[^/]+/, "")}
                  alt={s.name}
                  className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500"
                  loading="lazy"
                />
              ) : (
                <div className="no-cover w-full h-full flex flex-col items-center justify-center p-3">
                  <p className="text-center leading-tight px-1"
                     style={{fontFamily:"var(--serif)",fontSize:"0.65rem",color:"var(--parchment-dim)",opacity:0.6}}>
                    {s.name}
                  </p>
                </div>
              )}
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/85 to-transparent px-2 pb-1.5 pt-4">
                <div style={{fontFamily:"var(--mono)",fontSize:"0.6rem",color:"var(--gold-light)"}}>
                  {s.book_count} {s.book_count===1?"book":"books"}
                </div>
              </div>
            </div>
            <div className="mt-2 px-0.5">
              <div className="leading-tight line-clamp-2"
                   style={{fontFamily:"var(--serif)",fontSize:"0.85rem",color:"var(--parchment)"}}>
                {s.name}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function AuthorsView({ authors }: { authors: any[] }) {
  return (
    <div>
      <SectionTitle title="Authors" count={authors.length} />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-1.5">
        {authors.map((a:any) => (
          <Link key={a.id} href={`/?author_id=${a.id}`}
            className="group flex items-center justify-between px-4 py-2.5 rounded-sm border border-transparent hover:border-[var(--gold-dim)] transition-colors"
            style={{background:"var(--ink-soft)"}}>
            <span className="truncate group-hover:text-[var(--gold-light)] transition-colors"
                  style={{fontFamily:"var(--body)",fontSize:"1rem",color:"var(--parchment)"}}>
              {a.name}
            </span>
            <span className="ml-3 shrink-0"
                  style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)"}}>
              {a.book_count}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function TagsView({ tags }: { tags: any[] }) {
  return (
    <div>
      <SectionTitle title="Genres" count={tags.length} />
      <div className="flex flex-wrap gap-2">
        {[...tags].sort((a,b)=>b.book_count-a.book_count).map((t:any) => (
          <Link key={t.id} href={`/?tag_id=${t.id}`} className="tag-pill">
            {t.name} <span style={{opacity:0.6,marginLeft:"4px"}}>{t.book_count}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function SectionTitle({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-baseline gap-3 mb-6">
      <h2 style={{fontFamily:"var(--serif)",fontSize:"1.8rem",color:"var(--parchment)"}}>{title}</h2>
      <span style={{fontFamily:"var(--mono)",fontSize:"0.75rem",color:"var(--parchment-dim)"}}>{count.toLocaleString()}</span>
    </div>
  );
}

function Placeholder({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-3">
      <p style={{fontFamily:"var(--serif)",fontSize:"1.5rem",color:"var(--parchment-dim)",opacity:0.6}}>{title}</p>
      <p style={{fontFamily:"var(--body)",fontSize:"0.95rem",color:"var(--parchment-dim)",opacity:0.5}}>{subtitle}</p>
    </div>
  );
}

async function ShelfView({ shelfId, cols }: { shelfId: number; cols: number }) {
  const BASE = typeof window === "undefined"
    ? (process.env.API_URL ?? "http://bibliocapsa:8000")
    : "";

  let shelf: any = null;
  let books: any[] = [];

  // Forward the session cookie so the auth-gated API authenticates this SSR fetch.
  const { cookies } = await import("next/headers");
  const session = (await cookies()).get("bibliocapsa_session");
  const headers: Record<string, string> = session
    ? { Cookie: `bibliocapsa_session=${session.value}` } : {};

  try {
    const [shelfRes, booksRes] = await Promise.all([
      fetch(`${BASE}/api/shelves`, { headers, cache: "no-store" }),
      fetch(`${BASE}/api/shelves/${shelfId}/books`, { headers, cache: "no-store" }),
    ]);
    const allShelves = await shelfRes.json();
    shelf = allShelves.find((s: any) => s.id === shelfId);
    books = await booksRes.json();
  } catch {}

  if (!shelf) return <Placeholder title="Shelf not found" subtitle="" />;

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <div>
          <div className="flex items-baseline gap-3">
            <h2 style={{fontFamily:"var(--serif)",fontSize:"1.8rem",color:"var(--parchment)"}}>{shelf.name}</h2>
            {shelf.is_smart && (
              <span style={{fontFamily:"var(--mono)",fontSize:"0.65rem",color:"var(--gold-light)",background:"rgba(107,78,30,0.3)",padding:"2px 8px",borderRadius:"2px"}}>
                smart
              </span>
            )}
          </div>
          {shelf.description && (
            <p style={{fontFamily:"var(--body)",fontSize:"0.9rem",color:"var(--parchment-dim)",opacity:0.7,marginTop:"4px"}}>
              {shelf.description}
            </p>
          )}
        </div>
      </div>

      {books.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <p style={{fontFamily:"var(--serif)",fontSize:"1.2rem",color:"var(--parchment-dim)",opacity:0.4}}>
            {shelf.is_smart ? "No books match this shelf's rules" : "No books on this shelf yet"}
          </p>
          {!shelf.is_smart && (
            <p style={{fontFamily:"var(--body)",fontSize:"0.85rem",color:"var(--parchment-dim)",opacity:0.3}}>
              Open any book and use "Add to shelf" to add it here
            </p>
          )}
        </div>
      ) : (
        <ShelfGrid books={books} cols={cols} />
      )}
    </div>
  );
}
