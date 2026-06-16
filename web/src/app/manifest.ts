import type { MetadataRoute } from "next";

// Web App Manifest. Next.js serves this at /manifest.webmanifest and injects the
// <link rel="manifest"> automatically. Together with the service worker
// (public/sw.js) this makes Bibliocapsa an installable, standalone PWA.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Bibliocapsa",
    short_name: "Bibliocapsa",
    description: "Your personal library — ebooks and physical books — with KOReader sync.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#17130e",
    theme_color: "#17130e",
    categories: ["books", "education", "productivity"],
    icons: [
      { src: "/icons/pwa-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/pwa-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/pwa-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
