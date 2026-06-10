import type { Metadata, Viewport } from "next";
import "./globals.css";
import { FaviconManager } from "@/components/FaviconManager";

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
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Apply saved theme/font before paint to avoid a flash */}
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('bc-theme'),f=localStorage.getItem('bc-font');if(t)document.documentElement.dataset.theme=t;if(f)document.documentElement.dataset.font=f;}catch(e){}})();` }} />
      </head>
      <body><FaviconManager />{children}</body>
    </html>
  );
}
