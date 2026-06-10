"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { applyFavicon, applyAppleIcon } from "@/lib/favicon";

/** Mounted in the root layout so the theme-aware favicon is (re)applied on EVERY
 *  page — including Settings/Stats, which don't render the sidebar/ThemePicker.
 *  Re-runs on each navigation so the browser never falls back to its default. */
export function FaviconManager() {
  const pathname = usePathname();
  useEffect(() => {
    const theme = document.documentElement.dataset.theme || "library";
    applyFavicon();
    applyAppleIcon(theme);
  }, [pathname]);
  return null;
}
