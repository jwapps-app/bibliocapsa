"use client";

import { useEffect } from "react";

// Registers the service worker (public/sw.js) once, after the page loads. Kept
// tiny and side-effect-only; rendered near the root so every route is covered.
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* registration is best-effort; the app works without it */
      });
    };
    if (document.readyState === "complete") register();
    else {
      window.addEventListener("load", register, { once: true });
      return () => window.removeEventListener("load", register);
    }
  }, []);
  return null;
}
