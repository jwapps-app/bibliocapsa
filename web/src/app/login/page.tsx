"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { BookOpen, Loader2 } from "lucide-react";

function LoginInner() {
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((d) => setSetupRequired(!!d.setup_required))
      .catch(() => setSetupRequired(false));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (setupRequired && password !== confirmPassword) {
      setError("Passwords don't match — please re-type to confirm.");
      return;
    }
    setBusy(true); setError(null);
    try {
      if (setupRequired) {
        await api.register({ username, password, name: name || undefined });
      } else {
        await api.login(username, password);
      }
      // Full navigation so the middleware re-validates and SSR sees the cookie.
      window.location.href = next;
    } catch (err: any) {
      setError(err.message ?? "Something went wrong");
      setBusy(false);
    }
  }

  const heading = setupRequired ? "Welcome to Bibliocapsa" : "Bibliocapsa";
  const subtitle = setupRequired
    ? "Create the first account — it will be the library administrator."
    : "Sign in to your library.";

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <BookOpen className="w-9 h-9 mb-3" style={{ color: "var(--gold)" }} />
          <h1 style={{ fontFamily: "var(--serif)", fontSize: "1.9rem", fontWeight: 400, color: "var(--parchment)" }}>
            {heading}
          </h1>
          <p className="mt-1 text-center" style={{ fontFamily: "var(--body)", fontSize: "0.95rem", color: "var(--parchment-dim)" }}>
            {subtitle}
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4">
          {setupRequired && (
            <div>
              <Label>Display name (optional)</Label>
              <input className="bc-input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </div>
          )}
          <div>
            <Label>Username</Label>
            <input className="bc-input" value={username} onChange={(e) => setUsername(e.target.value)}
                   autoComplete="username" autoFocus required />
          </div>
          <div>
            <Label>Password</Label>
            <input className="bc-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                   autoComplete={setupRequired ? "new-password" : "current-password"} required />
          </div>
          {setupRequired && (
            <div>
              <Label>Confirm password</Label>
              <input className="bc-input" type="password" value={confirmPassword}
                     onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" required />
            </div>
          )}

          {error && (
            <div style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", color: "#d98a8a" }}>{error}</div>
          )}

          <button type="submit" disabled={busy || setupRequired === null}
            className="mt-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-sm border transition-colors hover:border-[var(--gold)] disabled:opacity-50"
            style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", color: "var(--gold-light)",
                     borderColor: "var(--gold-dim)", background: "rgba(107,78,30,0.2)" }}>
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {setupRequired ? "Create account" : "Sign in"}
          </button>

          {setupRequired && (
            <p className="text-center mt-1" style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.7 }}>
              KOReader devices log in with this same username & password.
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="uppercase tracking-widest mb-1.5"
         style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
      {children}
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
