"use client";
import { Suspense } from "react";

interface Props {
  currentSort: string;
  currentDir: string;
  searchParams: Record<string, string | undefined>;
  options: { key: string; label: string }[];
}

function SortPickerInner({ currentSort, currentDir, searchParams, options }: Props) {
  return (
    <div className="lg:hidden">
      <select
        value={`${currentSort}|${currentDir}`}
        onChange={e => {
          const [sort_by, sort_dir] = e.target.value.split("|");
          const params = new URLSearchParams(
            Object.entries(searchParams).filter(([, v]) => v) as [string, string][]
          );
          params.set("sort_by", sort_by);
          params.set("sort_dir", sort_dir);
          window.location.href = `/?${params}`;
        }}
        style={{
          fontFamily: "var(--mono)", fontSize: "0.65rem",
          background: "var(--ink-muted)", color: "var(--parchment-dim)",
          border: "1px solid var(--ink-muted)", borderRadius: "2px",
          padding: "3px 4px",
        }}>
        {options.map(o => [
          <option key={`${o.key}|asc`} value={`${o.key}|asc`}>{o.label} ↑</option>,
          <option key={`${o.key}|desc`} value={`${o.key}|desc`}>{o.label} ↓</option>,
        ])}
      </select>
    </div>
  );
}

export function SortPicker(props: Props) {
  return (
    <Suspense fallback={null}>
      <SortPickerInner {...props} />
    </Suspense>
  );
}
