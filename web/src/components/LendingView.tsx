"use client";

import { useState, useEffect, useCallback } from "react";
import { api, type Loan, type BookSummary } from "@/lib/api";
import { publicUrl } from "@/lib/api";
import { ArrowLeftRight, Plus, BookOpen, CalendarClock, Check, X, Loader2, Search } from "lucide-react";

const fmtDate = (s?: string) => s ? new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";

export function LendingView() {
  const [loans, setLoans] = useState<Loan[]>([]);
  const [activeOnly, setActiveOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [showLend, setShowLend] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.loans(activeOnly).then(setLoans).catch(() => setLoans([])).finally(() => setLoading(false));
  }, [activeOnly]);

  useEffect(() => { load(); }, [load]);

  const returnBook = async (id: number) => {
    await api.updateLoan(id, { returned_date: new Date().toISOString() });
    load();
  };
  const extend = async (loan: Loan) => {
    const base = loan.due_date ? new Date(loan.due_date) : new Date();
    base.setDate(base.getDate() + 14);
    await api.updateLoan(loan.id, { due_date: base.toISOString() });
    load();
  };

  const activeCount = loans.filter(l => !l.returned_date).length;
  const overdueCount = loans.filter(l => l.is_overdue).length;

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-1">
        <h2 style={{ fontFamily: "var(--serif)", fontSize: "1.8rem", color: "var(--parchment)" }}>Lending</h2>
        <button onClick={() => setShowLend(true)}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-sm border transition-colors hover:border-[var(--gold)]"
          style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
          <Plus className="w-4 h-4" /> Lend a book
        </button>
      </div>
      <p style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)", opacity: 0.7 }} className="mb-5">
        Track physical books loaned to friends and family.
        {activeOnly && ` ${activeCount} out${overdueCount ? `, ${overdueCount} overdue` : ""}.`}
      </p>

      {/* Active / History toggle */}
      <div className="flex items-center gap-1.5 mb-4">
        {[["active", true], ["history", false]].map(([label, val]) => (
          <button key={label as string} onClick={() => setActiveOnly(val as boolean)}
            className="px-3 py-1 rounded-sm border"
            style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", textTransform: "capitalize",
                     borderColor: activeOnly === val ? "var(--gold)" : "var(--ink-muted)",
                     color: activeOnly === val ? "var(--gold-light)" : "var(--parchment-dim)",
                     background: "transparent" }}>
            {label as string}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--parchment-dim)" }} /></div>
      ) : loans.length === 0 ? (
        <div className="text-center py-12" style={{ fontFamily: "var(--body)", color: "var(--parchment-dim)", opacity: 0.5 }}>
          <ArrowLeftRight className="w-8 h-8 mx-auto mb-3" style={{ opacity: 0.4 }} />
          {activeOnly ? "Nothing is currently lent out." : "No lending history yet."}
        </div>
      ) : (
        <div className="space-y-2">
          {loans.map(loan => (
            <div key={loan.id} className="flex items-center gap-3 p-3 rounded-sm border"
                 style={{ background: "var(--ink-soft)", borderColor: loan.is_overdue ? "rgba(180,70,70,0.5)" : "var(--ink-muted)" }}>
              {/* Cover */}
              <div className="shrink-0 w-10 h-15" style={{ width: "2.6rem" }}>
                {loan.has_cover && loan.cover_url ? (
                  <img src={publicUrl(loan.cover_url)} alt="" className="w-full rounded-sm border" style={{ borderColor: "var(--ink-muted)" }} />
                ) : (
                  <div className="aspect-[2/3] rounded-sm no-cover border flex items-center justify-center" style={{ borderColor: "var(--ink-muted)" }}>
                    <BookOpen className="w-4 h-4" style={{ color: "var(--parchment-dim)", opacity: 0.3 }} />
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.95rem", color: "var(--parchment)" }}>
                  {loan.book_title ?? `Book #${loan.book_id}`}
                </div>
                <div className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.82rem", color: "var(--parchment-dim)" }}>
                  {loan.borrower_name}
                </div>
                <div className="flex items-center gap-3 mt-0.5" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
                  <span>Lent {fmtDate(loan.loan_date)}</span>
                  {loan.due_date && <span style={{ color: loan.is_overdue ? "#e08080" : undefined }}>Due {fmtDate(loan.due_date)}</span>}
                  {loan.returned_date && <span style={{ color: "var(--gold-light)" }}>Returned {fmtDate(loan.returned_date)}</span>}
                  {loan.is_overdue && <span style={{ color: "#e08080", fontWeight: 700 }}>OVERDUE</span>}
                </div>
              </div>

              {/* Actions */}
              {!loan.returned_date && (
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => extend(loan)} title="Extend 2 weeks"
                    className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold-dim)]"
                    style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", borderColor: "var(--ink-muted)" }}>
                    <CalendarClock className="w-3.5 h-3.5" /> +2w
                  </button>
                  <button onClick={() => returnBook(loan.id)} title="Mark returned"
                    className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-sm border transition-colors hover:border-[var(--gold)]"
                    style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
                    <Check className="w-3.5 h-3.5" /> Return
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showLend && <LendModal onClose={() => setShowLend(false)} onLent={() => { setShowLend(false); setActiveOnly(true); load(); }} />}
    </div>
  );
}

function LendModal({ onClose, onLent }: { onClose: () => void; onLent: () => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<BookSummary[]>([]);
  const [picked, setPicked] = useState<BookSummary | null>(null);
  const [borrower, setBorrower] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!q.trim() || picked) { setResults([]); return; }
    const t = setTimeout(() => {
      api.books({ search: q.trim(), page_size: 8, format_filter: "all" })
        .then(r => setResults(r.items)).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q, picked]);

  const submit = async () => {
    if (!picked || !borrower.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createLoan({
        book_id: picked.id, book_source: picked.book_source ?? "calibre",
        borrower_name: borrower.trim(), due_date: due ? new Date(due).toISOString() : undefined,
      });
      onLent();
    } catch (e: any) { setError(e.message ?? "Could not lend"); setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <div className="w-full max-w-md rounded-sm border p-5" style={{ background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <span style={{ fontFamily: "var(--serif)", fontSize: "1.2rem", color: "var(--parchment)" }}>Lend a book</span>
          <button onClick={onClose} style={{ color: "var(--parchment-dim)" }}><X className="w-4 h-4" /></button>
        </div>

        {/* Book picker */}
        {picked ? (
          <div className="flex items-center gap-3 mb-4 p-2 rounded-sm" style={{ background: "var(--ink)", border: "1px solid var(--gold-dim)" }}>
            <span className="flex-1 truncate" style={{ fontFamily: "var(--serif)", fontSize: "0.9rem", color: "var(--parchment)" }}>{picked.title}</span>
            <button onClick={() => { setPicked(null); setQ(""); }} style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)" }} className="hover:underline">change</button>
          </div>
        ) : (
          <div className="mb-4">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--parchment-dim)", opacity: 0.5 }} />
              <input className="bc-input" style={{ paddingLeft: "2rem" }} placeholder="Search for a book…" value={q} onChange={e => setQ(e.target.value)} autoFocus />
            </div>
            {results.length > 0 && (
              <div className="mt-1 max-h-52 overflow-y-auto rounded-sm border" style={{ borderColor: "var(--ink-muted)" }}>
                {results.map(b => (
                  <button key={`${b.book_source}-${b.id}`} onClick={() => setPicked(b)}
                    className="block w-full text-left px-3 py-2 transition-colors hover:bg-[rgba(107,78,30,0.2)]"
                    style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment-dim)" }}>
                    {b.title}
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", opacity: 0.5 }}> · {b.book_source === "native" ? "physical" : "digital"}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <Field label="Borrower"><input className="bc-input" value={borrower} onChange={e => setBorrower(e.target.value)} placeholder="Who's borrowing it?" /></Field>
        <Field label="Due date (optional)"><input className="bc-input" type="date" value={due} onChange={e => setDue(e.target.value)} /></Field>

        {error && <div className="mb-3" style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "#d98a8a" }}>{error}</div>}

        <button onClick={submit} disabled={busy || !picked || !borrower.trim()}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-40"
          style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--gold-light)", borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowLeftRight className="w-4 h-4" />}
          Lend it
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="uppercase tracking-widest mb-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>{label}</div>
      {children}
    </div>
  );
}
