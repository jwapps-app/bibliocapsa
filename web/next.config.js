/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Single source of truth for the displayed version — read from package.json at
  // build time, so dev builds and image builds both show the same number.
  env: { NEXT_PUBLIC_APP_VERSION: require("./package.json").version },
  images: { unoptimized: true },
  async rewrites() {
    const api = process.env.API_URL ?? "http://bibliocapsa:8000";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/opds/:path*", destination: `${api}/opds/:path*` },
      // KOReader sync server (KOSync) — served at the public root so devices
      // can point at the same base URL as Bibliocapsa itself.
      { source: "/healthcheck", destination: `${api}/healthcheck` },
      { source: "/users/:path*", destination: `${api}/users/:path*` },
      { source: "/syncs/:path*", destination: `${api}/syncs/:path*` },
      // WebDAV for KOReader statistics cloud-sync.
      { source: "/dav", destination: `${api}/dav` },
      { source: "/dav/:path*", destination: `${api}/dav/:path*` },
    ];
  },
};
module.exports = nextConfig;
