"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

/** Goodreads-style clickable star rating for a Calibre book. Admins can set it
 *  inline — it queues a pending overlay edit (shown instantly, pushed to Calibre
 *  on the next Sync). Non-admins see it read-only. */
export function CalibreRating({ bookId, rating, community }: { bookId: number; rating?: number | null; community?: number | null }) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [hover, setHover] = useState(0);
  const [busy, setBusy] = useState(false);
  const current = rating ? Math.round(rating) : 0;

  useEffect(() => { api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {}); }, []);

  const set = async (n: number) => {
    if (!isAdmin || busy) return;
    const val = n === current ? 0 : n;  // clicking the current star clears it
    setBusy(true);
    try { await api.editCalibreBook(bookId, { rating: val }); window.location.reload(); }
    catch { setBusy(false); }
  };

  // Members: if unrated, fall back to the community rating (read-only).
  if (!isAdmin && current === 0) {
    return community ? (
      <div className="mb-4" style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--parchment-dim)" }} title="Community rating (Hardcover)">
        ★ {community.toFixed(1)} <span style={{ opacity: 0.6 }}>community</span>
      </div>
    ) : null;
  }

  const display = hover || current;
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map(n => (
          <button key={n} disabled={!isAdmin || busy}
            onMouseEnter={() => isAdmin && setHover(n)}
            onClick={() => set(n)}
            className={isAdmin ? "cursor-pointer" : "cursor-default"}
            style={{ lineHeight: 1, fontSize: "1.5rem", color: n <= display ? "var(--gold)" : "var(--ink-muted)", transition: "color 0.1s" }}
            aria-label={`${n} star${n > 1 ? "s" : ""}`}>★</button>
        ))}
        {isAdmin && current > 0 && (
          <span style={{ fontFamily: "var(--mono)", fontSize: "0.58rem", color: "var(--parchment-dim)", opacity: 0.45, marginLeft: "6px" }}>
            click again to clear
          </span>
        )}
      </div>
      {current === 0 && community != null && (
        <div className="mt-1" style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
          ★ {community.toFixed(1)} community
        </div>
      )}
    </div>
  );
}
