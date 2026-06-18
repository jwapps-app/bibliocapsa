"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

/** "Digital + Physical" badge for a Calibre book that's also flagged as owned in
 *  print. Admins get a control to drop the physical flag — the book stays as a
 *  normal digital book, and the badge disappears everywhere. Rendered only when
 *  the book is currently Digital + Physical (the page decides). */
export function PhysicalOwnership({ bookId, location }: { bookId: number; location?: string }) {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.me().then(u => setIsAdmin(u?.role === "admin")).catch(() => {}); }, []);

  if (removed) return null;

  const remove = async () => {
    if (!isAdmin || busy) return;
    if (!confirm("Remove the physical copy from this book? It stays in your library as a digital book.")) return;
    setBusy(true);
    try {
      await api.setCalibreOwnership(bookId, { has_physical: false });
      setRemoved(true);
      router.refresh();
    } catch (e: any) {
      setBusy(false);
      alert(e?.message ?? "Could not update ownership");
    }
  };

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1.5"
           style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
        <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
          <div style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#4a9aba" }} />
          <div style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#c9933a" }} />
        </div>
        <span>Digital + Physical{location ? ` · ${location}` : ""}</span>
      </div>
      {isAdmin && (
        <button onClick={remove} disabled={busy}
          className="underline disabled:opacity-50 hover:text-[var(--parchment)]"
          style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
          {busy ? "removing…" : "remove physical"}
        </button>
      )}
    </div>
  );
}
