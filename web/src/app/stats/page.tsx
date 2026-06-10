"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, Clock, BookOpen, CalendarDays, Layers, Target, Sparkles } from "lucide-react";

const fmtH = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

const PERIODS = [[0, "All time"], [365, "Year"], [90, "90 days"], [30, "30 days"]] as const;
const SORTS = [["seconds", "Time"], ["pages_read", "Pages"], ["last_open", "Recent"], ["title", "Title"]] as const;

export default function StatsPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(0);
  const [sortBy, setSortBy] = useState("last_open");

  useEffect(() => {
    setLoading(true);
    api.statsSummary(days).then(setData).catch(() => setData({ available: false })).finally(() => setLoading(false));
  }, [days]);

  const unavailable = !loading && !data?.available;

  const sortedBooks = !data?.books ? [] : [...data.books].sort((a: any, b: any) =>
    sortBy === "title" ? a.title.localeCompare(b.title) : (b[sortBy] || 0) - (a[sortBy] || 0));

  return (
    <div className="min-h-screen flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-3xl">
        <a href="/" className="inline-flex items-center gap-2 mb-6 hover:underline" style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--parchment-dim)" }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Library
        </a>
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "2rem", color: "var(--parchment)" }} className="mb-1">Reading Statistics</h1>
        <p className="mb-4" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.75 }}>
          From your KOReader reading activity (synced via WebDAV).
        </p>

        {/* Reading goal — independent of KOReader stats (counts your read history) */}
        <ReadingGoal />

        <a href="/stats/year" className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-sm border hover:border-[var(--gold)] transition-colors"
           style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--gold-light)", borderColor: "var(--ink-muted)", background: "var(--ink-soft)" }}>
          <Sparkles className="w-3.5 h-3.5" /> {new Date().getFullYear()} in Review →
        </a>

        {/* Period selector */}
        <div className="flex flex-wrap gap-1.5 mb-6">
          {PERIODS.map(([d, label]) => (
            <button key={d} onClick={() => setDays(d)}
              className="px-3 py-1 rounded-sm border"
              style={{ fontFamily: "var(--mono)", fontSize: "0.68rem",
                       borderColor: days === d ? "var(--gold)" : "var(--ink-muted)",
                       color: days === d ? "var(--gold-light)" : "var(--parchment-dim)", background: "transparent" }}>
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
        ) : unavailable ? (
          <div className="text-center py-16" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.6 }}>
            No statistics yet. Set up KOReader → Reading statistics → Cloud sync (WebDAV) to your Bibliocapsa account, then sync.
          </div>
        ) : (
          <>
            {/* Totals */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
              {[
                { Icon: Clock, label: "Time read", val: fmtH(data.total_seconds) },
                { Icon: BookOpen, label: "Pages", val: data.total_pages.toLocaleString() },
                { Icon: Layers, label: "Books", val: String(data.book_count) },
                { Icon: CalendarDays, label: "Days read", val: String(data.days_read) },
              ].map(({ Icon, label, val }) => (
                <div key={label} className="rounded-sm p-4 border" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                  <Icon className="w-4 h-4 mb-2" style={{ color: "var(--gold)" }} />
                  <div style={{ fontFamily: "var(--serif)", fontSize: "1.4rem", color: "var(--parchment)" }}>{val}</div>
                  <div className="uppercase tracking-widest" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{label}</div>
                </div>
              ))}
            </div>

            <Heatmap activity={data.activity} />

            {/* Top books */}
            <div className="flex items-center justify-between mt-8 mb-3">
              <span className="uppercase tracking-widest" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
                Books ({sortedBooks.length})
              </span>
              <div className="flex items-center gap-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)" }}>
                <span style={{ opacity: 0.5 }}>sort</span>
                {SORTS.map(([k, label]) => (
                  <button key={k} onClick={() => setSortBy(k)} className="hover:underline"
                    style={{ color: sortBy === k ? "var(--gold-light)" : "var(--parchment-dim)" }}>{label}</button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              {sortedBooks.slice(0, 60).map((b: any, i: number) => (
                <a key={i} href={b.calibre_book_id ? `/books/${b.calibre_book_id}` : undefined}
                  className={`flex items-center gap-3 p-2.5 rounded-sm border ${b.calibre_book_id ? "hover:border-[var(--gold-dim)]" : "cursor-default"}`}
                  style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
                  {b.cover_url
                    ? <img src={b.cover_url.replace(/^https?:\/\/[^/]+/, "")} alt="" className="w-8 h-12 object-cover rounded-sm shrink-0" />
                    : <div className="w-8 h-12 rounded-sm shrink-0" style={{ background: "var(--ink-muted)" }} />}
                  <div className="min-w-0 flex-1">
                    <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>{b.title}</div>
                    <div className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.78rem", color: "var(--parchment-dim)", opacity: 0.7 }}>{b.authors}</div>
                  </div>
                  <div className="text-right shrink-0" style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--gold-light)" }}>
                    {fmtH(b.seconds)}<div style={{ color: "var(--parchment-dim)", opacity: 0.6 }}>{b.pages_read} pp</div>
                  </div>
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ReadingGoal() {
  const [goal, setGoalState] = useState<{ year: number; target: number | null; count: number } | null>(null);
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");

  const load = () => api.getGoal().then(g => { setGoalState(g); setVal(g.target ? String(g.target) : ""); }).catch(() => {});
  useEffect(() => { load(); }, []);

  const save = async () => {
    const t = parseInt(val, 10);
    if (isNaN(t) || t < 0) return;
    const g = await api.setGoal(goal?.year ?? new Date().getFullYear(), t);
    setGoalState(g); setEditing(false);
  };

  if (!goal) return null;
  const { year, target, count } = goal;
  const pct = target ? Math.min(100, Math.round((count / target) * 100)) : 0;
  const done = target != null && count >= target;

  return (
    <div className="rounded-sm p-5 mb-6 border flex items-center gap-5"
         style={{ background: "var(--ink-soft)", borderColor: done ? "var(--gold)" : "var(--ink-muted)" }}>
      <div className="relative shrink-0" style={{ width: 76, height: 76 }}>
        <svg viewBox="0 0 36 36" style={{ width: 76, height: 76 }}>
          <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--ink-muted)" strokeWidth="3" />
          {target ? (
            <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--gold)" strokeWidth="3"
              strokeLinecap="round" strokeDasharray={`${pct} 100`} transform="rotate(-90 18 18)" />
          ) : null}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center"
             style={{ fontFamily: "var(--serif)", fontSize: "1.05rem", color: "var(--parchment)" }}>
          {target ? `${pct}%` : <Target className="w-5 h-5" style={{ color: "var(--parchment-dim)", opacity: 0.5 }} />}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-1">
          <Target className="w-3.5 h-3.5" style={{ color: "var(--gold)" }} />
          <span className="uppercase tracking-widest" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
            {year} Reading Goal
          </span>
        </div>
        {editing ? (
          <div className="flex items-center gap-2">
            <input autoFocus type="number" min={0} value={val} onChange={e => setVal(e.target.value)}
              onKeyDown={e => e.key === "Enter" && save()}
              className="bc-input" style={{ width: "5rem" }} placeholder="books" />
            <button onClick={save} className="px-2.5 py-1 rounded-sm"
              style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)", fontSize: "0.72rem" }}>Save</button>
            <button onClick={() => { setEditing(false); setVal(target ? String(target) : ""); }}
              style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--parchment-dim)" }}>Cancel</button>
          </div>
        ) : target ? (
          <>
            <div style={{ fontFamily: "var(--serif)", fontSize: "1.5rem", color: "var(--parchment)" }}>
              {count} <span style={{ color: "var(--parchment-dim)", fontSize: "1rem" }}>/ {target} books</span>
            </div>
            <button onClick={() => setEditing(true)} className="mt-0.5 hover:underline"
              style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--parchment-dim)" }}>
              {done ? "🎉 Goal reached — edit" : "Edit goal"}
            </button>
          </>
        ) : (
          <button onClick={() => setEditing(true)} className="hover:underline text-left"
            style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--gold-light)" }}>
            Set a {year} reading goal{count > 0 ? ` — you've read ${count} so far` : ""} →
          </button>
        )}
      </div>
    </div>
  );
}

function Heatmap({ activity }: { activity: { date: string; seconds: number }[] }) {
  const map: Record<string, number> = {};
  activity.forEach(a => { map[a.date] = a.seconds; });
  const WEEKS = 26;
  const today = new Date();
  // Start from the Sunday WEEKS weeks back.
  const start = new Date(today); start.setDate(start.getDate() - WEEKS * 7 - today.getDay());
  const cells: { date: string; secs: number }[] = [];
  for (let i = 0; i < (WEEKS + 1) * 7; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const key = d.toISOString().slice(0, 10);
    cells.push({ date: key, secs: map[key] || 0 });
  }
  const level = (s: number) => s === 0 ? 0 : s < 600 ? 1 : s < 1800 ? 2 : s < 3600 ? 3 : 4;
  const colors = ["var(--ink-muted)", "rgba(201,147,58,0.3)", "rgba(201,147,58,0.55)", "rgba(201,147,58,0.8)", "var(--gold)"];
  const weeks: { date: string; secs: number }[][] = [];
  for (let w = 0; w < cells.length; w += 7) weeks.push(cells.slice(w, w + 7));

  return (
    <div>
      <div className="uppercase tracking-widest mb-2" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
        Last 6 months
      </div>
      <div className="flex gap-[3px] overflow-x-auto pb-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            {week.map(c => (
              <div key={c.date} title={`${c.date}: ${fmtH(c.secs)}`}
                style={{ width: 11, height: 11, borderRadius: 2, background: colors[level(c.secs)] }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
