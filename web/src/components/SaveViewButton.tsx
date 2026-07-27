"use client";
import { useState } from "react";
import { BookmarkPlus } from "lucide-react";
import { api } from "@/lib/api";
import { paramsToConfig, type ViewParams } from "@/lib/savedViews";

/**
 * Saves whatever the library is currently showing (filters + sort + layout) as
 * a named view, shared with the iOS app. The current view IS the URL, so this
 * just names the active params - there's no separate filter builder to learn.
 */
export function SaveViewButton({ params, activeFilterName }: {
  params: ViewParams;
  /** Display name of the active series/author/tag, so the view can be stored
   *  by name rather than by Calibre id (which iOS can't resolve). */
  activeFilterName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveView(trimmed, paramsToConfig(params, activeFilterName));
      window.dispatchEvent(new Event("saved-views-changed"));
      setOpen(false);
      setName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save view");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} title="Save this view"
        className="flex items-center gap-1.5 px-2 py-1 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.2)]"
        style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--gold-light)", opacity: 0.85 }}>
        <BookmarkPlus className="w-3.5 h-3.5" /> Save view
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <input autoFocus value={name} onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") save(); if (e.key === "Escape") setOpen(false); }}
        placeholder="Name this view" maxLength={60}
        className="bc-input" style={{ width: "11rem", fontSize: "0.8rem", padding: "0.25rem 0.5rem" }} />
      <button onClick={save} disabled={busy || !name.trim()}
        className="px-2 py-1 rounded-sm transition-colors"
        style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--gold-light)",
                 opacity: busy || !name.trim() ? 0.4 : 0.9 }}>
        {busy ? "Saving…" : "Save"}
      </button>
      <button onClick={() => { setOpen(false); setError(null); }}
        className="px-1 py-1 rounded-sm"
        style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
        Cancel
      </button>
      {error && <span style={{ fontSize: "0.68rem", color: "var(--danger, #d66)" }}>{error}</span>}
    </div>
  );
}
