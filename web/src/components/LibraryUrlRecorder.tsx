"use client";

import { useEffect } from "react";

/** Records the current library/list URL (path + filters) so the book detail's
 *  "Library" link can return there directly — preserving the filter without
 *  relying on history.back() (which loops when you arrive from the reader). */
export function LibraryUrlRecorder() {
  useEffect(() => {
    try { sessionStorage.setItem("bc:lib", window.location.pathname + window.location.search); } catch {}
  });
  return null;
}
