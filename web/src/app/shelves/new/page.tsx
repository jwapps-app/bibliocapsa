"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Autocomplete } from "@/components/MetaInputs";
import { ArrowLeft, Plus, Trash2, Sparkles, Loader2 } from "lucide-react";

type FieldType = "text" | "rating" | "date" | "bool" | "number";
interface FieldDef { key: string; label: string; type: FieldType; }

const OPS: Record<FieldType, { value: string; label: string }[]> = {
  text:   [{ value: "is", label: "is" }, { value: "is_not", label: "is not" }, { value: "contains", label: "contains" }],
  rating: [{ value: "gte", label: "at least" }, { value: "lte", label: "at most" }, { value: "is", label: "exactly" }],
  number: [{ value: "gte", label: "at least" }, { value: "lte", label: "at most" }, { value: "is", label: "is" }],
  date:   [{ value: "after", label: "on/after" }, { value: "before", label: "on/before" }],
  bool:   [{ value: "is_true", label: "is yes" }, { value: "is_false", label: "is no" }],
};

const DT_TO_TYPE = (dt: string): FieldType =>
  dt === "bool" ? "bool" : dt === "datetime" ? "date" : (dt === "int" || dt === "float" || dt === "rating") ? "number" : "text";

export default function NewSmartShelfPage() {
  const [name, setName] = useState("");
  const [match, setMatch] = useState<"all" | "any">("all");
  const [conds, setConds] = useState<{ field: string; op: string; value: string }[]>([{ field: "tag", op: "is", value: "" }]);
  const [fields, setFields] = useState<FieldDef[]>([]);
  const [suggest, setSuggest] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    const base: FieldDef[] = [
      { key: "tag", label: "Genre", type: "text" },
      { key: "author", label: "Author", type: "text" },
      { key: "series", label: "Series", type: "text" },
      { key: "publisher", label: "Publisher", type: "text" },
      { key: "rating", label: "Rating (★)", type: "rating" },
      { key: "pubdate", label: "Published date", type: "date" },
      { key: "title", label: "Title", type: "text" },
    ];
    api.customColumns()
      .then(cols => setFields([...base, ...cols.map(c => ({ key: `custom:${c.label}`, label: c.name, type: DT_TO_TYPE(c.datatype) }))]))
      .catch(() => setFields(base));
    // Suggestion lists for the "pick a known thing" fields, keyed by field name.
    api.tags().then(ts => setSuggest(s => ({ ...s, tag: ts.map(t => t.name) }))).catch(() => {});
    api.authors({ page_size: 5000 }).then(a => setSuggest(s => ({ ...s, author: a.map(x => x.name) }))).catch(() => {});
    api.series({ page_size: 5000 }).then(se => setSuggest(s => ({ ...s, series: se.map(x => x.name) }))).catch(() => {});
    api.publishers().then(p => setSuggest(s => ({ ...s, publisher: p.map(x => x.name) }))).catch(() => {});
  }, []);

  const fieldDef = (key: string) => fields.find(f => f.key === key) ?? { key, label: key, type: "text" as FieldType };
  const typeOf = (key: string) => fieldDef(key).type;

  const update = (i: number, patch: Partial<{ field: string; op: string; value: string }>) => {
    setConds(cs => cs.map((c, j) => {
      if (j !== i) return c;
      const next = { ...c, ...patch };
      if (patch.field) next.op = OPS[typeOf(patch.field)][0].value;  // reset op to a valid one
      return next;
    }));
  };

  const buildConditions = () => conds
    .filter(c => c.field && (["is_true", "is_false", "is_set", "not_set"].includes(c.op) || c.value.trim() !== ""))
    .map(c => ({ field: c.field, op: c.op, value: c.value }));

  // Live count preview (debounced).
  useEffect(() => {
    const conditions = buildConditions();
    if (conditions.length === 0) { setCount(null); return; }
    const t = setTimeout(() => {
      api.previewShelf({ type: "query", match, conditions }).then(setCount).catch(() => setCount(null));
    }, 400);
    return () => clearTimeout(t);
  }, [conds, match]);

  const save = async () => {
    if (!name.trim()) { setErr("Give the shelf a name."); return; }
    setBusy(true); setErr(null);
    const conditions = buildConditions();
    if (conditions.length === 0) { setErr("Add at least one condition with a value."); setBusy(false); return; }
    try {
      const res = await fetch("/api/shelves", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), is_smart: true, smart_rules: { type: "query", match, conditions } }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not create shelf");
      const shelf = await res.json();
      window.location.href = `/?view=shelf&shelf=${shelf.id}`;
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <a href="/" className="inline-flex items-center gap-2 mb-6 hover:underline" style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-5 h-5" style={{ color: "var(--gold)" }} />
          <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }}>New smart shelf</h1>
        </div>
        <p className="mb-6" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.75 }}>
          A self-updating shelf built from rules — genres, ratings, series, or any Calibre custom column.
        </p>

        <label className="block mb-4">
          <span className="block uppercase tracking-widest mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>Shelf name</span>
          <input className="bc-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Unread Theology" />
        </label>

        <div className="mb-3 flex items-center gap-2" style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment-dim)" }}>
          Match
          <select className="bc-input" style={{ width: "auto", height: "2rem" }} value={match} onChange={e => setMatch(e.target.value as any)}>
            <option value="all">all</option>
            <option value="any">any</option>
          </select>
          of these conditions:
        </div>

        <div className="space-y-2 mb-4">
          {conds.map((c, i) => {
            const t = typeOf(c.field);
            const noValue = ["is_true", "is_false", "is_set", "not_set"].includes(c.op);
            return (
              <div key={i} className="flex flex-wrap items-center gap-2 p-2 rounded-sm border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                <select className="bc-input" style={{ width: "auto", flex: "1 1 8rem" }} value={c.field} onChange={e => update(i, { field: e.target.value })}>
                  {fields.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
                </select>
                <select className="bc-input" style={{ width: "auto" }} value={c.op} onChange={e => update(i, { op: e.target.value })}>
                  {OPS[t].map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                {!noValue && (
                  suggest[c.field]?.length ? (
                    <div style={{ flex: "1 1 8rem" }}>
                      <Autocomplete value={c.value} onChange={v => update(i, { value: v })}
                        suggestions={suggest[c.field]} placeholder={fieldDef(c.field).label.toLowerCase()} />
                    </div>
                  ) : (
                    <input className="bc-input" style={{ flex: "1 1 8rem" }}
                      type={t === "date" ? "date" : (t === "rating" || t === "number") ? "number" : "text"}
                      value={c.value} onChange={e => update(i, { value: e.target.value })}
                      placeholder={t === "rating" ? "1–5" : "value"} />
                  )
                )}
                {conds.length > 1 && (
                  <button onClick={() => setConds(cs => cs.filter((_, j) => j !== i))} style={{ color: "var(--parchment-dim)" }}><Trash2 className="w-4 h-4" /></button>
                )}
              </div>
            );
          })}
        </div>

        <button onClick={() => setConds(cs => [...cs, { field: "tag", op: "is", value: "" }])}
          className="inline-flex items-center gap-1.5 mb-6 px-3 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
          style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)" }}>
          <Plus className="w-3.5 h-3.5" /> Add condition
        </button>

        {err && <div className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "#d98a8a" }}>{err}</div>}

        <div className="flex items-center gap-3">
          <button onClick={save} disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Create smart shelf
          </button>
          {count !== null && (
            <span style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)" }}>
              {count.toLocaleString()} book{count === 1 ? "" : "s"} match
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
