const BASE = typeof window === "undefined" ? (process.env.API_URL ?? "http://bibliocapsa:8000") : "";

export interface Author   { id: number; name: string; sort?: string; book_count?: number; }
export interface SeriesRef { id: number; name: string; series_index?: number; }
export interface TagRef    { id: number; name: string; }
export interface FormatRef { format: string; size?: number; }

export interface BookSummary {
  id: number; title: string; sort?: string;
  authors: Author[]; series?: SeriesRef; tags: TagRef[];
  pubdate?: string; cover_url?: string; has_cover: boolean;
  rating?: number; community_rating?: number | null; last_modified?: string;
  reading_status?: string | null; date_read?: string | null;  // unified read status
  book_source?: string;       // "calibre" = digital, "native" = physical
  has_physical?: boolean;     // also owned as physical copy
  has_digital?: boolean;      // also owned as digital copy
  physical_location?: string; // where the physical copy lives
}
export interface CustomColumn { label: string; name: string; datatype: string; is_multiple: boolean; value: any; }
export interface BookDetail extends BookSummary {
  comment?: string; publisher?: string; isbn?: string;
  uuid?: string; formats: FormatRef[]; path?: string; series_index?: number;
  custom?: CustomColumn[];
}
export interface NativeBook {
  id: number; title: string; author?: string;
  isbn?: string; isbn13?: string; cover_url?: string; description?: string;
  page_count?: number; publisher?: string; published_date?: string;
  categories?: string[]; language?: string; format: string; location?: string;
  rating?: number; community_rating?: number | null; reading_status?: string | null; date_read?: string | null;
  cover_variant?: number | null;
}
export interface NativeBookUpdate {
  title?: string;
  author?: string | null;
  isbn?: string | null;
  isbn13?: string | null;
  cover_url?: string | null;
  description?: string | null;
  page_count?: number | null;
  publisher?: string | null;
  published_date?: string | null;
  categories?: string[] | null;
  language?: string | null;
  format?: string;
  location?: string | null;
  rating?: number | null;
  reading_status?: string | null;
  date_read?: string | null;
}
export interface PaginatedBooks {
  total: number; page: number; page_size: number; pages: number; items: BookSummary[];
}
export interface SeriesSummary { id: number; name: string; book_count: number; first_book_id?: number; first_book_cover_url?: string; first_book_has_cover: boolean; }
export interface SeriesDetail  { id: number; name: string; book_count: number; books: BookSummary[]; }
export interface AuthorDetail  { id: number; name: string; sort?: string; book_count: number; books: BookSummary[]; }
export interface TagDetail     { id: number; name: string; book_count: number; }
export interface HealthResponse { status: string; calibre_db: string; book_count: number; version: string; }
export interface SearchResult  {
  book_id: number; title: string; authors: string[]; format: string;
  excerpt: string; cover_url?: string; has_cover: boolean;
}
export interface SearchResponse { query: string; total: number; results: SearchResult[]; }
export interface CurrentUser { id: number; name: string; username: string; email?: string; role: string; kindle_email?: string | null; theme?: string | null; font?: string | null; }
export interface Loan {
  id: number; book_id: number; book_source: string;
  borrower_name: string; borrower_email?: string; borrower_phone?: string;
  loan_date?: string; due_date?: string; returned_date?: string;
  notes?: string; is_overdue: boolean;
  book_title?: string; cover_url?: string; has_cover: boolean;
}

async function get<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {};
  // On the server (SSR), forward the caller's session cookie to the backend so
  // protected routes authenticate. On the client, the browser sends it itself.
  if (typeof window === "undefined") {
    const { cookies } = await import("next/headers");
    const session = cookies().get("bibliocapsa_session");
    if (session) headers["Cookie"] = `bibliocapsa_session=${session.value}`;
  }
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", headers, credentials: "same-origin" });
  if (!res.ok) throw new Error(`${res.status}: ${path}`);
  return res.json();
}

export function publicUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  // Strip the host — proxy through Next.js so it works on any device
  return url.replace(/^https?:\/\/[^/]+/, "");
}

export const api = {
  health:       ()                  => get<HealthResponse>("/api/health"),
  books:        (p: Record<string, string|number|undefined> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(p).filter(([,v])=>v!==undefined).map(([k,v])=>[k,String(v)])
    ).toString();
    return get<PaginatedBooks>(`/api/books${qs?`?${qs}`:""}`);
  },
  book:         (id: number)        => get<BookDetail>(`/api/books/${id}`),
  editCalibreBook: async (id: number, fields: Record<string, unknown>): Promise<void> => {
    const res = await fetch(`/api/calibre/books/${id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not save edit");
  },
  discardCalibreEdits: async (id: number): Promise<void> => {
    await fetch(`/api/calibre/books/${id}`, { method: "DELETE" }).catch(() => {});
  },
  lookupMetadata: async (title: string, author?: string): Promise<any[]> => {
    const qs = new URLSearchParams({ title, ...(author ? { author } : {}) }).toString();
    const res = await fetch(`/api/calibre/lookup?${qs}`);
    return res.ok ? res.json() : [];
  },
  missingBooks: async (field = "description", page = 1, pageSize = 50): Promise<{ total: number; field: string; items: { id: number; title: string; author: string }[] }> => {
    const res = await fetch(`/api/calibre/missing?field=${field}&page=${page}&page_size=${pageSize}`);
    return res.ok ? res.json() : { total: 0, field, items: [] };
  },
  startEnrich: async (force = false): Promise<any> => {
    const res = await fetch(`/api/calibre/enrich${force ? "?force=true" : ""}`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not start");
    return res.json();
  },
  enrichStatus: async (): Promise<any> => {
    const res = await fetch("/api/calibre/enrich/status");
    return res.ok ? res.json() : null;
  },
  cancelEnrich: async (): Promise<void> => { await fetch("/api/calibre/enrich/cancel", { method: "POST" }).catch(() => {}); },
  // Uses get() so it also resolves during SSR (BASE + cookie forwarding) — the
  // server-rendered sort menu reads this to hide the mapped Date Read column.
  getReadingMap: () => get<{ read: string | null; progress: string | null; date: string | null }>("/api/calibre/reading-map"),
  saveReadingMap: async (body: { read?: string | null; progress?: string | null; date?: string | null }): Promise<void> => {
    await fetch("/api/calibre/reading-map", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => {});
  },
  runReadingSync: async (): Promise<{ queued: number; books_with_progress: number }> => {
    const res = await fetch("/api/calibre/reading-sync", { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Failed");
    return res.json();
  },
  setCommunityRating: async (id: number, rating: number): Promise<void> => {
    await fetch(`/api/calibre/community-rating/${id}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rating }),
    }).catch(() => {});
  },
  // Digital (Calibre) read/unread status — Bibliocapsa's own store (+ optional
  // write-back to a mapped Calibre column).
  getCalibreReadStatus: (id: number) =>
    get<{ status: string | null; date_read: string | null }>(`/api/calibre/read-status/${id}`),
  setCalibreReadStatus: async (id: number, body: { status: string | null; date_read?: string | null }):
    Promise<{ status: string | null; date_read: string | null }> => {
    const res = await fetch(`/api/calibre/read-status/${id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Failed");
    return res.json();
  },
  // Per-user read history (running list of finish dates; manual add/adjust/delete).
  readHistory: (source: string, id: number) =>
    get<{ id: number; date_read: string | null; source: string | null; ts: number }[]>(`/api/reading/history/${source}/${id}`),
  addReadDate: async (source: string, id: number, date_read?: string | null) => {
    const res = await fetch(`/api/reading/history/${source}/${id}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date_read }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Failed");
    return res.json();
  },
  editReadDate: async (entryId: number, date_read: string | null) => {
    await fetch(`/api/reading/history/entry/${entryId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date_read }),
    });
  },
  deleteReadDate: async (entryId: number) => {
    await fetch(`/api/reading/history/entry/${entryId}`, { method: "DELETE" });
  },
  statsSummary: (days = 0) => get<any>(`/api/stats/summary${days ? `?days=${days}` : ""}`),
  bookStats: (id: number) => get<any>(`/api/stats/book/${id}`),
  getGoal: (year?: number) => get<{ year: number; target: number | null; count: number }>(`/api/stats/goal${year ? `?year=${year}` : ""}`),
  yearReview: (year?: number) => get<{ year: number; total_books: number; by_month: number[]; by_format: { digital: number; physical: number }; top_authors: { name: string; count: number }[]; top_genres: { name: string; count: number }[] }>(`/api/stats/year${year ? `?year=${year}` : ""}`),
  wishlist: () => get<{ id: number; title: string; author: string | null; isbn: string | null; cover_url: string | null; notes: string | null; book_id: number | null; book_source: string | null }[]>("/api/wishlist"),
  addWishlist: async (item: { title: string; author?: string; isbn?: string; cover_url?: string; notes?: string; book_id?: number; book_source?: string }): Promise<{ id: number }> => {
    const res = await fetch("/api/wishlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item) });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  removeWishlist: async (id: number): Promise<void> => { await fetch(`/api/wishlist/${id}`, { method: "DELETE" }); },
  wishlistContains: (bookId: number, bookSource = "calibre") => get<{ bookmarked: boolean; id: number | null }>(`/api/wishlist/contains?book_id=${bookId}&book_source=${bookSource}`),
  setGoal: async (year: number, target: number): Promise<{ year: number; target: number | null; count: number }> => {
    const res = await fetch("/api/stats/goal", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ year, target }) });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  previewShelf: async (rules: any): Promise<number> => {
    const res = await fetch("/api/shelves/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ smart_rules: rules }),
    });
    return res.ok ? (await res.json()).count : 0;
  },
  // Uses get() so it works during SSR too (BASE + session cookie forwarding) —
  // the server-rendered Sort control reads custom date columns from here.
  customColumns: () => get<{ label: string; name: string; datatype: string; is_multiple: boolean }[]>("/api/calibre/custom-columns"),
  calibrePending: async (): Promise<{ count: number; books: number; items: any[]; uploads: any[] }> => {
    const res = await fetch("/api/calibre/pending");
    return res.ok ? res.json() : { count: 0, books: 0, items: [], uploads: [] };
  },
  uploadCalibreBook: async (file: File): Promise<any> => {
    const fd = new FormData(); fd.append("file", file);
    const res = await fetch("/api/calibre/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Upload failed");
    return res.json();
  },
  discardUpload: async (id: number): Promise<void> => {
    await fetch(`/api/calibre/uploads/${id}`, { method: "DELETE" }).catch(() => {});
  },
  calibrePendingCount: async (): Promise<number> => {
    const res = await fetch("/api/calibre/pending/count");
    return res.ok ? (await res.json()).count : 0;
  },
  syncToCalibre: async (): Promise<{ synced: number; failed: any[]; remaining: number }> => {
    const res = await fetch("/api/calibre/sync", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Sync failed");
    return res.json();
  },
  nativeBook:   (id: number)        => get<NativeBook>(`/api/native/books/${id}`),
  createNativeBook: async (body: Record<string, unknown>): Promise<NativeBook> => {
    const res = await fetch("/api/native/books", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not add book");
    return res.json();
  },
  updateNativeBook: async (id: number, body: NativeBookUpdate): Promise<NativeBook> => {
    const res = await fetch(`/api/native/books/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return res.json();
  },
  uploadNativeCover: async (id: number, file: File): Promise<NativeBook> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/native/books/${id}/cover`, { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return res.json();
  },
  deleteNativeCover: async (id: number): Promise<NativeBook> => {
    const res = await fetch(`/api/native/books/${id}/cover`, { method: "DELETE" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return res.json();
  },
  regenerateNativeCover: async (id: number): Promise<NativeBook> => {
    const res = await fetch(`/api/native/books/${id}/cover/generate`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return res.json();
  },
  authors:      (p: Record<string,string|number|undefined>={}) => {
    const qs = new URLSearchParams(Object.entries(p).filter(([,v])=>v!==undefined).map(([k,v])=>[k,String(v)])).toString();
    return get<Author[]>(`/api/authors${qs?`?${qs}`:""}`);
  },
  author:       (id: number)        => get<AuthorDetail>(`/api/authors/${id}`),
  series:       (p: Record<string,string|number|undefined>={}) => {
    const qs = new URLSearchParams(Object.entries(p).filter(([,v])=>v!==undefined).map(([k,v])=>[k,String(v)])).toString();
    return get<SeriesSummary[]>(`/api/series${qs?`?${qs}`:""}`);
  },
  seriesDetail: (id: number)        => get<SeriesDetail>(`/api/series/${id}`),
  seriesNextIndex: async (name: string): Promise<number> => {
    const res = await fetch(`/api/series/next-index?name=${encodeURIComponent(name)}`);
    return res.ok ? (await res.json()).next_index : 1;
  },
  tags:         ()                  => get<TagDetail[]>("/api/tags?page_size=5000"),
  search:       (q: string, limit=20) => get<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  fileUrl:      (id: number, fmt: string) => `/api/books/${id}/file/${fmt.toLowerCase()}`,

  // ── Reading progress (browser reader ↔ KOReader sync) ──
  bookProgress: async (id: number, format = "epub"): Promise<{
    browser: { cfi?: string; percentage?: number; ts?: number } | null;
    synced: { percentage?: number; progress?: string; device?: string; ts?: number } | null;
  }> => {
    const res = await fetch(`/api/reading/book/${id}?format=${format}`);
    return res.ok ? res.json() : { browser: null, synced: null };
  },
  saveBookProgress: async (id: number, percentage: number, cfi?: string, ko_progress?: string, format = "epub"): Promise<void> => {
    await fetch(`/api/reading/book/${id}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ percentage, cfi, ko_progress, format }),
    }).catch(() => {});
  },

  // ── Auth (client-side; browser carries the cookie) ──
  login: async (username: string, password: string): Promise<CurrentUser> => {
    const res = await fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Login failed");
    return res.json();
  },
  register: async (body: { username: string; password: string; name?: string; email?: string; role?: string; genres?: string[] }): Promise<CurrentUser> => {
    const res = await fetch("/api/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Registration failed");
    return res.json();
  },
  logout: async (): Promise<void> => { await fetch("/api/auth/logout", { method: "POST" }); },
  updateMe: async (body: { kindle_email?: string }): Promise<CurrentUser> => {
    const res = await fetch("/api/auth/me", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not save");
    return res.json();
  },
  savePreferences: async (body: { theme?: string; font?: string }): Promise<void> => {
    await fetch("/api/auth/preferences", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).catch(() => {});
  },
  sendToKindle: async (id: number): Promise<{ sent_to: string; format: string }> => {
    const res = await fetch(`/api/books/${id}/send-to-kindle`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Send failed");
    return res.json();
  },
  me:     async (): Promise<CurrentUser | null> => {
    const res = await fetch("/api/auth/me");
    return res.ok ? res.json() : null;
  },
  loans: async (activeOnly = true): Promise<Loan[]> => {
    const res = await fetch(`/api/lending?active_only=${activeOnly}`);
    return res.ok ? res.json() : [];
  },
  createLoan: async (body: { book_id: number; book_source: string; borrower_name: string; borrower_email?: string; due_date?: string; notes?: string }): Promise<Loan> => {
    const res = await fetch("/api/lending", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not create loan");
    return res.json();
  },
  updateLoan: async (id: number, body: { due_date?: string; returned_date?: string; notes?: string }): Promise<Loan> => {
    const res = await fetch(`/api/lending/${id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not update loan");
    return res.json();
  },
  setUserAccess: async (userId: number, genres: string[]): Promise<{ genres: string[] }> => {
    const res = await fetch(`/api/auth/users/${userId}/access`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ genres }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not update access");
    return res.json();
  },
  adminResetPassword: async (userId: number, new_password: string): Promise<void> => {
    const res = await fetch(`/api/auth/users/${userId}/password`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not reset password");
  },
  changePassword: async (new_password: string, current_password?: string): Promise<void> => {
    const res = await fetch("/api/auth/password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password, current_password }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Could not change password");
  },
};
