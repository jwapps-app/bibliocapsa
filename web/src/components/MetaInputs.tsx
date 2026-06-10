"use client";

import { useState } from "react";
import { X } from "lucide-react";

/** Chip-style tag input with live suggestions. Enter / Tab / comma / clicking a
 *  suggestion commits a chip and keeps the input focused for the next one. */
export function TagInput({ value, onChange, suggestions, placeholder }: {
  value: string[];
  onChange: (v: string[]) => void;
  suggestions: string[];
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);

  const lower = value.map(v => v.toLowerCase());
  const filtered = text.trim()
    ? suggestions.filter(s => s.toLowerCase().includes(text.toLowerCase()) && !lower.includes(s.toLowerCase())).slice(0, 8)
    : [];

  const add = (t: string) => {
    const tag = t.trim();
    if (tag && !lower.includes(tag.toLowerCase())) onChange([...value, tag]);
    setText("");
    setOpen(false);
  };
  const remove = (t: string) => onChange(value.filter(x => x !== t));

  return (
    <div className="relative">
      <div className="bc-input flex flex-wrap gap-1.5 items-center" style={{ minHeight: "2.4rem", height: "auto", paddingTop: "0.35rem", paddingBottom: "0.35rem" }}>
        {value.map(t => (
          <span key={t} className="inline-flex items-center gap-1 rounded-sm"
            style={{ background: "rgba(107,78,30,0.25)", border: "1px solid var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.68rem", padding: "1px 4px 1px 7px" }}>
            {t}
            <button type="button" onClick={() => remove(t)} style={{ lineHeight: 0, color: "var(--gold-light)", opacity: 0.7 }}><X className="w-3 h-3" /></button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[6rem] bg-transparent outline-none"
          style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment)" }}
          value={text}
          placeholder={value.length === 0 ? (placeholder ?? "Add a tag…") : ""}
          onChange={e => { setText(e.target.value); setOpen(true); }}
          onKeyDown={e => {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(text); }
            else if (e.key === "Tab" && text.trim()) { e.preventDefault(); add(text); }
            else if (e.key === "Backspace" && !text && value.length) remove(value[value.length - 1]);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onFocus={() => setOpen(true)}
        />
      </div>
      {open && filtered.length > 0 && (
        <div className="absolute z-20 left-0 right-0 mt-1 rounded-sm border overflow-hidden"
             style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)", maxHeight: "12rem", overflowY: "auto" }}>
          {filtered.map(s => (
            <button key={s} type="button" onMouseDown={e => { e.preventDefault(); add(s); }}
              className="block w-full text-left px-3 py-1.5 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
              style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)" }}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Single-value autocomplete (used for Series). `onPick` fires when a known
 *  value is chosen (suggestion click or exact type match) — used to fetch the
 *  next series index. */
export function Autocomplete({ value, onChange, onPick, suggestions, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  onPick?: (v: string) => void;
  suggestions: string[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const filtered = value.trim()
    ? suggestions.filter(s => s.toLowerCase().includes(value.toLowerCase()) && s.toLowerCase() !== value.toLowerCase()).slice(0, 8)
    : [];

  return (
    <div className="relative">
      <input className="bc-input" value={value} placeholder={placeholder}
        onChange={e => {
          const v = e.target.value;
          onChange(v);
          setOpen(true);
          if (onPick && suggestions.some(s => s.toLowerCase() === v.toLowerCase())) onPick(v);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => setOpen(true)} />
      {open && filtered.length > 0 && (
        <div className="absolute z-20 left-0 right-0 mt-1 rounded-sm border overflow-hidden"
             style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)", maxHeight: "12rem", overflowY: "auto" }}>
          {filtered.map(s => (
            <button key={s} type="button" onMouseDown={e => { e.preventDefault(); onChange(s); setOpen(false); onPick?.(s); }}
              className="block w-full text-left px-3 py-1.5 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
              style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)" }}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
