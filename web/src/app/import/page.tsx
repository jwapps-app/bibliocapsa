"use client";
import { useState, useRef, useEffect } from "react";
import { Upload, CheckCircle, AlertCircle, Loader, Trash2 } from "lucide-react";

export default function ImportPage() {
  const [status, setStatus] = useState<"idle"|"selecting"|"uploading"|"running"|"complete"|"error">("idle");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string>("");
  const [progress, setProgress] = useState(0);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<any>(null);
  const [undoing, setUndoing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // Physical-shelf selection step
  const [file, setFile] = useState<File | null>(null);
  const [shelves, setShelves] = useState<{ name: string; count: number }[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [previewing, setPreviewing] = useState(false);
  const [autoEnrich, setAutoEnrich] = useState(true);

  // Poll the server for import progress (works whether the import was started
  // here or is already running from a previous visit).
  const startPolling = () => {
    const poll = setInterval(async () => {
      const s = await fetch("/api/goodreads/import/status").then(r => r.json());
      setProgress(s.progress ?? 0);
      setTotal(s.total ?? 0);
      if (s.status === "complete") {
        clearInterval(poll);
        setStatus("complete");
        setResult(s.result);
        fetch("/api/goodreads/import/summary").then(r => r.json()).then(setSummary);
      } else if (s.status === "error") {
        clearInterval(poll);
        setStatus("error");
        setError(s.error ?? "Unknown error");
      }
    }, 500);
  };

  useEffect(() => {
    fetch("/api/goodreads/import/summary").then(r => r.json()).then(setSummary).catch(() => {});
    // Re-attach to an import still running on the server (e.g. after navigating
    // away and back) so live progress shows again instead of the upload screen.
    fetch("/api/goodreads/import/status").then(r => r.json()).then(s => {
      if (s.status === "running") {
        setStatus("running"); setProgress(s.progress ?? 0); setTotal(s.total ?? 0); startPolling();
      }
    }).catch(() => {});
  }, []);

  // Step 1: read the shelves out of the chosen CSV so the user can mark which
  // ones mean "physically owned".
  const onFile = async (f: File) => {
    setFile(f);
    setStatus("selecting");
    setPreviewing(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await fetch("/api/goodreads/preview-shelves", { method: "POST", body: form });
      const data = await res.json();
      setShelves(data.shelves ?? []);
      setSelected(new Set(data.saved_physical ?? []));
      setAutoEnrich(data.auto_enrich ?? true);
    } catch {
      setShelves([]);
    } finally {
      setPreviewing(false);
    }
  };

  const toggle = (name: string) =>
    setSelected(prev => { const n = new Set(prev); n.has(name) ? n.delete(name) : n.add(name); return n; });

  // Step 2: run the import with the selected physical shelves.
  const upload = async (f: File, physical: string[]) => {
    setStatus("uploading");
    setError("");
    try {
      const form = new FormData();
      form.append("file", f);
      form.append("physical_shelves", physical.join(","));
      form.append("auto_enrich", String(autoEnrich));
      const res = await fetch("/api/goodreads/import", { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      setStatus("running");
      startPolling();
    } catch (e: any) {
      setStatus("error");
      setError(e.message);
    }
  };

  const undo = async () => {
    if (!confirm("This will remove all imported Goodreads data — ratings, shelves, ownership info, and physical books added by the import. Continue?")) return;
    setUndoing(true);
    try {
      const res = await fetch("/api/goodreads/import", { method: "DELETE" });
      const data = await res.json();
      setSummary({ imported: false });
      setStatus("idle");
      setResult(null);
      alert(`Done. Removed ${data.shelves_removed} shelves and ${data.native_books_removed} physical books.`);
    } catch (e: any) {
      alert(`Undo failed: ${e.message}`);
    } finally {
      setUndoing(false);
    }
  };

  const StatRow = ({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) => (
    <div className="flex items-center justify-between py-1.5 border-b" style={{borderColor:"var(--ink-muted)"}}>
      <span style={{fontFamily:"var(--body)",fontSize:"0.95rem",color:"var(--parchment-dim)"}}>{label}</span>
      <span style={{fontFamily:"var(--mono)",fontSize:"0.9rem",color: highlight ? "var(--gold-light)" : "var(--parchment-dim)"}}>{value?.toLocaleString()}</span>
    </div>
  );

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8">
          <a href="/" style={{fontFamily:"var(--mono)",fontSize:"0.8rem",color:"var(--parchment-dim)",opacity:0.6}}>← Library</a>
        </div>

        <h1 style={{fontFamily:"var(--serif)",fontSize:"2rem",color:"var(--parchment)"}} className="mb-2">Goodreads Import</h1>
        <p style={{fontFamily:"var(--body)",fontSize:"1rem",color:"var(--parchment-dim)",opacity:0.7}} className="mb-8">
          Import your reading history, ratings, and shelves. Export from Goodreads → My Books → Import and Export → Export Library.
        </p>

        {/* Existing import summary */}
        {summary?.imported && status === "idle" && (
          <div className="rounded-sm p-5 mb-6 border" style={{background:"var(--ink-soft)",borderColor:"var(--ink-muted)"}}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4" style={{color:"var(--gold)"}} />
                <span style={{fontFamily:"var(--serif)",fontSize:"1rem",color:"var(--parchment)"}}>Goodreads data imported</span>
              </div>
              <button onClick={undo} disabled={undoing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm transition-colors hover:opacity-80 disabled:opacity-40"
                style={{background:"rgba(120,40,40,0.3)",border:"1px solid rgba(150,50,50,0.4)",fontFamily:"var(--mono)",fontSize:"0.7rem",color:"#e08080"}}>
                {undoing ? <Loader className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                Undo Import
              </button>
            </div>
            <StatRow label="Books imported" value={summary.total} />
            <StatRow label="Matched to Calibre" value={summary.matched_to_calibre} />
            <StatRow label="Owned in both formats" value={summary.dual_format} highlight />
            <StatRow label="Physical books added" value={summary.native_books} />
            <StatRow label="Shelves created" value={summary.shelves} />
            <StatRow label="Ratings imported" value={summary.ratings} />
            <p className="mt-3" style={{fontFamily:"var(--mono)",fontSize:"0.65rem",color:"var(--parchment-dim)",opacity:0.4}}>
              Undo first to reimport a new CSV.
            </p>
          </div>
        )}

        {/* Upload */}
        {status === "idle" && (
          <div onClick={() => fileRef.current?.click()}
            className="border-2 border-dashed rounded-sm p-12 text-center cursor-pointer transition-colors hover:border-[var(--gold-dim)]"
            style={{borderColor:"var(--ink-muted)",background:"var(--ink-soft)"}}>
            <Upload className="w-8 h-8 mx-auto mb-3" style={{color:"var(--parchment-dim)",opacity:0.4}} />
            <p style={{fontFamily:"var(--body)",fontSize:"1rem",color:"var(--parchment-dim)"}}>
              {summary?.imported ? "Upload a new CSV to reimport" : "Click to select your Goodreads CSV"}
            </p>
            <p style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)",opacity:0.4}} className="mt-1">goodreads_library_export.csv</p>
            <input ref={fileRef} type="file" accept=".csv" className="hidden"
              onChange={e => e.target.files?.[0] && onFile(e.target.files[0])} />
          </div>
        )}

        {/* Select which shelves mean "physically owned" */}
        {status === "selecting" && (
          <div className="rounded-sm p-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
            <h2 style={{ fontFamily: "var(--serif)", fontSize: "1.2rem", color: "var(--parchment)" }} className="mb-1">
              Which shelves are physical copies?
            </h2>
            <p style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
              Check the Goodreads shelves that represent books you own <strong style={{ color: "var(--parchment)" }}>physically</strong> (often a room or location). Those books get marked as physical copies. Leave all unchecked if you only track digital.
            </p>
            {previewing ? (
              <div className="flex justify-center py-6"><Loader className="w-6 h-6 animate-spin" style={{ color: "var(--gold)" }} /></div>
            ) : shelves.length === 0 ? (
              <p style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)", opacity: 0.5 }} className="py-4">
                No shelves found in this file — you can still import (nothing will be marked physical).
              </p>
            ) : (
              <div className="space-y-1 max-h-72 overflow-y-auto pr-1">
                {shelves.map(s => {
                  const on = selected.has(s.name);
                  return (
                    <label key={s.name}
                      className="flex items-center justify-between gap-3 px-3 py-2 rounded-sm cursor-pointer transition-colors"
                      style={{ background: on ? "rgba(107,78,30,0.25)" : "transparent", border: `1px solid ${on ? "var(--gold-dim)" : "var(--ink-muted)"}` }}>
                      <span className="flex items-center gap-2 min-w-0">
                        <input type="checkbox" checked={on} onChange={() => toggle(s.name)} style={{ accentColor: "var(--gold)" }} />
                        <span className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: on ? "var(--gold-light)" : "var(--parchment)" }}>{s.name}</span>
                      </span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)", opacity: 0.5 }}>{s.count.toLocaleString()}</span>
                    </label>
                  );
                })}
              </div>
            )}
            <label className="flex items-start gap-2 mt-5 cursor-pointer">
              <input type="checkbox" checked={autoEnrich} onChange={e => setAutoEnrich(e.target.checked)}
                style={{ accentColor: "var(--gold)", marginTop: "3px" }} />
              <span style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment)" }}>
                Automatically fetch covers &amp; metadata
                <span className="block" style={{ fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                  Looks up missing cover art and details for the added books (Open Library, plus Hardcover if configured). Runs in the background.
                </span>
              </span>
            </label>
            <div className="flex items-center gap-3 mt-5">
              <button onClick={() => file && upload(file, [...selected])}
                className="px-4 py-2 rounded-sm hover:opacity-80 transition-opacity"
                style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.8rem" }}>
                Import {selected.size > 0 ? `(${selected.size} physical shelf${selected.size === 1 ? "" : "es"})` : "(digital only)"}
              </button>
              <button onClick={() => { setStatus("idle"); setFile(null); setShelves([]); setSelected(new Set()); }}
                className="px-4 py-2 rounded-sm transition-colors"
                style={{ background: "var(--ink-muted)", color: "var(--parchment-dim)", fontFamily: "var(--mono)", fontSize: "0.8rem" }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Running */}
        {(status === "uploading" || status === "running") && (
          <div className="rounded-sm p-8 text-center" style={{background:"var(--ink-soft)",border:"1px solid var(--ink-muted)"}}>
            <Loader className="w-8 h-8 mx-auto mb-4 animate-spin" style={{color:"var(--gold)"}} />
            <p style={{fontFamily:"var(--serif)",fontSize:"1.1rem",color:"var(--parchment)"}} className="mb-3">
              {status === "uploading" ? "Uploading…" : "Importing…"}
            </p>
            {total > 0 ? (
              <>
                <div className="w-full rounded-full h-1.5 mb-2" style={{background:"var(--ink-muted)"}}>
                  <div className="h-1.5 rounded-full transition-all" style={{width:`${(progress/total)*100}%`,background:"var(--gold)"}} />
                </div>
                <p style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)",opacity:0.6}}>
                  {progress >= total ? "Finalizing shelves & ownership…" : `${progress.toLocaleString()} / ${total.toLocaleString()} books`}
                </p>
              </>
            ) : (
              <p style={{fontFamily:"var(--mono)",fontSize:"0.7rem",color:"var(--parchment-dim)",opacity:0.6}}>Reading your file…</p>
            )}
            <p className="mt-4" style={{fontFamily:"var(--body)",fontSize:"0.8rem",color:"var(--parchment-dim)",opacity:0.5}}>
              This runs on the server — you can safely leave this page; the import will keep going.
            </p>
          </div>
        )}

        {/* Complete */}
        {status === "complete" && result && (
          <div className="rounded-sm p-8" style={{background:"var(--ink-soft)",border:"1px solid var(--ink-muted)"}}>
            <div className="flex items-center gap-3 mb-6">
              <CheckCircle className="w-6 h-6 shrink-0" style={{color:"var(--gold)"}} />
              <h2 style={{fontFamily:"var(--serif)",fontSize:"1.3rem",color:"var(--parchment)"}}>Import Complete</h2>
            </div>
            <StatRow label="Total books processed" value={result.total} />
            <StatRow label="Matched by Goodreads ID" value={result.matched_by_goodreads_id} />
            <StatRow label="Matched by ISBN" value={result.matched_by_isbn} />
            <StatRow label="Matched by title" value={result.matched_by_title} />
            <StatRow label="Owned in both formats" value={result.dual_format} highlight />
            <StatRow label="Physical only (added to library)" value={result.unmatched} />
            <StatRow label="Shelves created" value={result.shelves_created} />
            <div className="flex items-center gap-3 mt-6">
              <a href="/" className="px-4 py-2 rounded-sm hover:opacity-80 transition-opacity"
                style={{background:"var(--gold-dim)",color:"var(--gold-light)",fontFamily:"var(--mono)",fontSize:"0.8rem"}}>
                Back to Library
              </a>
              <button onClick={undo} disabled={undoing}
                className="flex items-center gap-1.5 px-4 py-2 rounded-sm hover:opacity-80 transition-opacity"
                style={{background:"rgba(120,40,40,0.3)",border:"1px solid rgba(150,50,50,0.4)",fontFamily:"var(--mono)",fontSize:"0.8rem",color:"#e08080"}}>
                <Trash2 className="w-3.5 h-3.5" />
                Undo Import
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {status === "error" && (
          <div className="rounded-sm p-8" style={{background:"var(--ink-soft)",border:"1px solid rgba(150,50,50,0.4)"}}>
            <div className="flex items-center gap-3 mb-4">
              <AlertCircle className="w-6 h-6" style={{color:"#c04040"}} />
              <h2 style={{fontFamily:"var(--serif)",fontSize:"1.3rem",color:"var(--parchment)"}}>Import Failed</h2>
            </div>
            <p style={{fontFamily:"var(--mono)",fontSize:"0.75rem",color:"var(--parchment-dim)",opacity:0.7}}>{error}</p>
            <button onClick={() => setStatus("idle")} className="mt-4 px-4 py-2 rounded-sm"
              style={{background:"var(--ink-muted)",color:"var(--parchment-dim)",fontFamily:"var(--mono)",fontSize:"0.8rem"}}>
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
