import type { Metadata, Viewport } from "next";
import { Playfair_Display, Crimson_Pro, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Self-hosted fonts (downloaded at build time, served from /_next/static).
// The old Google Fonts @import was blocked by our CSP (style-src 'self'), so
// the intended typography never actually loaded through the proxy.
const playfair = Playfair_Display({ subsets: ["latin"], style: ["normal", "italic"], variable: "--font-playfair" });
const crimson  = Crimson_Pro({ subsets: ["latin"], style: ["normal", "italic"], variable: "--font-crimson" });
const inter    = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jbmono   = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jbmono" });
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
