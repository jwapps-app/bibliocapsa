"use client";

import { useState, useEffect } from "react";
import { Smartphone, Copy, Check } from "lucide-react";
import { api } from "@/lib/api";

/** Shows the addresses to plug into KOReader for the three integrations
 *  (OPDS, reading-position sync, reading-statistics WebDAV), computed from the
 *  URL the user is currently accessing Bibliocapsa at. */
export function KOReaderSettings() {
  const [username, setUsername] = useState("");
  const [origin, setOrigin] = useState("");
  const [dav, setDav] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(u => setUsername(u?.username || "")).catch(() => {});
    setOrigin(window.location.origin);
    setDav(`${window.location.origin}/dav`);
  }, []);

  const copy = (text: string, key: string) => {
    try { navigator.clipboard?.writeText(text); } catch {}
    setCopied(key); setTimeout(() => setCopied(c => (c === key ? null : c)), 1500);
  };

  const rows = [
    { key: "opds", label: "OPDS catalog", url: `${origin}/opds`,
      desc: "Browse & download books on the device. KOReader → top menu → search/OPDS → add catalog." },
    { key: "sync", label: "Reading-position sync (KOSync)", url: origin,
      desc: "Syncs where you are in a book. KOReader → Progress sync → Custom sync server." },
    { key: "dav", label: "Reading statistics (WebDAV)", url: dav,
      desc: "Syncs reading time/pages for the Statistics dashboard. KOReader → Reading statistics → settings → Cloud sync → WebDAV, folder “/”.",
      note: "Uses your normal Bibliocapsa address — the built-in proxy routes /dav to the backend so WebDAV works over your domain. (Self-hosting without the bundled proxy? Make sure /dav reaches the backend on port 8000.)" },
  ];

  return (
    <div className="rounded-sm p-5 mb-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
      <div className="flex items-center gap-2 mb-2">
        <Smartphone className="w-4 h-4" style={{ color: "var(--gold)" }} />
        <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>KOReader integration</span>
      </div>
      <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
        Set these up on your KOReader device. Sign in with your Bibliocapsa account
        {username ? <> — username <span style={{ color: "var(--gold-light)" }}>{username}</span></> : null} and your password.
      </p>

      <div className="space-y-3">
        {rows.map(r => (
          <div key={r.key}>
            <div className="uppercase tracking-widest mb-1" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{r.label}</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-2.5 py-1.5 rounded-sm truncate"
                style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)", fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)" }}>
                {r.url || "…"}
              </code>
              <button onClick={() => copy(r.url, r.key)} className="shrink-0 p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
                style={{ color: "var(--parchment-dim)" }} title="Copy">
                {copied === r.key ? <Check className="w-4 h-4" style={{ color: "var(--gold-light)" }} /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
            <div className="mt-1" style={{ fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.65 }}>{r.desc}</div>
            {r.note && <div className="mt-1" style={{ fontFamily: "var(--body)", fontSize: "0.72rem", color: "var(--parchment-dim)", opacity: 0.5 }}>{r.note}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
