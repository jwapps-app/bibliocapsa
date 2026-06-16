import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const API = process.env.API_URL ?? "http://bibliocapsa:8000";

// Gate every page navigation: validate the session cookie against the backend
// and redirect to /login when it's missing, expired, or invalid. Backend-proxied
// paths (/api, /opds, KOSync) and static assets are excluded via the matcher.
export async function middleware(req: NextRequest) {
  const token = req.cookies.get("bibliocapsa_session")?.value;
  if (token) {
    try {
      const r = await fetch(`${API}/api/auth/me`, {
        headers: { Cookie: `bibliocapsa_session=${token}` },
        cache: "no-store",
      });
      if (r.ok) return NextResponse.next();
    } catch {
      // Backend unreachable — fall through to the login redirect.
    }
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|icon.svg|icons/|apple-touch-icon|pdf.worker.min.mjs|sw.js|manifest.webmanifest|login|api/|opds|healthcheck|users/|syncs/|dav).*)",
  ],
};
