"use client";

import { useState, useEffect, useRef } from "react";
import { Palette, Check } from "lucide-react";
import { api } from "@/lib/api";
import { applyFavicon, applyAppleIcon } from "@/lib/favicon";

const THEMES = [
  { id: "library", label: "Library", dot: "#c9933a", bg: "#0f0d0b" },
  { id: "midnight", label: "Midnight", dot: "#6ea8e8", bg: "#0b0e14" },
  { id: "slate", label: "Slate", dot: "#b08d57", bg: "#121212" },
  { id: "forest", label: "Forest", dot: "#8fbf6f", bg: "#0c120e" },
  { id: "sepia", label: "Sepia (light)", dot: "#8a5e22", bg: "#efe6d2" },
  { id: "paper", label: "Paper (light)", dot: "#7a672f", bg: "#f5f5f3" },
];
const FONTS = [
  { id: "classic", label: "Classic serif" },
  { id: "modern", label: "Modern sans" },
  { id: "plain", label: "System" },
];

export function ThemePicker({ collapsed, iconOnly }: { collapsed?: boolean; iconOnly?: boolean }) {
  const [open, setOpen] = useState(false);
  const [theme, setThemeState] = useState("library");
  const [font, setFontState] = useState("classic");
  const ref = useRef<HTMLDivElement>(null);

  const setFavicon = applyFavicon;
  const setAppleIcon = applyAppleIcon;

  const applyTheme = (id: string) => { document.documentElement.dataset.theme = id; localStorage.setItem("bc-theme", id); setFavicon(); setAppleIcon(id); };
  const applyFont = (id: string) => { document.documentElement.dataset.font = id; localStorage.setItem("bc-font", id); };

  useEffect(() => {
    // Start from the local cache (already applied pre-paint), then reconcile with
    // the account so the choice follows the user across devices.
    setThemeState(localStorage.getItem("bc-theme") || "library");
    setFontState(localStorage.getItem("bc-font") || "classic");
    api.me().then(u => {
      if (u?.theme) { applyTheme(u.theme); setThemeState(u.theme); }
      if (u?.font) { applyFont(u.font); setFontState(u.font); }
    }).catch(() => {}).finally(() => { const t = localStorage.getItem("bc-theme") || "library"; setFavicon(); setAppleIcon(t); });
  }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const setTheme = (id: string) => { applyTheme(id); setThemeState(id); api.savePreferences({ theme: id }); };
  const setFont = (id: string) => { applyFont(id); setFontState(id); api.savePreferences({ font: id }); };

  return (
    <div className="relative" ref={ref}>
      {iconOnly ? (
        <button onClick={() => setOpen(o => !o)} title="Appearance"
          className="p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
          style={{ color: "var(--parchment-dim)" }}>
          <Palette className="w-4 h-4" />
        </button>
      ) : (
        <button onClick={() => setOpen(o => !o)} title="Appearance"
          className={`${collapsed ? "w-full justify-center" : ""} flex items-center gap-2 px-3 py-2 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]`}
          style={{ color: "var(--parchment-dim)", fontFamily: "var(--body)", fontSize: "0.85rem", width: collapsed ? undefined : "100%" }}>
          <Palette className="w-4 h-4 shrink-0" />
          {!collapsed && <span>Appearance</span>}
        </button>
      )}

      {open && (
        <div className={`absolute bottom-full mb-2 z-50 rounded-sm border p-3 ${iconOnly ? (collapsed ? "left-0" : "right-0") : "left-2 right-2"}`}
          style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)", minWidth: "13rem" }}>
          <div className="uppercase tracking-widest mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>Theme</div>
          <div className="grid grid-cols-2 gap-1.5 mb-3">
            {THEMES.map(t => (
              <button key={t.id} onClick={() => setTheme(t.id)}
                className="flex items-center gap-2 px-2 py-1.5 rounded-sm border transition-colors"
                style={{ borderColor: theme === t.id ? "var(--gold)" : "var(--ink-muted)", fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment)" }}>
                <span className="w-3.5 h-3.5 rounded-full border shrink-0" style={{ background: t.bg, borderColor: t.dot }}>
                  <span className="block w-full h-full rounded-full" style={{ background: t.dot, transform: "scale(0.5)" }} />
                </span>
                <span className="truncate">{t.label}</span>
              </button>
            ))}
          </div>
          <div className="uppercase tracking-widest mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>Font</div>
          <div className="space-y-1">
            {FONTS.map(fo => (
              <button key={fo.id} onClick={() => setFont(fo.id)}
                className="w-full flex items-center justify-between px-2 py-1.5 rounded-sm border transition-colors"
                style={{ borderColor: font === fo.id ? "var(--gold)" : "var(--ink-muted)", fontFamily: "var(--body)", fontSize: "0.8rem", color: "var(--parchment)" }}>
                {fo.label}{font === fo.id && <Check className="w-3.5 h-3.5" style={{ color: "var(--gold-light)" }} />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
