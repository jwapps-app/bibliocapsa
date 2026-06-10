"use client";
import { useState, useEffect } from "react";
import { BookMarked, Check } from "lucide-react";

interface Props { bookId: number; bookSource?: string; }

export function AddToShelf({ bookId, bookSource = "calibre" }: Props) {
  const [shelves, setShelves] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      fetch("/api/shelves")
        .then(r => r.json())
        .then(data => setShelves(data.filter((s: any) => !s.is_smart)))
        .catch(() => {});
    }
  }, [open]);

  const addToShelf = async (shelfId: number) => {
    setLoading(true);
    try {
      await fetch(`/api/shelves/${shelfId}/books`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: bookId, book_source: bookSource }),
      });
      setAdded(prev => new Set([...prev, shelfId]));
    } finally { setLoading(false); }
  };

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
        style={{fontFamily:"var(--mono)",fontSize:"0.72rem",color:"var(--parchment-dim)",borderColor:"var(--ink-muted)",background:"var(--ink-soft)"}}>
        <BookMarked className="w-3.5 h-3.5" />
        Add to shelf
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-30 rounded-sm border shadow-xl min-w-48"
          style={{background:"var(--ink-soft)",borderColor:"var(--ink-muted)"}}>
          {shelves.length === 0 ? (
            <div className="px-3 py-2" style={{fontFamily:"var(--body)",fontSize:"0.85rem",color:"var(--parchment-dim)",opacity:0.5}}>
              No shelves yet — create one in the sidebar
            </div>
          ) : (
            shelves.map(shelf => (
              <button key={shelf.id} onClick={() => addToShelf(shelf.id)} disabled={loading}
                className="w-full flex items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--ink-muted)]"
                style={{fontFamily:"var(--body)",fontSize:"0.9rem",color:"var(--parchment)"}}>
                <span>{shelf.name}</span>
                {added.has(shelf.id) && <Check className="w-3.5 h-3.5" style={{color:"var(--gold-light)"}} />}
              </button>
            ))
          )}
          <div className="border-t px-3 py-1.5" style={{borderColor:"var(--ink-muted)"}}>
            <button onClick={() => setOpen(false)}
              className="text-xs transition-opacity hover:opacity-80"
              style={{fontFamily:"var(--mono)",color:"var(--parchment-dim)",opacity:0.5}}>
              close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
