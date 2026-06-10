/** Built-in Read/Unread filter — a segmented pill control matching the Format
 *  filter. Spans digital (Calibre) + physical (native) via the unified read
 *  status. Sets ?read=read|reading|unread. */
const OPTIONS: [string, string][] = [["", "All"], ["read", "Read"], ["unread", "Unread"]];

export function ReadFilter({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const current = searchParams.read || "";
  const hrefFor = (value: string) => {
    const p = new URLSearchParams(Object.entries(searchParams).filter(([, v]) => v) as [string, string][]);
    if (value) p.set("read", value); else p.delete("read");
    p.delete("page");
    return `/?${p}`;
  };
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", opacity: 0.5 }}>read</span>
      <div className="flex items-center gap-1" style={{ fontFamily: "var(--mono)", fontSize: "0.65rem" }}>
        {OPTIONS.map(([val, label]) => {
          const active = current === val;
          return (
            <a key={val || "all"} href={hrefFor(val)}
              className="px-2 py-1 rounded-sm transition-colors"
              style={{
                background: active ? "rgba(107,78,30,0.4)" : "transparent",
                color: active ? "var(--gold-light)" : "var(--parchment-dim)",
                border: `1px solid ${active ? "var(--gold-dim)" : "var(--ink-muted)"}`,
              }}>
              {label}
            </a>
          );
        })}
      </div>
    </div>
  );
}
