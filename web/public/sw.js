// Bibliocapsa service worker.
//
// Goals: make the app installable + resilient when the network drops, WITHOUT
// ever caching authenticated or dynamic data. Backend routes (the API, OPDS,
// WebDAV, KOSync) are deliberately passed straight through to the network — we
// only cache the static front-end shell (Next.js build output, icons, fonts).
//
// Bump CACHE when the caching logic changes; the activate handler purges any
// cache whose name doesn't match, so old shells don't linger.
const CACHE = "bibliocapsa-shell-v1";

// Paths owned by the backend — auth state, live data, large downloads. Never
// touched by the SW: no caching, no interception.
const BACKEND = /^\/(api|opds|dav|users|syncs|healthcheck)(\/|$)/;

// Minimal offline fallback shown when a navigation fails and nothing is cached.
const OFFLINE_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline — Bibliocapsa</title>
<style>html{height:100%}body{margin:0;height:100%;display:flex;align-items:center;
justify-content:center;background:#17130e;color:#f0e8d8;font-family:system-ui,
-apple-system,sans-serif;text-align:center}.b{max-width:22rem;padding:2rem}
h1{font-size:1.25rem;margin:0 0 .5rem;color:#c9933a}p{opacity:.8;line-height:1.5}</style>
</head><body><div class="b"><h1>You're offline</h1>
<p>Bibliocapsa can't reach the server right now. Reconnect and try again.</p></div></body></html>`;

self.addEventListener("install", (event) => {
  // Precache the start URL so the shell is available offline; skip waiting so a
  // new SW takes over on the next load rather than after every tab closes.
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.add(new Request("/", { cache: "reload" })).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Only handle same-origin requests; let the browser deal with the rest.
  if (url.origin !== self.location.origin) return;
  // Backend / authenticated / dynamic — hands off.
  if (BACKEND.test(url.pathname)) return;

  // Page navigations: network-first (always prefer fresh, auth-aware HTML), then
  // fall back to the cached shell, then the offline page.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/", copy)).catch(() => {});
          return res;
        })
        .catch(() =>
          caches.match(request).then(
            (r) => r || caches.match("/").then((shell) =>
              shell || new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
            )
          )
        )
    );
    return;
  }

  // Static build assets, icons, fonts, images: stale-while-revalidate.
  const isStatic =
    url.pathname.startsWith("/_next/static") ||
    url.pathname.startsWith("/icons/") ||
    /\.(?:js|css|png|jpg|jpeg|gif|svg|webp|ico|woff2?|ttf|mjs)$/.test(url.pathname);
  if (isStatic) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((res) => {
            if (res && res.status === 200) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
