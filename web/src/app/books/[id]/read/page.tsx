"use client";

import { useEffect, useRef, useState, useCallback, Suspense, use } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, Settings2, Minus, Plus, List, X, Search, Info, Maximize2, ScrollText, FileText } from "lucide-react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { api } from "@/lib/api";

type Theme = "light" | "sepia" | "dark";
const THEMES: Record<Theme, { bg: string; color: string }> = {
  light: { bg: "#f0e8d8", color: "#1a1713" },
  sepia: { bg: "#e9dcc2", color: "#3a2f1e" },
  dark:  { bg: "#1a1713", color: "#d4c8b0" },
};

export default function ReaderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Suspense fallback={null}>
      <ReaderDispatch id={Number(id)} />
    </Suspense>
  );
}

function ReaderDispatch({ id }: { id: number }) {
  const fmt = useSearchParams().get("fmt");
  return fmt === "pdf" ? <PdfReader bookId={id} /> : <EpubReader bookId={id} />;
}

// One page in the continuous-scroll PDF view. Renders itself to a canvas on
// mount; Virtuoso only mounts items near the viewport, so off-screen pages cost
// nothing. The min-height keeps the scroll height stable before the page paints.
function PdfScrollPage({ pdf, n, width, aspect }: { pdf: any; n: number; width: number; aspect: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!pdf || !width) return;
    let cancelled = false;
    let task: any;
    (async () => {
      try {
        const pg = await pdf.getPage(n);
        const base = pg.getViewport({ scale: 1 });
        const scale = Math.min(3, Math.max(0.2, width / base.width));
        const vp = pg.getViewport({ scale });
        const canvas = ref.current;
        if (!canvas || cancelled) return;
        canvas.width = vp.width; canvas.height = vp.height;
        task = pg.render({ canvasContext: canvas.getContext("2d"), viewport: vp });
        await task.promise.catch(() => {});
      } catch { /* skip page */ }
    })();
    return () => { cancelled = true; try { task?.cancel(); } catch {} };
  }, [pdf, n, width]);
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "4px 0",
                  minHeight: width ? Math.round(width * aspect) + 8 : undefined }}>
      <canvas ref={ref} className="max-w-full h-auto shadow-lg" />
    </div>
  );
}

function PdfReader({ bookId }: { bookId: number }) {
  // pdf.js renderer with page tracking → progress syncs to/from KOReader by page
  // number (PDF progress is an absolute page, so cross-device is exact).
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<any>(null);
  const renderTask = useRef<any>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const readyRef = useRef(false);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<{ page: number; excerpt: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const initialQ = useSearchParams().get("q") || "";
  // Page fit: "page" shows the whole page (default), "width" fills the width and
  // scrolls. fitRef/pageRef keep renderPage a stable callback (no reload on toggle).
  const [fit, setFit] = useState<"page" | "width">("page");
  const fitRef = useRef<"page" | "width">("page");
  const pageRef = useRef(1);
  // View mode: "paged" (one page, prev/next) or "scroll" (continuous, virtualized).
  const [mode, setMode] = useState<"paged" | "scroll">("paged");
  const modeRef = useRef<"paged" | "scroll">("paged");
  const baseAspectRef = useRef(1.3);   // page height/width ratio, for scroll-item sizing
  const [scrollWidth, setScrollWidth] = useState(0);
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  const runSearch = useCallback(async (q: string) => {
    const pdf = pdfRef.current;
    const ql = q.trim().toLowerCase();
    if (!pdf || ql.length < 2) { setSearchResults([]); return; }
    setSearching(true);
    setSearchResults([]);
    const out: { page: number; excerpt: string }[] = [];
    try {
      for (let n = 1; n <= pdf.numPages; n++) {
        try {
          const tc = await (await pdf.getPage(n)).getTextContent();
          const text = tc.items.map((it: any) => it.str).join(" ");
          const idx = text.toLowerCase().indexOf(ql);
          if (idx >= 0) {
            const s = Math.max(0, idx - 45), e = Math.min(text.length, idx + ql.length + 45);
            out.push({ page: n, excerpt: text.slice(s, e).trim() });
          }
        } catch { /* skip page */ }
        if (out.length >= 300) break;
      }
    } finally {
      setSearchResults(out);
      setSearching(false);
    }
  }, []);

  const renderPage = useCallback(async (n: number) => {
    const pdf = pdfRef.current, canvas = canvasRef.current;
    if (!pdf || !canvas) return;
    const pg = await pdf.getPage(n);
    const cont = containerRef.current;
    const availW = (cont?.clientWidth ?? 800) - 16;
    const availH = (cont?.clientHeight ?? 1000) - 16;
    const base = pg.getViewport({ scale: 1 });
    // "page": fit the whole page in the viewport. "width": fill width, scroll down.
    const raw = fitRef.current === "page"
      ? Math.min(availW / base.width, availH / base.height)
      : availW / base.width;
    const scale = Math.min(3, Math.max(0.4, raw));
    const vp = pg.getViewport({ scale });
    canvas.width = vp.width; canvas.height = vp.height;
    if (renderTask.current) { try { renderTask.current.cancel(); } catch {} }
    renderTask.current = pg.render({ canvasContext: canvas.getContext("2d"), viewport: vp });
    await renderTask.current.promise.catch(() => {});
  }, []);

  const changeFit = useCallback((f: "page" | "width") => {
    fitRef.current = f;
    setFit(f);
    try { localStorage.setItem("reader.pdfFit", f); } catch {}
    if (readyRef.current) renderPage(pageRef.current);
  }, [renderPage]);

  const scheduleSave = useCallback((n: number) => {
    const pct = numPages ? n / numPages : 0;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => api.saveBookProgress(bookId, pct, String(n), String(n), "pdf"), 800);
  }, [numPages, bookId]);

  // Jump to a page in either mode: scroll mode scrolls the virtual list; paged
  // mode just sets the page (the page-render effect redraws the single canvas).
  const goToPage = useCallback((n: number) => {
    const clamped = Math.min(numPages || n, Math.max(1, n));
    if (modeRef.current === "scroll") {
      virtuosoRef.current?.scrollToIndex({ index: clamped - 1, align: "start" });
    }
    pageRef.current = clamped;
    setPage(clamped);
  }, [numPages]);

  const changeMode = useCallback((m: "paged" | "scroll") => {
    modeRef.current = m;
    setMode(m);
    try { localStorage.setItem("reader.pdfMode", m); } catch {}
    if (m === "paged" && readyRef.current) renderPage(pageRef.current);
  }, [renderPage]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdfjs: any = await import("pdfjs-dist");
        // Worker served as a static asset (see web/Dockerfile) — not bundled.
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        // Stream via HTTP range requests instead of downloading the whole file
        // up front: pdf.js fetches just the structure + the current page so
        // page 1 renders fast, then pulls the rest in the background (kept on
        // for search / page jumps). The backend (Starlette FileResponse) serves
        // Range requests; if ranges aren't available pdf.js falls back to a full
        // download — i.e. never slower than before.
        const pdf = await pdfjs.getDocument({
          url: `/api/books/${bookId}/file/pdf?inline=1`,
          rangeChunkSize: 262144,   // 256 KB chunks
          disableStream: false,
          disableAutoFetch: false,
        }).promise;
        if (cancelled) return;
        pdfRef.current = pdf;
        setNumPages(pdf.numPages);
        // Page aspect ratio (assume uniform, true for books/Bibles) sizes the
        // scroll-mode item slots so the scrollbar is right before pages paint.
        try {
          const p1 = await pdf.getPage(1);
          const v1 = p1.getViewport({ scale: 1 });
          if (v1.width) baseAspectRef.current = v1.height / v1.width;
        } catch {}

        // Resume: most-recent of browser page / KOReader page (or percentage).
        let target = 1;
        try {
          const prog = await api.bookProgress(bookId, "pdf");
          const br = prog.browser, sy = prog.synced;
          const brTs = br?.ts ?? -1, syTs = sy?.ts ?? -1;
          const brPage = br?.cfi ? parseInt(br.cfi, 10) : NaN;
          const syPage = sy?.progress ? parseInt(sy.progress, 10)
            : (sy?.percentage != null ? Math.round(sy.percentage * pdf.numPages) : NaN);
          if (!isNaN(brPage) && brTs >= syTs) target = brPage;
          else if (!isNaN(syPage)) target = syPage;
        } catch {}
        target = Math.min(pdf.numPages, Math.max(1, target || 1));
        setPage(target);
        pageRef.current = target;
        // Paged mode draws the single canvas now; scroll mode (Virtuoso) renders
        // its own pages and opens at `target` via initialTopMostItemIndex.
        if (modeRef.current === "paged") await renderPage(target);
        readyRef.current = true;
        setLoading(false);
        if (initialQ.trim()) { setSearchQ(initialQ); setShowSearch(true); runSearch(initialQ); }
      } catch (e: any) {
        if (!cancelled) {
          const msg = e?.name === "MissingPDFException" || e?.status === 404
            ? "No PDF available for this book"
            : (e?.message ?? "Could not open PDF");
          setError(msg);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true; readyRef.current = false;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      try { renderTask.current?.cancel(); } catch {}
      try { pdfRef.current?.destroy?.(); } catch {}
    };
  }, [bookId, renderPage]);

  // Re-render + save when the page changes (after initial resume).
  useEffect(() => {
    if (!readyRef.current || modeRef.current !== "paged") return;
    pageRef.current = page;
    renderPage(page);
    scheduleSave(page);
  }, [page, numPages, bookId, renderPage, scheduleSave]);

  // Load saved fit + view-mode preferences once.
  useEffect(() => {
    try {
      const f = localStorage.getItem("reader.pdfFit");
      if (f === "page" || f === "width") { fitRef.current = f; setFit(f); }
      const m = localStorage.getItem("reader.pdfMode");
      if (m === "paged" || m === "scroll") { modeRef.current = m; setMode(m); }
    } catch {}
  }, []);

  // Track available width so scroll-mode pages render crisp; re-measure on resize.
  useEffect(() => {
    const measure = () => setScrollWidth(Math.max(0, (containerRef.current?.clientWidth ?? 0) - 24));
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [mode]);

  // Re-fit the current page on viewport resize / orientation change.
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const onResize = () => { clearTimeout(t); t = setTimeout(() => { if (readyRef.current) renderPage(pageRef.current); }, 150); };
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); clearTimeout(t); };
  }, [renderPage]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") goToPage(pageRef.current + 1);
      if (e.key === "ArrowLeft") goToPage(pageRef.current - 1);
    };
    document.addEventListener("keyup", onKey);
    return () => document.removeEventListener("keyup", onKey);
  }, [goToPage]);

  return (
    <div className="fixed inset-0 flex flex-col" style={{ background: "var(--ink)" }}>
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0"
           style={{ borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
        <div className="flex items-center gap-3">
          <a href={`/books/${bookId}`} className="inline-flex items-center gap-2 hover:underline"
             style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}>
            <ArrowLeft className="w-3.5 h-3.5" /> Back
          </a>
          <button onClick={() => setShowSearch(true)} className="inline-flex items-center gap-1.5"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }} aria-label="Search in PDF">
            <Search className="w-4 h-4" /> Search
          </button>
          <button onClick={() => changeMode(mode === "scroll" ? "paged" : "scroll")} className="inline-flex items-center gap-1.5"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}
            aria-label="Toggle scroll / paged view" title={mode === "scroll" ? "Switch to paged view" : "Switch to scroll view"}>
            {mode === "scroll" ? <FileText className="w-4 h-4" /> : <ScrollText className="w-4 h-4" />} {mode === "scroll" ? "Paged" : "Scroll"}
          </button>
          {mode === "paged" && (
            <button onClick={() => changeFit(fit === "page" ? "width" : "page")} className="inline-flex items-center gap-1.5"
              style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}
              aria-label="Toggle page fit" title={fit === "page" ? "Switch to fit-width" : "Switch to fit-page"}>
              <Maximize2 className="w-4 h-4" /> {fit === "page" ? "Fit width" : "Fit page"}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
          <button onClick={() => goToPage(page - 1)} disabled={page <= 1} className="disabled:opacity-30"><ChevronLeft className="w-4 h-4" /></button>
          <input type="number" min={1} max={numPages || 1} value={page}
            onChange={e => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) goToPage(v); }}
            className="bc-input" style={{ width: "3.5rem", padding: "2px 4px", textAlign: "center" }} />
          <span style={{ color: "var(--gold-light)" }}>/ {numPages || "…"}</span>
          <button onClick={() => goToPage(page + 1)} disabled={page >= numPages} className="disabled:opacity-30"><ChevronRight className="w-4 h-4" /></button>
        </div>
      </div>

      {/* Search drawer */}
      {showSearch && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowSearch(false)} style={{ background: "rgba(0,0,0,0.5)" }} />
          <div className="fixed top-0 right-0 z-50 h-full w-96 max-w-[90vw] flex flex-col"
               style={{ background: "var(--ink-soft)", borderLeft: "1px solid var(--ink-muted)" }}>
            <div className="flex items-center justify-between px-4 py-3 border-b shrink-0" style={{ borderColor: "var(--ink-muted)" }}>
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Search in PDF</span>
              <button onClick={() => setShowSearch(false)} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
            </div>
            <form className="px-4 py-3 border-b shrink-0 flex gap-2" style={{ borderColor: "var(--ink-muted)" }}
                  onSubmit={e => { e.preventDefault(); runSearch(searchQ); }}>
              <input autoFocus value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Find a word or phrase…"
                className="flex-1 px-2 py-1.5 rounded-sm outline-none"
                style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)", color: "var(--parchment)", fontFamily: "var(--body)", fontSize: "0.9rem" }} />
              <button type="submit" className="px-3 rounded-sm" style={{ background: "var(--gold-dim)", color: "var(--gold-light)" }}><Search className="w-4 h-4" /></button>
            </form>
            <div className="flex-1 overflow-y-auto">
              {searching ? (
                <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
              ) : searchResults.length === 0 ? (
                <div className="px-4 py-8 text-center" style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                  {searchQ.trim().length >= 2 ? "No matches." : "Type at least 2 characters."}
                </div>
              ) : (
                <>
                  <div className="px-4 py-2" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
                    {searchResults.length}{searchResults.length >= 300 ? "+" : ""} page{searchResults.length === 1 ? "" : "s"} with matches
                  </div>
                  {searchResults.map((r, i) => (
                    <button key={i} onClick={() => { goToPage(r.page); setShowSearch(false); }}
                      className="block w-full text-left px-4 py-2.5 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
                      style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)", borderBottom: "1px solid var(--ink-muted)" }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--gold-light)" }}>p. {r.page}</span>{"  "}…{r.excerpt}…
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>
        </>
      )}

      <div ref={containerRef}
           className={`relative flex-1 min-h-0 ${mode === "scroll" ? "overflow-hidden" : "overflow-auto flex justify-center"}`}
           style={{ background: "#33312c" }}>
        {loading && <div className="absolute inset-0 flex items-center justify-center z-20" style={{ color: "var(--parchment-dim)" }}><Loader2 className="w-6 h-6 animate-spin" /></div>}
        {error && <div className="absolute inset-0 flex items-center justify-center px-6 text-center z-20" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)" }}>{error}</div>}
        {mode === "scroll" ? (
          !loading && !error && numPages > 0 && scrollWidth > 0 && (
            <Virtuoso
              ref={virtuosoRef}
              style={{ height: "100%", width: "100%" }}
              totalCount={numPages}
              initialTopMostItemIndex={Math.max(0, pageRef.current - 1)}
              increaseViewportBy={600}
              itemContent={(index) => (
                <PdfScrollPage pdf={pdfRef.current} n={index + 1} width={scrollWidth} aspect={baseAspectRef.current} />
              )}
              rangeChanged={(r) => {
                const cur = r.startIndex + 1;
                if (cur >= 1 && readyRef.current) { pageRef.current = cur; setPage(cur); scheduleSave(cur); }
              }}
            />
          )
        ) : (
          <>
            <button onClick={() => goToPage(page - 1)} aria-label="Previous page" className="fixed left-0 top-12 bottom-0 w-[12%] z-10" style={{ background: "transparent" }} />
            <button onClick={() => goToPage(page + 1)} aria-label="Next page" className="fixed right-0 top-12 bottom-0 w-[12%] z-10" style={{ background: "transparent" }} />
            <canvas ref={canvasRef} className="my-2 max-w-full h-auto shadow-lg" style={{ alignSelf: "flex-start" }} />
          </>
        )}
      </div>
    </div>
  );
}

function EpubReader({ bookId }: { bookId: number }) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const renditionRef = useRef<any>(null);
  const bookRef = useRef<any>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const readyRef = useRef(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [showToc, setShowToc] = useState(false);
  const [toc, setToc] = useState<{ label: string; href: string; depth: number }[]>([]);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<{ cfi: string; excerpt: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const lastHighlight = useRef<string | null>(null);
  // Set once the reader navigates (page turn / TOC / search). Cancels the
  // deferred percentage-resume jump so we never yank them off a page they've
  // already started reading while the location index is still building.
  const userInteractedRef = useRef(false);
  const initialQ = useSearchParams().get("q") || "";
  const [fontSize, setFontSize] = useState(110);
  const [theme, setTheme] = useState<Theme>("light");
  const [flow, setFlow] = useState<"paginated" | "scrolled-doc">("paginated");

  const next = useCallback(() => { userInteractedRef.current = true; renditionRef.current?.next(); }, []);
  const prev = useCallback(() => { userInteractedRef.current = true; renditionRef.current?.prev(); }, []);
  // Resolve a TOC href to something epub.js can actually display. TOC hrefs
  // often don't match spine href keys exactly (directory prefixes, encoding, or
  // anchors into a shared file), which makes display() silently do nothing.
  const resolveHref = useCallback((href: string): string => {
    const b = bookRef.current;
    if (!b || !href) return href;
    const [path, frag] = href.split("#");
    const suffix = frag ? `#${frag}` : "";
    try {
      let s = b.spine.get(href) || b.spine.get(path) || b.spine.get(decodeURI(path));
      if (!s) {
        const base = path.split("/").pop();
        const items = b.spine.spineItems || [];
        s = items.find((it: any) => (it.href || "").split("/").pop() === base);
      }
      if (s) return s.href + suffix;
    } catch {}
    return href;
  }, []);

  const goTo = useCallback(async (href: string) => {
    const r = renditionRef.current;
    if (!r || !href) return;
    userInteractedRef.current = true;
    const target = resolveHref(href);
    try {
      await r.display(target);
    } catch {
      try { await r.display(target.split("#")[0]); } catch (e) { console.error("TOC nav failed", href, e); }
    }
    setShowToc(false);
  }, [resolveHref]);

  // Full-text search across the whole book (epub.js section.find → cfi + excerpt).
  const runSearch = useCallback(async (q: string) => {
    const book = bookRef.current;
    const query = q.trim();
    if (!book || query.length < 2) { setSearchResults([]); return; }
    setSearching(true);
    setSearchResults([]);
    const results: { cfi: string; excerpt: string }[] = [];
    try {
      const items = book.spine?.spineItems || [];
      for (const item of items) {
        try {
          await item.load(book.load.bind(book));
          const found = item.find(query) || [];
          for (const f of found) results.push({ cfi: f.cfi, excerpt: (f.excerpt || "").trim() });
          item.unload();
        } catch { /* skip section */ }
        if (results.length >= 300) break;
      }
    } finally {
      setSearchResults(results);
      setSearching(false);
    }
  }, []);

  const goToCfi = useCallback(async (cfi: string) => {
    const r = renditionRef.current; if (!r) return;
    userInteractedRef.current = true;
    try {
      await r.display(cfi);
      if (lastHighlight.current) { try { r.annotations.remove(lastHighlight.current, "highlight"); } catch {} }
      try { r.annotations.highlight(cfi); lastHighlight.current = cfi; } catch {}
    } catch {}
    setShowSearch(false);
  }, []);

  const applyTheme = useCallback((t: Theme) => {
    const r = renditionRef.current; if (!r) return;
    r.themes.override("color", THEMES[t].color);
    r.themes.override("background", THEMES[t].bg);
  }, []);

  // Load saved prefs once.
  useEffect(() => {
    try {
      const fs = localStorage.getItem("reader.fontSize"); if (fs) setFontSize(Number(fs));
      const th = localStorage.getItem("reader.theme") as Theme | null; if (th) setTheme(th);
      const fl = localStorage.getItem("reader.flow") as any; if (fl) setFlow(fl);
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    let rendition: any;

    async function snapToHeading(cfi: string) {
      try {
        const contents = rendition.getContents()[0];
        if (!contents) return;
        const headings = Array.from(contents.document.querySelectorAll("h1,h2,h3,h4,h5,h6"));
        if (!headings.length) return;
        const range = contents.range(cfi);
        const cur = range && range.startContainer;
        if (!cur) return;
        let best: any = null;
        for (const h of headings as any[]) {
          // DOCUMENT_POSITION_FOLLOWING (4): `cur` comes after `h` → h precedes cur.
          if (h.compareDocumentPosition(cur) & 4) best = h; else break;
        }
        if (best) {
          const hcfi = contents.cfiFromNode(best);
          if (hcfi) await rendition.display(hcfi);
        }
      } catch {}
    }

    (async () => {
      try {
        const ePub = (await import("epubjs")).default as any;
        const res = await fetch(`/api/books/${bookId}/file/epub`);
        if (!res.ok) throw new Error(res.status === 404 ? "No EPUB available for this book" : `Failed to load (${res.status})`);
        const buf = await res.arrayBuffer();
        if (cancelled) return;

        const book = ePub(buf);
        bookRef.current = book;
        rendition = book.renderTo(viewerRef.current, {
          width: "100%", height: "100%", flow, spread: "none",
        });
        renditionRef.current = rendition;
        // Keep images (covers especially) within the page and undistorted.
        rendition.themes.default({
          "body": { "margin": "0 auto !important", "padding": "0 10px !important" },
          "img, image, svg": { "max-width": "100% !important", "max-height": "96vh !important" },
          "img": { "height": "auto !important", "object-fit": "contain !important" },
          "svg": { "height": "auto !important" },
        });
        // Many EPUB covers are a full-page <svg> whose <image> uses a
        // preserveAspectRatio that stretches it (CSS can't fix that attribute).
        // Force aspect-preserving fit on every rendered section's cover SVG.
        rendition.hooks.content.register((contents: any) => {
          try {
            contents.document.querySelectorAll("svg, svg image").forEach((el: Element) => {
              el.setAttribute("preserveAspectRatio", "xMidYMid meet");
            });
          } catch {}
        });
        rendition.themes.fontSize(`${fontSize}%`);
        rendition.themes.override("line-height", "1.6");
        applyTheme(theme);

        await rendition.display();
        await book.ready;

        // Table of contents (flattened, with nesting depth).
        try {
          const nav = await book.loaded.navigation;
          const flat: { label: string; href: string; depth: number }[] = [];
          const walk = (items: any[], d: number) => items?.forEach((it: any) => {
            if (it.label && it.label.trim()) flat.push({ label: it.label.trim(), href: it.href, depth: d });
            if (it.subitems?.length) walk(it.subitems, d + 1);
          });
          walk(nav.toc, 0);
          if (!cancelled) setToc(flat);
        } catch {}

        // Locations power the % readout and percentage-based resume. Load the
        // cached index if present; otherwise DON'T block the open on generating
        // it (that's the slow part on a first open) — we build it in the
        // background once the book is on screen, below.
        const cacheKey = `reader.loc.${bookId}`;
        let locationsReady = false;
        try {
          const cached = localStorage.getItem(cacheKey);
          if (cached) { book.locations.load(cached); locationsReady = true; }
        } catch {}
        // Generate-on-demand, idempotent: the percentage-resume fallback and the
        // background warm-up below share this single promise (never double-run).
        let locGen: Promise<void> | null = null;
        const ensureLocations = (): Promise<void> => {
          if (locationsReady) return Promise.resolve();
          if (!locGen) {
            locGen = book.locations.generate(1024).then(() => {
              locationsReady = true;
              try { localStorage.setItem(cacheKey, book.locations.save()); } catch {}
            });
          }
          return locGen as Promise<void>;
        };
        // Resume to a stored percentage WITHOUT blocking the open: the book is
        // already on page 1, so we let the index build in the background and jump
        // to the exact spot once it's ready — unless the reader has meanwhile
        // started turning pages (then we leave them where they are).
        const resumeByPercentage = (pct: number) => {
          ensureLocations().then(() => {
            if (cancelled || userInteractedRef.current) return;
            try {
              const cfi = book.locations.cfiFromPercentage(pct);
              return rendition.display(cfi).then(() => snapToHeading(cfi));
            } catch {}
          }).catch(() => {});
        };
        if (cancelled) return;

        // Resume. Priority:
        //  1. Browser's own exact CFI if it's the most recent edit.
        //  2. KOReader's position → its xpointer encodes the chapter as
        //     DocFragment[N] (N = spine index + 1). Open that chapter directly —
        //     this is accurate, unlike mapping KOReader's percentage (whose
        //     scale doesn't match epub.js) which landed a chapter off.
        //  3. Fall back to percentage → nearest heading.
        const prog = await api.bookProgress(bookId, "epub");
        const br = prog.browser, sy = prog.synced;
        const brTs = br?.ts ?? -1, syTs = sy?.ts ?? -1;

        const chapterIndexFromXpointer = (xp?: string): number | null => {
          const m = /DocFragment\[(\d+)\]/.exec(xp || "");
          return m ? parseInt(m[1], 10) - 1 : null;  // 0-based spine index
        };

        try {
          if (br?.cfi && brTs >= syTs) {
            await rendition.display(br.cfi);
          } else if (sy) {
            const idx = chapterIndexFromXpointer(sy.progress);
            const section = idx != null ? book.spine.get(idx) : null;
            if (section && section.href) {
              await rendition.display(section.href);  // chapter start — accurate
            } else if (sy.percentage != null) {
              resumeByPercentage(sy.percentage);
            }
          } else if (br?.percentage != null) {
            resumeByPercentage(br.percentage);
          }
        } catch { /* fall back to start */ }

        // Only start saving AFTER resume, so the initial render can't overwrite
        // the stored position.
        readyRef.current = true;
        rendition.on("relocated", (loc: any) => {
          const cfi = loc?.start?.cfi;
          if (!cfi || !readyRef.current) return;
          const p = book.locations.percentageFromCfi(cfi) ?? loc.start.percentage ?? 0;
          setPct(Math.round(p * 100));
          // KOReader applies `progress` as a crengine xpointer — give it the
          // current chapter (DocFragment N = spine index + 1) so it lands in the
          // right chapter instead of resetting to the start.
          const idx = loc.start.index ?? 0;
          const ko = `/body/DocFragment[${idx + 1}]/body`;
          if (saveTimer.current) clearTimeout(saveTimer.current);
          saveTimer.current = setTimeout(() => api.saveBookProgress(bookId, p, cfi, ko, "epub"), 1000);
        });

        const onKey = (e: KeyboardEvent) => {
          if (e.key === "ArrowRight") { userInteractedRef.current = true; rendition.next(); }
          if (e.key === "ArrowLeft") { userInteractedRef.current = true; rendition.prev(); }
        };
        rendition.on("keyup", onKey);
        document.addEventListener("keyup", onKey);

        setLoading(false);

        // Build the location index in the background so the % readout fills in
        // shortly — without holding up the open. No-op if it was loaded from
        // cache or already generated for a percentage resume above. (Until it's
        // ready, the relocated handler falls back to epub.js's own percentage.)
        if (!locationsReady && !cancelled) {
          ensureLocations().catch(() => {});
        }

        // Arriving from a global search → open the search panel and run it.
        if (initialQ.trim()) {
          setSearchQ(initialQ);
          setShowSearch(true);
          runSearch(initialQ);
        }
      } catch (e: any) {
        if (!cancelled) { setError(e.message ?? "Could not open book"); setLoading(false); }
      }
    })();

    return () => {
      cancelled = true;
      readyRef.current = false;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      try { rendition?.destroy(); } catch {}
    };
    // Re-create the rendition only on book change; flow change handled separately.
  }, [bookId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Live-apply font size.
  useEffect(() => {
    renditionRef.current?.themes.fontSize(`${fontSize}%`);
    try { localStorage.setItem("reader.fontSize", String(fontSize)); } catch {}
  }, [fontSize]);

  // Live-apply theme.
  useEffect(() => {
    applyTheme(theme);
    try { localStorage.setItem("reader.theme", theme); } catch {}
  }, [theme, applyTheme]);

  // Live-apply flow (re-render at current spot).
  useEffect(() => {
    const r = renditionRef.current; if (!r || !readyRef.current) return;
    try { localStorage.setItem("reader.flow", flow); } catch {}
    const cur = r.currentLocation()?.start?.cfi;
    try { r.flow(flow); if (cur) r.display(cur); } catch {}
  }, [flow]);

  const bg = THEMES[theme].bg;

  return (
    <div className="fixed inset-0 flex flex-col" style={{ background: "var(--ink)" }}>
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0"
           style={{ borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
        <div className="flex items-center gap-3">
          <a href={`/books/${bookId}`} className="inline-flex items-center gap-2 hover:underline"
             style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}>
            <ArrowLeft className="w-3.5 h-3.5" /> Back
          </a>
          <button onClick={() => setShowToc(true)} disabled={!toc.length}
            className="inline-flex items-center gap-1.5 disabled:opacity-30"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}
            aria-label="Table of contents">
            <List className="w-4 h-4" /> Contents
          </button>
          <button onClick={() => setShowSearch(true)}
            className="inline-flex items-center gap-1.5"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}
            aria-label="Search in book">
            <Search className="w-4 h-4" /> Search
          </button>
          <button onClick={() => setFlow(flow === "scrolled-doc" ? "paginated" : "scrolled-doc")}
            className="inline-flex items-center gap-1.5"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }}
            aria-label="Toggle scroll / paged view" title={flow === "scrolled-doc" ? "Switch to paged view" : "Switch to scroll view"}>
            {flow === "scrolled-doc" ? <FileText className="w-4 h-4" /> : <ScrollText className="w-4 h-4" />} {flow === "scrolled-doc" ? "Paged" : "Scroll"}
          </button>
        </div>
        <div className="flex items-center gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span
              title="Reading position syncs exactly between KOReader devices, and between browser sessions. When you switch between this in-browser reader and KOReader, it resumes at the nearest chapter — the two readers track position differently."
              style={{ color: "var(--parchment-dim)", cursor: "help", display: "inline-flex", opacity: 0.6 }}>
              <Info className="w-3.5 h-3.5" />
            </span>
            <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>{pct}%</span>
          </span>
          <button onClick={() => setShowSettings(s => !s)} style={{ color: "var(--parchment-dim)" }} aria-label="Reader settings">
            <Settings2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Table of contents drawer */}
      {showToc && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowToc(false)}
               style={{ background: "rgba(0,0,0,0.5)" }} />
          <div className="fixed top-0 left-0 z-50 h-full w-80 max-w-[85vw] flex flex-col"
               style={{ background: "var(--ink-soft)", borderRight: "1px solid var(--ink-muted)" }}>
            <div className="flex items-center justify-between px-4 py-3 border-b shrink-0" style={{ borderColor: "var(--ink-muted)" }}>
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Contents</span>
              <button onClick={() => setShowToc(false)} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
            </div>
            <div className="flex-1 overflow-y-auto py-2">
              {toc.map((t, i) => (
                t.href ? (
                  <button key={i} onClick={() => goTo(t.href)}
                    className="block w-full text-left px-4 py-2 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
                    style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment-dim)",
                             paddingLeft: `${1 + t.depth * 0.9}rem` }}>
                    {t.label}
                  </button>
                ) : (
                  <div key={i} className="px-4 py-2"
                    style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", letterSpacing: "0.04em",
                             textTransform: "uppercase", color: "var(--parchment-dim)", opacity: 0.5,
                             paddingLeft: `${1 + t.depth * 0.9}rem` }}>
                    {t.label}
                  </div>
                )
              ))}
            </div>
          </div>
        </>
      )}

      {/* Search drawer */}
      {showSearch && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowSearch(false)} style={{ background: "rgba(0,0,0,0.5)" }} />
          <div className="fixed top-0 right-0 z-50 h-full w-96 max-w-[90vw] flex flex-col"
               style={{ background: "var(--ink-soft)", borderLeft: "1px solid var(--ink-muted)" }}>
            <div className="flex items-center justify-between px-4 py-3 border-b shrink-0" style={{ borderColor: "var(--ink-muted)" }}>
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Search in book</span>
              <button onClick={() => setShowSearch(false)} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
            </div>
            <form className="px-4 py-3 border-b shrink-0 flex gap-2" style={{ borderColor: "var(--ink-muted)" }}
                  onSubmit={e => { e.preventDefault(); runSearch(searchQ); }}>
              <input autoFocus value={searchQ} onChange={e => setSearchQ(e.target.value)}
                placeholder="Find a word or phrase…"
                className="flex-1 px-2 py-1.5 rounded-sm outline-none"
                style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)", color: "var(--parchment)", fontFamily: "var(--body)", fontSize: "0.9rem" }} />
              <button type="submit" className="px-3 rounded-sm" style={{ background: "var(--gold-dim)", color: "var(--gold-light)" }}><Search className="w-4 h-4" /></button>
            </form>
            <div className="flex-1 overflow-y-auto">
              {searching ? (
                <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
              ) : searchResults.length === 0 ? (
                <div className="px-4 py-8 text-center" style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                  {searchQ.trim().length >= 2 ? "No matches." : "Type at least 2 characters."}
                </div>
              ) : (
                <>
                  <div className="px-4 py-2" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
                    {searchResults.length}{searchResults.length >= 300 ? "+" : ""} result{searchResults.length === 1 ? "" : "s"}
                  </div>
                  {searchResults.map((r, i) => (
                    <button key={i} onClick={() => goToCfi(r.cfi)}
                      className="block w-full text-left px-4 py-2.5 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
                      style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)", borderBottom: "1px solid var(--ink-muted)" }}>
                      …{r.excerpt}…
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>
        </>
      )}

      {/* Settings panel */}
      {showSettings && (
        <div className="flex flex-wrap items-center gap-4 px-4 py-2 border-b shrink-0"
             style={{ borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
          <div className="flex items-center gap-2">
            <span style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)" }}>Font</span>
            <button onClick={() => setFontSize(s => Math.max(70, s - 10))} className="p-1 rounded-sm" style={{ background: "var(--ink-muted)", color: "var(--parchment)" }}><Minus className="w-3.5 h-3.5" /></button>
            <span style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", width: "2.5rem", textAlign: "center" }}>{fontSize}%</span>
            <button onClick={() => setFontSize(s => Math.min(220, s + 10))} className="p-1 rounded-sm" style={{ background: "var(--ink-muted)", color: "var(--parchment)" }}><Plus className="w-3.5 h-3.5" /></button>
          </div>
          <div className="flex items-center gap-1.5">
            {(["light", "sepia", "dark"] as Theme[]).map(t => (
              <button key={t} onClick={() => setTheme(t)}
                className="px-2.5 py-1 rounded-sm border"
                style={{ fontFamily: "var(--mono)", fontSize: "0.65rem",
                         borderColor: theme === t ? "var(--gold)" : "var(--ink-muted)",
                         color: theme === t ? "var(--gold-light)" : "var(--parchment-dim)",
                         background: THEMES[t].bg, textTransform: "capitalize" }}>
                <span style={{ color: THEMES[t].color }}>{t}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Reading surface */}
      <div className="relative flex-1 min-h-0" style={{ background: bg }}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-20" style={{ color: "#8a7d63" }}>
            <Loader2 className="w-6 h-6 animate-spin" />
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center px-6 text-center z-20"
               style={{ fontFamily: "var(--body)", color: "#8a7d63" }}>{error}</div>
        )}

        <button onClick={prev} aria-label="Previous page"
          className="absolute left-0 top-0 h-full w-[15%] z-10 flex items-center justify-start pl-2 opacity-0 hover:opacity-100 transition-opacity"
          style={{ color: "#8a7d63" }}><ChevronLeft className="w-6 h-6" /></button>
        <button onClick={next} aria-label="Next page"
          className="absolute right-0 top-0 h-full w-[15%] z-10 flex items-center justify-end pr-2 opacity-0 hover:opacity-100 transition-opacity"
          style={{ color: "#8a7d63" }}><ChevronRight className="w-6 h-6" /></button>

        <div className="mx-auto h-full" style={{ maxWidth: "44rem" }}>
          <div ref={viewerRef} className="h-full" />
        </div>
      </div>
    </div>
  );
}
