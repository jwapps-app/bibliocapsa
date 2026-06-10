"use client";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

// Phone: 2-5, Tablet/Desktop: 5-8
const MOBILE_OPTIONS = [2, 3, 4, 5];
const DESKTOP_OPTIONS = [5, 6, 7, 8];

function Btn({ n, current, set }: { n: number; current: number; set: (n: number) => void }) {
  return (
    <button onClick={() => set(n)}
      className="w-6 h-6 rounded-sm transition-colors flex items-center justify-center"
      style={{
        background: current === n ? "rgba(107,78,30,0.4)" : "transparent",
        color: current === n ? "var(--gold-light)" : "var(--parchment-dim)",
        border: `1px solid ${current === n ? "var(--gold-dim)" : "var(--ink-muted)"}`,
        fontFamily: "var(--mono)", fontSize: "0.65rem",
      }}>
      {n}
    </button>
  );
}

function ColumnPickerInner({ current }: { current: number }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const set = (n: number) => {
    // Persist as a cookie so the choice survives navigating away and back
    // (the server reads it as the default when the URL has no ?cols param).
    document.cookie = `cols=${n}; path=/; max-age=31536000; samesite=lax`;
    const params = new URLSearchParams(searchParams.toString());
    params.set("cols", String(n));
    startTransition(() => router.push(`?${params}`));
  };

  return (
    <div className="flex items-center gap-1.5" style={{color:"var(--parchment-dim)"}}>
      <span style={{fontFamily:"var(--mono)",fontSize:"0.6rem",opacity:0.5}}>cols</span>
      {/* Mobile only: 2-5 */}
      <div className="flex items-center gap-1 lg:hidden">
        {MOBILE_OPTIONS.map(n => <Btn key={n} n={n} current={current} set={set} />)}
      </div>
      {/* Desktop/iPad only: 5-8 */}
      <div className="hidden lg:flex items-center gap-1">
        {DESKTOP_OPTIONS.map(n => <Btn key={n} n={n} current={current} set={set} />)}
      </div>
    </div>
  );
}

export function ColumnPicker({ current }: { current: number }) {
  return (
    <Suspense fallback={null}>
      <ColumnPickerInner current={current} />
    </Suspense>
  );
}
