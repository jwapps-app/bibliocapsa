"use client";
import { useState, useEffect } from "react";
import { Grid, Layers, Users, Tag, ChevronLeft, ChevronRight, ArrowLeftRight, Plus, Sparkles, Settings, Menu, X, LogOut, BarChart3, Bookmark } from "lucide-react";
import clsx from "clsx";
import { api, type CurrentUser } from "@/lib/api";
import { ThemePicker } from "@/components/ThemePicker";
import { BookLogo } from "@/components/BookLogo";

interface ShelfItem { id: number; name: string; is_smart: boolean; book_count: number; }

interface SidebarProps {
  currentParams: Record<string, string | undefined>;
  bookCount?: number;
}

export function Sidebar({ currentParams, bookCount }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [shelves, setShelves] = useState<ShelfItem[]>([]);
  const [showNewShelf, setShowNewShelf] = useState(false);
  const [newShelfName, setNewShelfName] = useState("");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const activeView = currentParams.view;
  const activeShelf = currentParams.shelf ? Number(currentParams.shelf) : null;

  useEffect(() => {
    fetch("/api/shelves")
      .then(r => (r.ok ? r.json() : []))
      .then(d => setShelves(Array.isArray(d) ? d : []))  // never let a bad response crash the app
      .catch(() => {});
    api.me().then(setUser).catch(() => {});
    fetch("/api/counts").then(r => (r.ok ? r.json() : {})).then(d => setCounts(d || {})).catch(() => {});
  }, []);

  const logout = async () => {
    await api.logout();
    window.location.href = "/login";
  };

  // Close mobile drawer on navigation
  useEffect(() => { setMobileOpen(false); }, [currentParams]);

  const deleteShelf = async (shelfId: number) => {
    if (!confirm("Delete this shelf?")) return;
    await fetch(`/api/shelves/${shelfId}`, { method: "DELETE" });
    setShelves(prev => prev.filter(s => s.id !== shelfId));
    if (activeShelf === shelfId) window.location.href = "/";
  };

  const createShelf = async () => {
    if (!newShelfName.trim()) return;
    const res = await fetch("/api/shelves", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newShelfName.trim(), is_smart: false }),
    });
    if (res.ok) {
      const shelf = await res.json();
      setShelves(prev => [...prev, shelf]);
      setNewShelfName("");
      setShowNewShelf(false);
    }
  };

  const navItems = [
    { href: "/",              label: "Library",   view: undefined,  Icon: Grid,          countKey: "books" },
    { href: "/?view=series",  label: "Series",    view: "series",   Icon: Layers,        countKey: "series" },
    { href: "/?view=authors", label: "Authors",   view: "authors",  Icon: Users,         countKey: "authors" },
    { href: "/?view=tags",    label: "Genres",    view: "tags",     Icon: Tag,           countKey: "genres" },
    { href: "/?view=lending", label: "Lending",   view: "lending",  Icon: ArrowLeftRight, countKey: "lending" },
    { href: "/wishlist",      label: "Want to Read", view: undefined, Icon: Bookmark,    countKey: "wishlist" },
    { href: "/stats",         label: "Statistics", view: undefined, Icon: BarChart3,     countKey: undefined },
  ];

  const smartShelves = shelves.filter(s => s.is_smart);
  const manualShelves = shelves.filter(s => !s.is_smart);

  const SidebarContent = ({ onNavigate }: { onNavigate?: () => void }) => (
    <>
      {/* Main nav */}
      <nav className="flex flex-col gap-0.5 px-2 pt-3 pb-2">
        {navItems.map(({ href, label, view, Icon, countKey }) => {
          const active = view
            ? activeView === view
            : href === "/" && !activeView && !activeShelf && !currentParams.search &&
              !currentParams.series_id && !currentParams.author_id && !currentParams.tag_id;
          const count = countKey ? counts[countKey] : undefined;
          return (
            <a key={href} href={href} onClick={onNavigate}
              className="flex items-center gap-3 px-3 py-2 rounded-sm transition-all"
              style={{
                background: active ? "rgba(107,78,30,0.35)" : "transparent",
                color: active ? "var(--gold-light)" : "var(--parchment)",
                opacity: active ? 1 : 0.85,
                fontFamily: "var(--body)", fontSize: "0.95rem",
              }}>
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span>{label}</span>}
              {!collapsed && count != null && (
                <span className="ml-auto" style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--parchment-dim)", opacity: 0.55 }}>
                  {count.toLocaleString()}
                </span>
              )}
            </a>
          );
        })}

      </nav>

      <hr style={{ border: "none", height: "1px", background: "linear-gradient(90deg,transparent,var(--gold-dim),transparent)", margin: "4px 12px" }} />

      {/* Shelves */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 pb-4 mt-2 space-y-4">
          {smartShelves.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 px-3 mb-1"
                style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.45, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                <Sparkles className="w-3 h-3" />
                Smart Shelves
              </div>
              {smartShelves.map(shelf => (
                <a key={shelf.id} href={`/?view=shelf&shelf=${shelf.id}`} onClick={onNavigate}
                  className="flex items-center justify-between gap-2 px-3 py-1.5 rounded-sm transition-all"
                  style={{
                    background: activeShelf === shelf.id ? "rgba(107,78,30,0.25)" : "transparent",
                    color: activeShelf === shelf.id ? "var(--gold-light)" : "var(--parchment)",
                    opacity: activeShelf === shelf.id ? 1 : 0.8,
                    fontFamily: "var(--body)", fontSize: "0.875rem",
                  }}>
                  <span className="truncate">{shelf.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
                    {shelf.book_count}
                  </span>
                </a>
              ))}
            </div>
          )}

          <a href="/shelves/new" onClick={onNavigate}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.2)]"
            style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--gold-light)", opacity: 0.85 }}>
            <Sparkles className="w-3 h-3" /> New smart shelf…
          </a>

          <div>
            <div className="flex items-center justify-between px-3 mb-1">
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.45, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Shelves
              </div>
              <button onClick={() => setShowNewShelf(!showNewShelf)}
                className="transition-opacity hover:opacity-100"
                style={{ opacity: 0.45, color: "var(--parchment-dim)" }}
                title="New shelf">
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>

            {showNewShelf && (
              <div className="px-3 mb-2">
                <div className="flex gap-1">
                  <input type="text" value={newShelfName}
                    onChange={e => setNewShelfName(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") createShelf(); if (e.key === "Escape") setShowNewShelf(false); }}
                    placeholder="Shelf name…" autoFocus
                    className="flex-1 px-2 py-1 rounded-sm text-sm"
                    style={{ background: "var(--ink-muted)", border: "1px solid var(--gold-dim)", color: "var(--parchment)", fontFamily: "var(--body)", fontSize: "0.8rem" }}
                  />
                  <button onClick={createShelf}
                    className="px-2 py-1 rounded-sm text-xs transition-colors hover:opacity-80"
                    style={{ background: "var(--gold-dim)", color: "var(--gold-light)", fontFamily: "var(--mono)" }}>
                    +
                  </button>
                </div>
              </div>
            )}

            {manualShelves.length === 0 && !showNewShelf && (
              <div className="px-3 py-1" style={{ fontFamily: "var(--body)", fontSize: "0.8rem", color: "var(--parchment-dim)", opacity: 0.4, fontStyle: "italic" }}>
                No shelves yet
              </div>
            )}

            {manualShelves.map(shelf => (
              <div key={shelf.id} className="flex items-center group/shelf">
                <a href={`/?view=shelf&shelf=${shelf.id}`} onClick={onNavigate}
                  className="flex-1 flex items-center justify-between px-3 py-1.5 rounded-sm transition-all min-w-0"
                  style={{
                    background: activeShelf === shelf.id ? "rgba(107,78,30,0.25)" : "transparent",
                    color: activeShelf === shelf.id ? "var(--gold-light)" : "var(--parchment)",
                    opacity: activeShelf === shelf.id ? 1 : 0.8,
                    fontFamily: "var(--body)", fontSize: "0.875rem",
                  }}>
                  <span className="truncate">{shelf.name}</span>
                  {shelf.book_count > 0 && (
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.5 }}>
                      {shelf.book_count}
                    </span>
                  )}
                </a>
                <button onClick={() => deleteShelf(shelf.id)}
                  className="opacity-0 group-hover/shelf:opacity-40 hover:!opacity-100 transition-opacity px-1.5 py-1.5 shrink-0"
                  style={{ color: "var(--parchment-dim)" }}
                  title="Delete shelf">
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* User · settings · appearance · logout footer */}
      <div className="mt-auto border-t px-2 py-2" style={{ borderColor: "var(--ink-muted)" }}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-1">
            <a href="/settings" onClick={() => onNavigate?.()} title="Settings"
              className="p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
              style={{ color: "var(--parchment-dim)" }}>
              <Settings className="w-4 h-4" />
            </a>
            <ThemePicker iconOnly collapsed />
            <button onClick={logout} title="Sign out"
              className="p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
              style={{ color: "var(--parchment-dim)" }}>
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-0.5 px-1 py-0.5">
            <div className="min-w-0 flex-1">
              <div className="truncate" style={{ fontFamily: "var(--body)", fontSize: "0.85rem", color: "var(--parchment)" }}>
                {user ? user.name || user.username : "—"}
              </div>
              {user && (
                <div style={{ fontFamily: "var(--mono)", fontSize: "0.6rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                  @{user.username}{user.role === "admin" ? " · admin" : ""}
                </div>
              )}
            </div>
            <a href="/settings" onClick={() => onNavigate?.()} title="Settings"
              className="shrink-0 p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
              style={{ color: "var(--parchment-dim)" }}>
              <Settings className="w-4 h-4" />
            </a>
            <ThemePicker iconOnly />
            <button onClick={logout} title="Sign out"
              className="shrink-0 p-1.5 rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]"
              style={{ color: "var(--parchment-dim)" }}>
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
        {!collapsed && process.env.NEXT_PUBLIC_APP_VERSION && (
          <div className="text-center pt-1.5" style={{ fontFamily: "var(--mono)", fontSize: "0.55rem", color: "var(--parchment-dim)", opacity: 0.4 }}>
            Bibliocapsa v{process.env.NEXT_PUBLIC_APP_VERSION}
          </div>
        )}
      </div>
    </>
  );

  return (
    <>
      {/* ── Mobile hamburger button (shown only on small screens) ── */}
      <button
        onClick={() => setMobileOpen(true)}
        className="lg:hidden fixed top-3 left-4 z-50 w-9 h-9 flex items-center justify-center rounded-sm"
        style={{ background: "var(--ink-soft)", border: "1px solid var(--ink-muted)", color: "var(--parchment-dim)" }}>
        <Menu className="w-5 h-5" />
      </button>

      {/* ── Mobile drawer overlay ── */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40" onClick={() => setMobileOpen(false)}
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(2px)" }} />
      )}

      {/* ── Mobile drawer ── */}
      <div className={clsx(
        "lg:hidden fixed top-0 left-0 z-50 h-full w-72 flex flex-col transition-transform duration-300",
        mobileOpen ? "translate-x-0" : "-translate-x-full"
      )} style={{ background: "var(--ink-soft)", borderRight: "1px solid var(--ink-muted)" }}>
        {/* Mobile header */}
        <div className="flex items-center gap-3 px-4 py-5 border-b" style={{ borderColor: "var(--ink-muted)" }}>
          <BookLogo className="w-9 h-9 shrink-0" />
          <div className="min-w-0 flex-1">
            <div style={{ fontFamily: "var(--serif)", fontSize: "1.1rem", fontWeight: 600, color: "var(--parchment)" }}>
              Bibliocapsa
            </div>
            {bookCount && (
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                {bookCount.toLocaleString()} books
              </div>
            )}
          </div>
          <button onClick={() => setMobileOpen(false)} style={{ color: "var(--parchment-dim)", opacity: 0.6 }}>
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto flex flex-col">
          <SidebarContent onNavigate={() => setMobileOpen(false)} />
        </div>
      </div>

      {/* ── Desktop sidebar (hidden on mobile) ── */}
      <aside
        className={clsx("hidden lg:flex flex-col shrink-0 transition-all duration-300 border-r", collapsed ? "w-14" : "w-64")}
        style={{ height: "100vh", overflowY: "auto", background: "var(--ink-soft)", borderColor: "var(--ink-muted)" }}>
        {/* Logo */}
        <div className={clsx("flex items-center border-b py-5", collapsed ? "flex-col gap-2 px-2" : "gap-3 px-4")}
             style={{ borderColor: "var(--ink-muted)" }}>
          <BookLogo className="w-9 h-9 shrink-0" />
          {!collapsed && (
            <div className="min-w-0">
              <div style={{ fontFamily: "var(--serif)", fontSize: "1.1rem", fontWeight: 600, color: "var(--parchment)" }}>
                Bibliocapsa
              </div>
              {bookCount && (
                <div style={{ fontFamily: "var(--mono)", fontSize: "0.65rem", color: "var(--parchment-dim)", opacity: 0.6 }}>
                  {bookCount.toLocaleString()} books
                </div>
              )}
            </div>
          )}
          <button onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand menu" : "Collapse menu"}
            className={clsx("flex items-center justify-center rounded-sm transition-colors hover:bg-[rgba(107,78,30,0.25)]", collapsed ? "w-8 h-8" : "ml-auto p-1.5")}
            style={{ color: collapsed ? "var(--gold-light)" : "var(--parchment-dim)", border: collapsed ? "1px solid var(--gold-dim)" : "none" }}>
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
        <SidebarContent />
      </aside>
    </>
  );
}
