import type { BookSummary } from "@/lib/api";
import { publicUrl } from "@/lib/api";
import clsx from "clsx";

interface Props {
  book: BookSummary;
  className?: string;
}

export function BookCard({ book, className }: Props) {
  const author = book.authors[0]?.name ?? "Unknown Author";
  const stars = book.rating ? Math.round(book.rating) : 0;
  const isNative = book.book_source === "native";
  const isDual = !isNative && book.has_physical === true;
  const isPhysicalOnly = isNative;

  const href = isNative ? `/books/${book.id}?source=native` : `/books/${book.id}`;
  // Calibre authors have a real id → go to their author page. Physical/native
  // authors have no Calibre record, so fall back to a search by name (which spans
  // both physical and digital books).
  const authorName = book.authors[0]?.name;
  const authorId = book.authors[0]?.id;
  const authorHref = authorId
    ? `/?author_id=${authorId}`
    : authorName ? `/?search=${encodeURIComponent(authorName)}` : null;

  return (
    <div className={clsx("group flex flex-col", className)}>
      <a href={href} className="block">
      <div className="relative aspect-[2/3] w-full overflow-hidden rounded cover-shadow group-hover:cover-shadow-hover transition-all duration-300 group-hover:-translate-y-1"
           style={{ background: "var(--ink-soft)", border: "3px solid var(--cover-border)" }}>
        {book.has_cover && book.cover_url ? (
          <img
            src={publicUrl(book.cover_url) ?? ""}
            alt={book.title}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500"
            loading="lazy"
          />
        ) : (
          <div className="no-cover w-full h-full flex flex-col items-center justify-center p-3 gap-2">
            <div className="w-8 h-0.5 rounded" style={{background:"var(--gold-dim)",opacity:0.4}} />
            <p className="text-center leading-tight mt-2 px-1"
               style={{fontFamily:"var(--sans)",fontSize:"0.65rem",color:"var(--parchment-dim)",opacity:0.5}}>
              {book.title}
            </p>
          </div>
        )}

        {/* Series index badge — upper left */}
        {book.series?.series_index != null && (
          <div className="absolute top-1.5 left-1.5 w-6 h-6 rounded-sm flex items-center justify-center"
               style={{background:"rgba(0,0,0,0.75)",backdropFilter:"blur(4px)"}}>
            <span style={{fontFamily:"var(--mono)",fontSize:"0.6rem",color:"var(--gold-light)",lineHeight:1}}>
              {book.series.series_index % 1 === 0
                ? book.series.series_index.toFixed(0)
                : book.series.series_index}
            </span>
          </div>
        )}

        {/* Format dots — upper right corner */}
        {(isDual || isPhysicalOnly) && (
          <div style={{position:"absolute",top:"6px",right:"6px",display:"flex",gap:"3px",alignItems:"center",zIndex:10}}>
            {isDual && (
              <div style={{
                width:"8px",height:"8px",borderRadius:"50%",
                background:"#4a9aba",
                boxShadow:"0 0 0 1px rgba(0,0,0,0.5), 0 0 4px rgba(74,154,186,0.8)",
              }} title="Also owned as digital" />
            )}
            <div style={{
              width:"8px",height:"8px",borderRadius:"50%",
              background:"#c9933a",
              boxShadow:"0 0 0 1px rgba(0,0,0,0.5), 0 0 4px rgba(201,147,58,0.8)",
            }} title={book.physical_location ? `Physical · ${book.physical_location}` : "Physical copy"} />
          </div>
        )}

        {/* Series name badge — bottom */}
        {book.series && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/85 to-transparent px-2 pb-1.5 pt-4">
            <div className="truncate" style={{fontFamily:"var(--mono)",fontSize:"0.58rem",color:"var(--gold-light)"}}>
              {book.series.name}{book.series.series_index != null ? ` #${book.series.series_index}` : ""}
            </div>
          </div>
        )}
      </div>
      </a>

      {/* Info — hidden on mobile (covers only); shown on desktop */}
      <div className="mt-2.5 px-0.5 hidden lg:block">
        <a href={href} className="block leading-snug line-clamp-2 hover:text-[var(--gold-light)] transition-colors text-[0.70rem] lg:text-[0.8rem]"
             style={{fontFamily:"var(--sans)",fontWeight:500,letterSpacing:"-0.01em",color:"var(--parchment)"}}
             title={book.title}>
          {book.title}
        </a>
        {authorHref ? (
          <a href={authorHref} className="block truncate mt-1 hover:text-[var(--gold-light)] transition-colors"
             style={{fontFamily:"var(--sans)",fontSize:"0.72rem",fontWeight:400,color:"var(--parchment-dim)",opacity:0.85}}>
            {author}
          </a>
        ) : (
          <div className="truncate mt-1"
               style={{fontFamily:"var(--sans)",fontSize:"0.72rem",fontWeight:400,color:"var(--parchment-dim)",opacity:0.85}}>
            {author}
          </div>
        )}
        {/* Format label */}
        {(isDual || isPhysicalOnly) && (
          <div style={{fontFamily:"var(--mono)",fontSize:"0.55rem",letterSpacing:"0.05em",
            color: isDual ? "var(--gold-light)" : "#c9933a", opacity:0.8, marginTop:"2px"}}>
            {isDual ? "digital + physical" : `physical${book.physical_location ? ` · ${book.physical_location}` : ""}`}
          </div>
        )}
        {stars > 0 ? (
          <div className="flex gap-px mt-1">
            {[1,2,3,4,5].map(s => (
              <span key={s} className={clsx("star", s <= stars && "filled")}>★</span>
            ))}
          </div>
        ) : book.community_rating ? (
          <div className="mt-1" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)", opacity: 0.65 }}
               title="Community rating (Hardcover)">
            ★ {book.community_rating.toFixed(1)} <span style={{ opacity: 0.6 }}>community</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
