"use client";

import { useEffect, useState } from "react";
import DOMPurify from "dompurify";

/** Renders untrusted HTML (e.g. a Calibre book description, which can contain
 *  arbitrary markup) after sanitizing it with DOMPurify — strips <script>,
 *  event handlers, javascript: URLs, etc. Sanitization runs in the browser, so
 *  nothing unsafe is ever inserted into the DOM. */
export function SafeHtml({ html, className, style }:
  { html: string; className?: string; style?: React.CSSProperties }) {
  const [clean, setClean] = useState("");
  useEffect(() => {
    setClean(DOMPurify.sanitize(html || "", { USE_PROFILES: { html: true } }));
  }, [html]);
  return <div className={className} style={style} dangerouslySetInnerHTML={{ __html: clean }} />;
}
