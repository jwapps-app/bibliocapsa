"use client";

import { useState, useEffect } from "react";
import { Bookmark } from "lucide-react";
import { api } from "@/lib/api";

/** "Want to Read" toggle for an owned library book. Filled when on the list. */
export function BookmarkButton({ bookId, bookSource = "calibre", title, author }:
  { bookId: number; bookSource?: string; title: string; author?: string }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [wid, setWid] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.wishlistContains(bookId, bookSource)
      .then(r => { setOn(r.bookmarked); setWid(r.id); })
      .catch(() => setOn(false));
  }, [bookId, bookSource]);

  const toggle = async () => {
    if (on === null || busy) return;
    setBusy(true);
    try {
      if (on) {
        if (wid != null) await api.removeWishlist(wid);
        setOn(false); setWid(null);
      } else {
        const r = await api.addWishlist({ title, author, book_id: bookId, book_source: bookSource });
        setOn(true); setWid(r.id);
      }
    } finally { setBusy(false); }
  };

  return (
    <button onClick={toggle} disabled={on === null || busy}
      title={on ? "On your Want to Read list — click to remove" : "Add to Want to Read"}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
      style={{
        borderColor: on ? "var(--gold)" : "var(--ink-muted)",
        background: on ? "rgba(107,78,30,0.2)" : "transparent",
        fontFamily: "var(--mono)", fontSize: "0.72rem",
        color: on ? "var(--gold-light)" : "var(--parchment-dim)",
      }}>
      <Bookmark className="w-3.5 h-3.5" fill={on ? "currentColor" : "none"} />
      Want to Read
    </button>
  );
}
