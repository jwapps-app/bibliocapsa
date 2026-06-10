"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { KeyRound, Sparkles, Loader, Loader2, CheckCircle, Eye, EyeOff, Save, XCircle, Users, UserPlus, Lock, Send, Mail, RefreshCw, BookMarked, Wrench, SearchX, Upload, BookPlus } from "lucide-react";
import { api, type CurrentUser } from "@/lib/api";
import { KOReaderSettings } from "@/components/KOReaderSettings";

interface SettingsView {
  hardcover_token_set: boolean; hardcover_token_preview: string | null;
  smtp_host?: string | null; smtp_port?: string | null; smtp_user?: string | null;
  smtp_from?: string | null; smtp_tls?: boolean; smtp_password_set?: boolean; smtp_configured?: boolean;
  auto_enrich?: boolean;
}
interface EnrichJob {
  running: boolean; total: number; processed: number;
  succeeded: number; no_match: number; errors: number;
  current: string | null; finished_at: string | null;
  library: { total: number; with_cover: number; no_match: number } | null;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [job, setJob] = useState<EnrichJob | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Accounts ──
  type Account = CurrentUser & { genres?: string[] };
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [allGenres, setAllGenres] = useState<string[]>([]);
  const [nu, setNu] = useState({ username: "", password: "", name: "", role: "member", genres: "" });
  const [memberMsg, setMemberMsg] = useState<string | null>(null);
  const [memberBusy, setMemberBusy] = useState(false);
  const [accessEdit, setAccessEdit] = useState<{ id: number; text: string } | null>(null);
  const [pwReset, setPwReset] = useState<{ id: number; text: string } | null>(null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);

  // ── Email: Kindle address (per user) + SMTP (admin) ──
  const [kindle, setKindle] = useState("");
  const [kindleMsg, setKindleMsg] = useState<string | null>(null);
  const [smtp, setSmtp] = useState({ host: "", port: "587", user: "", password: "", from: "", tls: true });
  const [smtpMsg, setSmtpMsg] = useState<string | null>(null);
  const [smtpBusy, setSmtpBusy] = useState(false);
  const [testTo, setTestTo] = useState("");

  // ── Reading → Calibre columns (admin) ──
  const [readingMap, setReadingMap] = useState<{ read: string | null; progress: string | null; date: string | null }>({ read: null, progress: null, date: null });
  const [customCols, setCustomCols] = useState<{ label: string; name: string; datatype: string }[]>([]);
  const [readingMsg, setReadingMsg] = useState<string | null>(null);
  const [readingBusy, setReadingBusy] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (user?.role !== "admin") return;
    api.customColumns().then(setCustomCols).catch(() => {});
    api.getReadingMap().then(setReadingMap).catch(() => {});
    api.calibrePendingCount().then(setPendingCount).catch(() => {});
  }, [user]);

  const saveReadingMap = async (m: typeof readingMap) => { setReadingMap(m); await api.saveReadingMap(m); };
  const runReadingSync = async () => {
    setReadingBusy(true); setReadingMsg(null);
    try {
      const r = await api.runReadingSync();
      setReadingMsg(`Queued ${r.queued} update${r.queued === 1 ? "" : "s"} from ${r.books_with_progress} book(s) with reading progress — review on Sync.`);
    } catch (e: any) { setReadingMsg(e.message ?? "Failed"); }
    finally { setReadingBusy(false); }
  };

  // Populate forms from loaded data.
  useEffect(() => { if (user?.kindle_email) setKindle(user.kindle_email); }, [user]);
  useEffect(() => {
    if (settings) setSmtp(s => ({
      ...s,
      host: settings.smtp_host ?? "", port: settings.smtp_port ?? "587",
      user: settings.smtp_user ?? "", from: settings.smtp_from ?? "",
      tls: settings.smtp_tls ?? true,
    }));
  }, [settings]);

  const saveKindle = async () => {
    setKindleMsg(null);
    try { await api.updateMe({ kindle_email: kindle.trim() }); setKindleMsg("Saved."); setTimeout(() => setKindleMsg(null), 2500); }
    catch (e: any) { setKindleMsg(e.message ?? "Could not save"); }
  };

  const saveSmtp = async () => {
    setSmtpBusy(true); setSmtpMsg(null);
    try {
      const body: any = { smtp_host: smtp.host, smtp_port: smtp.port, smtp_user: smtp.user, smtp_from: smtp.from, smtp_tls: smtp.tls };
      if (smtp.password) body.smtp_password = smtp.password;
      const res = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Save failed");
      setSettings(await res.json());
      setSmtp(s => ({ ...s, password: "" }));
      setSmtpMsg("Saved.");
      setTimeout(() => setSmtpMsg(null), 2500);
    } catch (e: any) { setSmtpMsg(e.message ?? "Could not save"); }
    finally { setSmtpBusy(false); }
  };

  const testSmtp = async () => {
    const to = testTo.trim() || kindle.trim();
    if (!to) { setSmtpMsg("Enter a test address"); return; }
    setSmtpBusy(true); setSmtpMsg(null);
    try {
      const res = await fetch("/api/settings/smtp-test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ to }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Test failed");
      setSmtpMsg(`Test email sent to ${to}.`);
    } catch (e: any) { setSmtpMsg(e.message ?? "Test failed"); }
    finally { setSmtpBusy(false); }
  };

  const loadAccounts = useCallback(() => {
    fetch("/api/auth/users").then(r => r.ok ? r.json() : []).then(setAccounts).catch(() => {});
    fetch("/api/tags?page_size=500").then(r => r.ok ? r.json() : []).then(
      (tags: any[]) => setAllGenres(tags.map(t => t.name))
    ).catch(() => {});
  }, []);

  const parseGenres = (s: string) => s.split(",").map(g => g.trim()).filter(Boolean);

  const addMember = async () => {
    setMemberBusy(true); setMemberMsg(null);
    try {
      await api.register({
        username: nu.username.trim(), password: nu.password,
        name: nu.name || undefined, role: nu.role,
        genres: nu.role === "member" ? parseGenres(nu.genres) : undefined,
      });
      setNu({ username: "", password: "", name: "", role: "member", genres: "" });
      setMemberMsg("Account created.");
      loadAccounts();
      setTimeout(() => setMemberMsg(null), 2500);
    } catch (e: any) { setMemberMsg(e.message ?? "Could not create account"); }
    finally { setMemberBusy(false); }
  };

  const saveAccess = async (id: number, text: string) => {
    try {
      await api.setUserAccess(id, parseGenres(text));
      setAccessEdit(null);
      loadAccounts();
    } catch (e: any) { setMemberMsg(e.message ?? "Could not update access"); }
  };

  const resetPassword = async (id: number, text: string, username: string) => {
    if (text.length < 6) { setMemberMsg("Password must be at least 6 characters"); return; }
    try {
      await api.adminResetPassword(id, text);
      setPwReset(null);
      setMemberMsg(`Password reset for @${username}. Share it with them — it works for the web app and KOReader.`);
      setTimeout(() => setMemberMsg(null), 6000);
    } catch (e: any) { setMemberMsg(e.message ?? "Could not reset password"); }
  };

  const savePassword = async () => {
    setPwBusy(true); setPwMsg(null);
    try {
      await api.changePassword(pw.next, pw.current);
      setPw({ current: "", next: "" });
      setPwMsg("Password updated. Use it for the web app and KOReader.");
      setTimeout(() => setPwMsg(null), 3500);
    } catch (e: any) { setPwMsg(e.message ?? "Could not change password"); }
    finally { setPwBusy(false); }
  };

  const loadSettings = useCallback(() => {
    fetch("/api/settings").then(r => r.json()).then(setSettings).catch(() => {});
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const s: EnrichJob = await fetch("/api/native/books/enrich/status").then(r => r.json());
      setJob(s);
      if (!s.running && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {}
  }, []);

  useEffect(() => {
    loadSettings();
    loadStatus();
    api.me().then(u => { setUser(u); if (u?.role === "admin") loadAccounts(); }).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadSettings, loadStatus, loadAccounts]);

  // If a job is already running when the page loads, start polling.
  useEffect(() => {
    if (job?.running && !pollRef.current) {
      pollRef.current = setInterval(loadStatus, 1000);
    }
  }, [job?.running, loadStatus]);

  const saveToken = async () => {
    setSaving(true); setSaved(false);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hardcover_token: token }),
      });
      const data = await res.json();
      setSettings(data);
      setToken("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {} finally { setSaving(false); }
  };

  const clearToken = async () => {
    if (!confirm("Remove the saved Hardcover token? Enrichment will fall back to Open Library only.")) return;
    setSaving(true);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hardcover_token: "" }),
      });
      setSettings(await res.json());
    } catch {} finally { setSaving(false); }
  };

  const startEnrich = async (force = false) => {
    setStarting(true);
    try {
      await fetch(`/api/native/books/enrich?force=${force}`, { method: "POST" });
      await loadStatus();
      if (!pollRef.current) pollRef.current = setInterval(loadStatus, 1000);
    } catch {} finally { setStarting(false); }
  };

  const cancelEnrich = async () => {
    await fetch("/api/native/books/enrich/cancel", { method: "POST" });
    await loadStatus();
  };

  const lib = job?.library;
  const coverPct = lib && lib.total ? Math.round((lib.with_cover / lib.total) * 100) : 0;
  const jobPct = job && job.total ? Math.round((job.processed / job.total) * 100) : 0;

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8">
          <a href="/" style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)", opacity: 0.6 }}>← Library</a>
        </div>

        <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }} className="mb-2">Settings</h1>
        <p style={{ fontFamily: "var(--body)", fontSize: "1rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-8">
          Account, devices, and library tools.
        </p>

        {/* ── KOReader integration ────────────────────────────────────── */}
        <KOReaderSettings />

        {/* ── Hardcover token ─────────────────────────────────────────── */}
        <div className="rounded-sm p-5 mb-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex items-center gap-2 mb-3">
            <KeyRound className="w-4 h-4" style={{ color: "var(--gold)" }} />
            <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Hardcover API token</span>
          </div>
          <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
            Optional. Richer covers, descriptions, and ratings. Get a token at{" "}
            <a href="https://hardcover.app/account/api" target="_blank" rel="noreferrer"
               style={{ color: "var(--gold-light)" }} className="hover:underline">hardcover.app/account/api</a>.
            Without it, Open Library is used (free, no token).
          </p>

          {settings?.hardcover_token_set && (
            <div className="flex items-center justify-between mb-3 px-3 py-2 rounded-sm"
                 style={{ background: "rgba(107,78,30,0.18)", border: "1px solid var(--gold-dim)" }}>
              <span className="flex items-center gap-2" style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)" }}>
                <CheckCircle className="w-3.5 h-3.5" /> Saved · {settings.hardcover_token_preview}
              </span>
              <button onClick={clearToken} disabled={saving}
                style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "#e08080" }} className="hover:underline">
                Remove
              </button>
            </div>
          )}

          <div className="flex gap-2">
            <div className="flex-1 relative">
              <input
                type={showToken ? "text" : "password"}
                value={token}
                onChange={e => setToken(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") saveToken(); }}
                placeholder={settings?.hardcover_token_set ? "Enter a new token to replace…" : "Paste your Hardcover token…"}
                className="w-full px-3 py-2 rounded-sm pr-9"
                style={{ background: "var(--ink-muted)", border: "1px solid var(--ink-muted)", color: "var(--parchment)", fontFamily: "var(--mono)", fontSize: "0.78rem" }}
              />
              <button onClick={() => setShowToken(s => !s)} className="absolute right-2 top-1/2 -translate-y-1/2"
                style={{ color: "var(--parchment-dim)", opacity: 0.6 }} tabIndex={-1}>
                {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <button onClick={saveToken} disabled={saving || !token.trim()}
              className="flex items-center gap-1.5 px-3 py-2 rounded-sm transition-opacity hover:opacity-85 disabled:opacity-40"
              style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.75rem" }}>
              {saving ? <Loader className="w-3.5 h-3.5 animate-spin" /> : saved ? <CheckCircle className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
              {saved ? "Saved" : "Save"}
            </button>
          </div>
        </div>

        {/* ── Enrichment ──────────────────────────────────────────────── */}
        <div className="rounded-sm p-5 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4" style={{ color: "var(--gold)" }} />
            <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Cover &amp; metadata enrichment</span>
          </div>

          {/* Auto-enrich toggle (master default; the import has its own checkbox) */}
          <label className="flex items-start gap-2 mb-4 cursor-pointer">
            <input type="checkbox" checked={settings?.auto_enrich ?? true}
              onChange={async e => {
                const val = e.target.checked;
                setSettings(s => (s ? { ...s, auto_enrich: val } : s));
                const res = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ auto_enrich: val }) });
                if (res.ok) setSettings(await res.json());
              }}
              style={{ accentColor: "var(--gold)", marginTop: "3px" }} />
            <span style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment)" }}>
              Automatically enrich new books
              <span className="block" style={{ fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                Fetch covers &amp; details as books are imported or added (Open Library, plus Hardcover if configured). Turn off to keep everything local — you can still run it manually below.
              </span>
            </span>
          </label>

          {/* Coverage summary */}
          {lib && (
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>
                <span>{lib.with_cover.toLocaleString()} of {lib.total.toLocaleString()} physical books have covers</span>
                <span style={{ color: "var(--gold-light)" }}>{coverPct}%</span>
              </div>
              <div className="w-full rounded-full h-1.5" style={{ background: "var(--ink-muted)" }}>
                <div className="h-1.5 rounded-full transition-all" style={{ width: `${coverPct}%`, background: "var(--gold)" }} />
              </div>
            </div>
          )}

          {/* Running job */}
          {job?.running ? (
            <div className="rounded-sm p-4 mb-4" style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)" }}>
              <div className="flex items-center gap-2 mb-3">
                <Loader className="w-4 h-4 animate-spin" style={{ color: "var(--gold)" }} />
                <span style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment)" }}>
                  Enriching… {job.processed.toLocaleString()} / {job.total.toLocaleString()}
                </span>
              </div>
              <div className="w-full rounded-full h-1.5 mb-2" style={{ background: "var(--ink-muted)" }}>
                <div className="h-1.5 rounded-full transition-all" style={{ width: `${jobPct}%`, background: "var(--gold)" }} />
              </div>
              {job.current && (
                <p className="truncate" style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                  {job.current}
                </p>
              )}
              <div className="flex gap-4 mt-2" style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                <span style={{ color: "var(--gold-light)" }}>✓ {job.succeeded}</span>
                <span>— {job.no_match} no match</span>
                {job.errors > 0 && <span style={{ color: "#e08080" }}>✕ {job.errors}</span>}
              </div>
              <button onClick={cancelEnrich}
                className="flex items-center gap-1.5 mt-3 px-3 py-1.5 rounded-sm hover:opacity-80"
                style={{ background: "rgba(120,40,40,0.3)", border: "1px solid rgba(150,50,50,0.4)", fontFamily: "var(--mono)", fontSize: "0.7rem", color: "#e08080" }}>
                <XCircle className="w-3 h-3" /> Stop
              </button>
            </div>
          ) : (
            <>
              {job?.finished_at && job.processed > 0 && (
                <p className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>
                  Last run: {job.succeeded} enriched, {job.no_match} no match{job.errors > 0 ? `, ${job.errors} errors` : ""}.
                </p>
              )}
              <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
                Looks up each physical book by ISBN. Runs in the background — you can leave this page.
                {settings?.hardcover_token_set ? " Using Hardcover + Open Library." : " Using Open Library (add a token above for richer data)."}
              </p>
              <div className="flex items-center gap-3">
                <button onClick={() => startEnrich(false)} disabled={starting}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-sm transition-opacity hover:opacity-85 disabled:opacity-40"
                  style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.78rem" }}>
                  {starting ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                  Enrich missing covers
                </button>
                <button onClick={() => startEnrich(true)} disabled={starting}
                  style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)", opacity: 0.7 }}
                  className="hover:underline disabled:opacity-40">
                  Re-run all
                </button>
              </div>
            </>
          )}
        </div>

        {/* ── Library tools (admin only) ──────────────────────────────── */}
        {user?.role === "admin" && (
          <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
            <div className="flex items-center gap-2 mb-1">
              <Wrench className="w-4 h-4" style={{ color: "var(--gold)" }} />
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Library tools</span>
            </div>
            <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
              Occasional maintenance — usually only needed during initial setup.
            </p>
            <div className="flex flex-wrap gap-2">
              <a href="/sync" title={pendingCount > 0 ? `${pendingCount} change${pendingCount === 1 ? "" : "s"} pending` : "No changes pending"}
                className="relative inline-flex items-center gap-2 px-3 py-2 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                style={{ fontFamily: "var(--mono)", fontSize: "0.75rem",
                         color: pendingCount > 0 ? "var(--gold-light)" : "var(--parchment-dim)",
                         borderColor: pendingCount > 0 ? "var(--gold-dim)" : "var(--ink-muted)", background: "var(--ink)" }}>
                <RefreshCw className="w-4 h-4" /> Sync to Calibre
                {pendingCount > 0 && (
                  <span className="inline-flex items-center justify-center"
                    style={{ minWidth: "16px", height: "16px", padding: "0 4px", borderRadius: "999px",
                             background: "var(--gold)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: "0.6rem", fontWeight: 700 }}>
                    {pendingCount}
                  </span>
                )}
              </a>
              <a href="/books/new" className="inline-flex items-center gap-2 px-3 py-2 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink)" }}>
                <BookPlus className="w-4 h-4" /> Add a book
              </a>
              <a href="/missing" className="inline-flex items-center gap-2 px-3 py-2 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink)" }}>
                <SearchX className="w-4 h-4" /> Missing metadata
              </a>
              <a href="/import" className="inline-flex items-center gap-2 px-3 py-2 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)", background: "var(--ink)" }}>
                <Upload className="w-4 h-4" /> Import from Goodreads
              </a>
            </div>
          </div>
        )}

        {/* ── Reading → Calibre columns (admin only) ──────────────────── */}
        {user?.role === "admin" && customCols.length > 0 && (
          <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
            <div className="flex items-center gap-2 mb-1">
              <BookMarked className="w-4 h-4" style={{ color: "var(--gold)" }} />
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Reading → Calibre columns</span>
            </div>
            <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
              Pick which Calibre columns hold your reading data. The <strong style={{ color: "var(--parchment)" }}>Read status</strong> column also makes the Read/Unread toggle on digital books export back to Calibre on Sync. Leave any blank to keep that data inside Bibliocapsa only. "Queue reading updates" pushes your KOReader progress (read / % / date finished) into these columns for review on Sync.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              {([
                ["read", "Read status (bool)", "bool"],
                ["progress", "Progress % (int)", "int"],
                ["date", "Date read (datetime)", "datetime"],
              ] as const).map(([key, label, dt]) => (
                <label key={key} className="block">
                  <span className="block uppercase tracking-widest mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{label}</span>
                  <select className="bc-input" value={readingMap[key] ?? ""}
                    onChange={e => saveReadingMap({ ...readingMap, [key]: e.target.value || null })}>
                    <option value="">— none —</option>
                    {customCols.filter(c => c.datatype === dt).map(c => <option key={c.label} value={c.label}>{c.name}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={runReadingSync} disabled={readingBusy || !(readingMap.read || readingMap.progress || readingMap.date)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-40"
                style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                {readingBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} Queue reading updates
              </button>
              {readingMsg && <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)" }}>{readingMsg}</span>}
            </div>
          </div>
        )}

        {/* ── Members (admin only) ────────────────────────────────────── */}
        {user?.role === "admin" && (
          <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
            <div className="flex items-center gap-2 mb-3">
              <Users className="w-4 h-4" style={{ color: "var(--gold)" }} />
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Members</span>
            </div>
            <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
              Each member signs into the web app and KOReader with the same username &amp; password.
            </p>

            <datalist id="genre-options">
              {allGenres.map(g => <option key={g} value={g} />)}
            </datalist>

            <div className="space-y-2 mb-4">
              {accounts.map(a => (
                <div key={a.id} className="px-3 py-2 rounded-sm"
                     style={{ background: "var(--ink)", border: "1px solid var(--ink-muted)" }}>
                  <div className="flex items-center justify-between">
                    <span style={{ fontFamily: "var(--body)", fontSize: "0.9rem", color: "var(--parchment)" }}>
                      {a.name || a.username} <span style={{ color: "var(--parchment-dim)", opacity: 0.6, fontFamily: "var(--mono)", fontSize: "0.7rem" }}>@{a.username}</span>
                    </span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: a.role === "admin" ? "var(--gold-light)" : "var(--parchment-dim)", opacity: 0.8 }}>
                      {a.role}
                    </span>
                  </div>
                  {/* Access row — admins always see everything */}
                  {a.role !== "admin" && (
                    <div className="mt-1.5">
                      {accessEdit?.id === a.id ? (
                        <div className="flex gap-1.5">
                          <input className="bc-input flex-1" list="genre-options" autoFocus
                            placeholder="Comma-separated genres (blank = full library)"
                            value={accessEdit.text}
                            onChange={e => setAccessEdit({ id: a.id, text: e.target.value })}
                            onKeyDown={e => { if (e.key === "Enter") saveAccess(a.id, accessEdit.text); if (e.key === "Escape") setAccessEdit(null); }} />
                          <button onClick={() => saveAccess(a.id, accessEdit.text)}
                            className="px-2.5 rounded-sm" style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>Save</button>
                          <button onClick={() => setAccessEdit(null)}
                            className="px-2 rounded-sm" style={{ color: "var(--parchment-dim)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>×</button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 flex-wrap">
                          {a.genres && a.genres.length > 0 ? (
                            a.genres.map(g => <span key={g} className="tag-pill">{g}</span>)
                          ) : (
                            <span style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--gold-light)", opacity: 0.8 }}>Full library</span>
                          )}
                          <button onClick={() => setAccessEdit({ id: a.id, text: (a.genres || []).join(", ") })}
                            style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)" }} className="hover:underline">
                            edit access
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                  {/* Reset password — available for any account */}
                  <div className="mt-1.5">
                    {pwReset?.id === a.id ? (
                      <div className="flex gap-1.5">
                        <input className="bc-input flex-1" type="text" autoFocus
                          placeholder="New password (min 6 chars)"
                          value={pwReset.text}
                          onChange={e => setPwReset({ id: a.id, text: e.target.value })}
                          onKeyDown={e => { if (e.key === "Enter") resetPassword(a.id, pwReset.text, a.username); if (e.key === "Escape") setPwReset(null); }} />
                        <button onClick={() => resetPassword(a.id, pwReset.text, a.username)}
                          className="px-2.5 rounded-sm" style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>Set</button>
                        <button onClick={() => setPwReset(null)}
                          className="px-2 rounded-sm" style={{ color: "var(--parchment-dim)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>×</button>
                      </div>
                    ) : (
                      <button onClick={() => setPwReset({ id: a.id, text: "" })}
                        style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)" }} className="hover:underline">
                        reset password
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <input className="bc-input" placeholder="Username" value={nu.username}
                     onChange={e => setNu({ ...nu, username: e.target.value })} />
              <input className="bc-input" type="password" placeholder="Password" value={nu.password}
                     onChange={e => setNu({ ...nu, password: e.target.value })} />
              <input className="bc-input" placeholder="Display name (optional)" value={nu.name}
                     onChange={e => setNu({ ...nu, name: e.target.value })} />
              <select className="bc-input" value={nu.role} onChange={e => setNu({ ...nu, role: e.target.value })}>
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
            </div>
            {nu.role === "member" && (
              <input className="bc-input mt-2" list="genre-options"
                     placeholder="Allowed genres, comma-separated (leave blank for full library)"
                     value={nu.genres} onChange={e => setNu({ ...nu, genres: e.target.value })} />
            )}
            <div className="flex items-center gap-3 mt-3">
              <button onClick={addMember} disabled={memberBusy || !nu.username.trim() || !nu.password}
                className="flex items-center gap-1.5 px-4 py-2 rounded-sm transition-opacity hover:opacity-85 disabled:opacity-40"
                style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.78rem" }}>
                {memberBusy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <UserPlus className="w-3.5 h-3.5" />}
                Add member
              </button>
              {memberMsg && <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>{memberMsg}</span>}
            </div>
          </div>
        )}

        {/* ── Send to Kindle: your Kindle email ───────────────────────── */}
        <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex items-center gap-2 mb-3">
            <Send className="w-4 h-4" style={{ color: "var(--gold)" }} />
            <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Send to Kindle</span>
          </div>
          <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
            Your <code>@kindle.com</code> address. Find it at Amazon → Manage Your Content &amp; Devices → Preferences → Personal Document Settings.
            Remember to add the library&apos;s send address there as an approved sender.
          </p>
          <div className="flex gap-2">
            <input className="bc-input flex-1" placeholder="you@kindle.com" value={kindle} onChange={e => setKindle(e.target.value)} />
            <button onClick={saveKindle} className="flex items-center gap-1.5 px-3 rounded-sm" style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.75rem" }}>
              <Save className="w-3.5 h-3.5" /> Save
            </button>
          </div>
          {kindleMsg && <div className="mt-2" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>{kindleMsg}</div>}
        </div>

        {/* ── SMTP (admin) ────────────────────────────────────────────── */}
        {user?.role === "admin" && (
          <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
            <div className="flex items-center gap-2 mb-3">
              <Mail className="w-4 h-4" style={{ color: "var(--gold)" }} />
              <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Email server (SMTP)</span>
              {settings?.smtp_configured && <CheckCircle className="w-3.5 h-3.5" style={{ color: "var(--gold-light)" }} />}
            </div>
            <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
              Used for Send-to-Kindle and lending reminders. For Gmail, use an App Password.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <input className="bc-input" placeholder="Host (smtp.gmail.com)" value={smtp.host} onChange={e => setSmtp({ ...smtp, host: e.target.value })} />
              <input className="bc-input" placeholder="Port (587)" value={smtp.port} onChange={e => setSmtp({ ...smtp, port: e.target.value })} inputMode="numeric" />
              <input className="bc-input" placeholder="Username" value={smtp.user} onChange={e => setSmtp({ ...smtp, user: e.target.value })} autoComplete="off" />
              <input className="bc-input" type="password" placeholder={settings?.smtp_password_set ? "Password (saved — leave blank to keep)" : "Password"} value={smtp.password} onChange={e => setSmtp({ ...smtp, password: e.target.value })} autoComplete="new-password" />
              <input className="bc-input" placeholder="From address" value={smtp.from} onChange={e => setSmtp({ ...smtp, from: e.target.value })} />
              <label className="flex items-center gap-2 px-1" style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--parchment-dim)" }}>
                <input type="checkbox" checked={smtp.tls} onChange={e => setSmtp({ ...smtp, tls: e.target.checked })} /> Use STARTTLS
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <button onClick={saveSmtp} disabled={smtpBusy} className="flex items-center gap-1.5 px-4 py-2 rounded-sm disabled:opacity-50" style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.78rem" }}>
                {smtpBusy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Save
              </button>
              <input className="bc-input" style={{ width: "12rem" }} placeholder="test@email.com" value={testTo} onChange={e => setTestTo(e.target.value)} />
              <button onClick={testSmtp} disabled={smtpBusy} className="px-3 py-2 rounded-sm border disabled:opacity-50" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)" }}>
                Send test
              </button>
              {smtpMsg && <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>{smtpMsg}</span>}
            </div>
          </div>
        )}

        {/* ── Change password ─────────────────────────────────────────── */}
        <div className="rounded-sm p-5 mt-6 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
          <div className="flex items-center gap-2 mb-3">
            <Lock className="w-4 h-4" style={{ color: "var(--gold)" }} />
            <span style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>Change password</span>
          </div>
          <p style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-4">
            Updates both your web login and KOReader sync password.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <input className="bc-input" type="password" placeholder="Current password" value={pw.current}
                   onChange={e => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
            <input className="bc-input" type="password" placeholder="New password" value={pw.next}
                   onChange={e => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
          </div>
          <div className="flex items-center gap-3 mt-3">
            <button onClick={savePassword} disabled={pwBusy || pw.next.length < 6}
              className="flex items-center gap-1.5 px-4 py-2 rounded-sm transition-opacity hover:opacity-85 disabled:opacity-40"
              style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.78rem" }}>
              {pwBusy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Update password
            </button>
            {pwMsg && <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>{pwMsg}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
