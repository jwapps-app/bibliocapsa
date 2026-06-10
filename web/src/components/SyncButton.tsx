"use client";

import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

/** Compact "Sync to Calibre" icon for the top header (admin only). Shows the
 *  pending-changes count as a badge; links to /sync (which has the confirm
 *  dialog / "close Calibre first" warning). */
export function SyncButton() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [count, setCount] = useState(0);

  useEffect(() => {
    api.me().then(u => {
      if (u?.role === "admin") { setIsAdmin(true); api.calibrePendingCount().then(setCount).catch(() => {}); }
    }).catch(() => {});
  }, []);

  if (!isAdmin) return null;

  return (
    <a href="/sync" title={count > 0 ? `Sync to Calibre — ${count} pending` : "Sync to Calibre"}
      className="relative inline-flex items-center justify-center p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
      style={{ color: count > 0 ? "var(--gold-light)" : "var(--parchment-dim)" }}>
      <RefreshCw className="w-4 h-4" />
      {count > 0 && (
        <span className="absolute -top-1 -right-1 flex items-center justify-center"
          style={{ minWidth: "15px", height: "15px", padding: "0 3px", borderRadius: "999px",
                   background: "var(--gold)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: "0.55rem", fontWeight: 700 }}>
          {count}
        </span>
      )}
    </a>
  );
}
