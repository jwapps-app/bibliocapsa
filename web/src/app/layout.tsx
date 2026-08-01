import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Fonts are VENDORED (./fonts/*.woff2, latin subset, variable weight) and served
// from /_next/static. They used to come from `next/font/google`, which downloads
// them during `next build` - that made the image build depend on network access,
// and it timed out under QEMU-emulated arm64 whenever a dependency change
// invalidated the layer cache. Vendoring keeps builds offline and reproducible.
// All four families are SIL Open Font License 1.1 (see fonts/OFL.txt).
// To refresh: re-download the latin woff2 from Google Fonts into ./fonts.
const playfair = localFont({
  src: [{ path: "./fonts/playfair.woff2", style: "normal" },
        { path: "./fonts/playfair-italic.woff2", style: "italic" }],
  weight: "400 900", display: "swap", variable: "--font-playfair",
});
const crimson = localFont({
  src: [{ path: "./fonts/crimson.woff2", style: "normal" },
        { path: "./fonts/crimson-italic.woff2", style: "italic" }],
  weight: "200 900", display: "swap", variable: "--font-crimson",
});
const inter  = localFont({ src: "./fonts/inter.woff2",  weight: "100 900", display: "swap", variable: "--font-inter" });
const jbmono = localFont({ src: "./fonts/jbmono.woff2", weight: "100 800", display: "swap", variable: "--font-jbmono" });
const fontVars = `${playfair.variable} ${crimson.variable} ${inter.variable} ${jbmono.variable}`;
import { FaviconManager } from "@/components/FaviconManager";
import { ServiceWorkerRegister } from "./sw-register";

export const metadata: Metadata = {
  title: { default: "Bibliocapsa", template: "%s — Bibliocapsa" },
  description: "Your personal library, beautifully organized.",
  // Default iOS home-screen icon (the active theme overrides this client-side).
  icons: { apple: "/icons/library.png" },
  appleWebApp: { capable: true, title: "Bibliocapsa", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  // Matches the manifest background so the iOS/Android status bar and splash
  // blend into the app shell.
  themeColor: "#17130e",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={fontVars}>
      <head>
        {/* Apply saved theme/font before paint to avoid a flash */}
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('bc-theme'),f=localStorage.getItem('bc-font');if(t)document.documentElement.dataset.theme=t;if(f)document.documentElement.dataset.font=f;}catch(e){}})();` }} />
      </head>
      <body><FaviconManager /><ServiceWorkerRegister />{children}</body>
    </html>
  );
}
