import { api } from "@/lib/api";
import { notFound } from "next/navigation";
import { Download, Calendar, Building2, Hash, BookOpen, BookOpenText, Info } from "lucide-react";
import { AddToShelf } from "@/components/AddToShelf";
import { BackLink } from "@/components/BackLink";
import { NativeBookDetail } from "./native";
import { ReadingBadge } from "./ReadingBadge";
import { SendToKindle } from "./SendToKindle";
import { CalibreEditor } from "./CalibreEditor";
import { MetadataPicker } from "./MetadataPicker";
import { ReadingSessions } from "./ReadingSessions";
import { CalibreRating } from "./CalibreRating";
import { BookmarkButton } from "@/components/BookmarkButton";
import { CalibreReadStatus } from "./CalibreReadStatus";
import { PhysicalOwnership } from "./PhysicalOwnership";
import { SafeHtml } from "@/components/SafeHtml";

export default async function BookPage({
  params, searchParams,
}: { params: Promise<{ id: string }>; searchParams: Promise<{ source?: string }> }) {
  const { id } = await params;
  const { source } = await searchParams;
  if (source === "native") {
    const nb = await api.nativeBook(Number(id)).catch(() => null);
    if (!nb) notFound();
    return <NativeBookDetail book={nb} />;
  }

  const book = await api.book(Number(id)).catch(() => null);
  if (!book) notFound();

  const allAuthors = book.authors.map(a => a.name).join(", ");
  const pubYear = book.pubdate ? new Date(book.pubdate).getFullYear() : null;

  return (
    <div className="min-h-screen">
      {/* Back nav */}
      <div className="px-6 py-4 pl-16 lg:pl-6 border-b" style={{borderColor:"var(--ink-muted)"}}>
        <BackLink fallback="/" />
      </div>

      <div className="max-w-4xl mx-auto px-6 py-10">
        <div className="flex flex-col sm:flex-row gap-6 sm:gap-10 items-start">
          {/* Cover */}
          <div className="shrink-0 w-40 sm:w-44 mx-auto sm:mx-0">
            {book.has_cover && book.cover_url ? (
              <img
                src={book.cover_url.replace(/^https?:\/\/[^/]+/, "")}
                alt={book.title}
                className="w-full rounded-sm cover-shadow border"
                style={{borderColor:"var(--ink-muted)"}}
              />
            ) : (
              <div className="aspect-[2/3] rounded-sm no-cover border flex items-center justify-center"
                   style={{borderColor:"var(--ink-muted)"}}>
                <BookOpen className="w-10 h-10" style={{color:"var(--parchment-dim)",opacity:0.3}} />
              </div>
            )}

            {/* Formats */}
            {book.formats.length > 0 && (
              <div className="mt-4 space-y-1.5">
                <div className="uppercase tracking-widest mb-2"
                     style={{fontFamily:"var(--mono)",fontSize:"0.6rem",color:"var(--parchment-dim)",opacity:0.5}}>
                  Formats
                </div>
                {book.formats.map(f => (
                  <a key={f.format}
                     href={`/api/books/${book.id}/file/${f.format.toLowerCase()}`}
                     download
                     className="flex items-center justify-between px-2.5 py-1.5 rounded-sm border transition-colors group hover:border-[var(--gold-dim)]"
                     style={{background:"var(--ink-soft)",borderColor:"var(--ink-muted)"}}>
                    <span className="group-hover:text-[var(--gold-light)] transition-colors"
                          style={{fontFamily:"var(--mono)",fontSize:"0.72rem",color:"var(--parchment-dim)"}}>
                      {f.format}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {f.size && (
                        <span style={{fontFamily:"var(--mono)",fontSize:"0.65rem",color:"var(--parchment-dim)",opacity:0.6}}>
                          {(f.size/1024/1024).toFixed(1)}MB
                        </span>
                      )}
                      <Download className="w-3 h-3" style={{color:"var(--parchment-dim)",opacity:0.5}} />
                    </div>
                  </a>
                ))}
              </div>
            )}
          </div>

          {/* Details */}
          <div className="flex-1 min-w-0">
            {/* Series badge */}
            {book.series && (
              <a href={`/?series_id=${book.series.id}`}
                 className="inline-flex items-center gap-1.5 mb-3 px-2.5 py-1 rounded-sm border transition-colors hover:border-opacity-70"
                 style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--gold-light)",
                   background:"rgba(107,78,30,0.2)",borderColor:"rgba(107,78,30,0.5)"}}>
                <Hash className="w-3 h-3" />
                {book.series.name}
                {book.series.series_index != null && ` · Book ${book.series.series_index}`}
              </a>
            )}

            {/* Title */}
            <h1 className="leading-tight mb-2"
                style={{fontFamily:"var(--serif)",fontSize:"2rem",fontWeight:400,color:"var(--parchment)"}}>
              {book.title}
            </h1>

            {/* Author */}
            <a href={`/?author_id=${book.authors[0]?.id}`}
               className="block mb-4 transition-colors hover:text-[var(--gold-light)]"
               style={{fontFamily:"var(--body)",fontSize:"1.15rem",fontStyle:"italic",color:"var(--parchment-dim)"}}>
              {allAuthors}
            </a>

            {/* Want to Read bookmark toggle */}
            <div className="mb-4">
              <BookmarkButton bookId={book.id} bookSource="calibre" title={book.title} author={allAuthors} />
            </div>

            {/* Rating — clickable (admin) / read-only, queues a Calibre overlay edit */}
            <CalibreRating bookId={book.id} rating={book.rating} community={book.community_rating} />

            {/* Read/Unread + read history (admin-editable; member read-only) */}
            <CalibreReadStatus bookId={book.id} status={book.reading_status} />

            {/* Read in browser (EPUB or PDF) + Send to Kindle */}
            {(() => {
              const hasEpub = book.formats.some(f => f.format.toUpperCase() === "EPUB");
              const hasPdf = book.formats.some(f => f.format.toUpperCase() === "PDF");
              const sendable = book.formats.some(f => ["EPUB", "AZW3", "MOBI", "PDF"].includes(f.format.toUpperCase()));
              const readHref = hasEpub ? `/books/${book.id}/read` : `/books/${book.id}/read?fmt=pdf`;
              return (
                <>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    {(hasEpub || hasPdf) && (
                      <a href={readHref}
                         className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold)]"
                         style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)",
                                  borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                        <BookOpenText className="w-4 h-4" /> Read{hasEpub ? "" : " (PDF)"}
                      </a>
                    )}
                    {sendable && <SendToKindle bookId={book.id} />}
                  </div>
                  {hasEpub && (
                    <p className="flex items-start gap-1.5 mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.72rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                      <Info className="w-3 h-3 mt-0.5 shrink-0" />
                      <span>Reading here syncs your place with KOReader to the <strong style={{ color: "var(--parchment)" }}>nearest chapter</strong> — exact position is kept between KOReader devices.</span>
                    </p>
                  )}
                </>
              );
            })()}

            {/* Admin: edit Calibre metadata + find missing metadata (pending overlay) */}
            <div className="flex flex-wrap gap-2">
              <CalibreEditor book={book} />
              <MetadataPicker book={book} />
            </div>

            {/* Currently-reading progress (from KOReader sync) */}
            <ReadingBadge bookId={book.id} />

            {/* KOReader reading sessions for this book (current user) */}
            <ReadingSessions bookId={book.id} />

            {/* Meta row */}
            <div className="flex flex-wrap gap-4 mb-5">
              {pubYear && <MetaItem icon={<Calendar className="w-3.5 h-3.5"/>} label={String(pubYear)} />}
              {book.publisher && <MetaItem icon={<Building2 className="w-3.5 h-3.5"/>} label={book.publisher} />}
              {book.isbn && <MetaItem icon={<Hash className="w-3.5 h-3.5"/>} label={book.isbn} />}
              {/* Format ownership — Digital + Physical, with an admin "remove physical" control */}
              {book.has_physical && (
                <PhysicalOwnership bookId={book.id} location={book.physical_location} />
              )}
            </div>

            {/* Tags */}
            {book.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-6">
                {book.tags.map(t => (
                  <a key={t.id} href={`/?tag_id=${t.id}`} className="tag-pill">{t.name}</a>
                ))}
              </div>
            )}

            {/* Calibre custom columns */}
            {book.custom && book.custom.length > 0 && (
              <div className="mb-6 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                {book.custom.map(c => (
                  <div key={c.label} className="flex flex-col">
                    <span className="uppercase tracking-widest" style={{fontFamily:"var(--mono)",fontSize:"0.55rem",color:"var(--parchment-dim)",opacity:0.5}}>{c.name}</span>
                    <span style={{fontFamily:"var(--body)",fontSize:"0.92rem",color:"var(--parchment)"}}>{fmtCustom(c)}</span>
                  </div>
                ))}
              </div>
            )}

            <hr className="gold-rule mb-6" />

            {/* Add to shelf */}
            <div className="mb-6">
              <AddToShelf bookId={book.id} bookSource="calibre" />
            </div>

            {/* Description (sanitized — Calibre comments are arbitrary HTML) */}
            {book.comment && (
              <SafeHtml html={book.comment}
                className="leading-relaxed prose prose-sm max-w-none"
                style={{fontFamily:"var(--body)",fontSize:"1rem",color:"var(--parchment-dim)"}} />
            )}

            {/* More by author */}
            <div className="mt-8 pt-6 border-t" style={{borderColor:"var(--ink-muted)"}}>
              <a href={`/?author_id=${book.authors[0]?.id}`}
                 className="transition-colors hover:underline"
                 style={{fontFamily:"var(--mono)",fontSize:"0.75rem",color:"var(--parchment-dim)"}}>
                More by {book.authors[0]?.name} →
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function fmtCustom(c: { datatype: string; is_multiple: boolean; value: any }): string {
  const v = c.value;
  if (c.is_multiple && Array.isArray(v)) return v.join(", ");
  if (c.datatype === "bool") return v ? "Yes" : "No";
  if (c.datatype === "datetime" && v) {
    const d = new Date(v);
    if (!isNaN(d.getTime()) && d.getFullYear() > 1) return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    return "—";
  }
  if (c.datatype === "rating") return "★".repeat(Math.round(Number(v) / 2)) || String(v);
  return String(v);
}

function MetaItem({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-1.5"
         style={{fontFamily:"var(--mono)",fontSize:"0.72rem",color:"var(--parchment-dim)"}}>
      {icon}
      <span>{label}</span>
    </div>
  );
}

export async function generateStaticParams() { return []; }
export const dynamic = "force-dynamic";
