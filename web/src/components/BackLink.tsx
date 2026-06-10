"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

/** "Library" link that returns to the last recorded library view (preserving the
 *  format filter / search / author-series-tag), or `fallback` if none. Uses a
 *  direct push rather than history.back() so it never loops back into the reader. */
export function BackLink({ fallback = "/", label = "Library" }: { fallback?: string; label?: string }) {
  const router = useRouter();
  const go = () => {
    let dest = fallback;
    try { dest = sessionStorage.getItem("bc:lib") || fallback; } catch {}
    router.push(dest);
  };
  return (
    <button onClick={go}
      className="inline-flex items-center gap-2 transition-colors hover:underline"
      style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
      <ArrowLeft className="w-3.5 h-3.5" />
      {label}
    </button>
  );
}
