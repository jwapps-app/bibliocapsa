"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

/** Compact toolbar dropdown(s) for filtering the library by a boolean Calibre
 *  custom column (e.g. Read/Unread). Sets ?custom=<label>:<value>. */
export function CustomFilter({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const [cols, setCols] = useState<{ label: string; name: string }[]>([]);

  useEffect(() => {
    api.customColumns()
      .then(cs => setCols(cs.filter(c => c.datatype === "bool").map(c => ({ label: c.label, name: c.name }))))
      .catch(() => {});
  }, []);

  if (!cols.length) return null;

  const current = searchParams.custom || "";
  const hrefFor = (label: string, value: string) => {
    const p = new URLSearchParams(Object.entries(searchParams).filter(([, v]) => v) as [string, string][]);
    if (value) p.set("custom", `${label}:${value}`); else p.delete("custom");
    p.delete("page");
    return `/?${p}`;
  };

  return (
    <>
      {cols.map(col => {
        const sel = current.startsWith(`${col.label}:`) ? current.split(":")[1] : "";
        return (
          <select key={col.label} value={sel}
            onChange={e => { window.location.href = hrefFor(col.label, e.target.value); }}
            title={col.name}
            style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: sel ? "var(--gold-light)" : "var(--parchment-dim)",
                     background: "transparent", border: "none", outline: "none", cursor: "pointer" }}>
            <option value="">{col.name}: All</option>
            <option value="1">{col.name}: Yes</option>
            <option value="0">{col.name}: No</option>
          </select>
        );
      })}
    </>
  );
}
