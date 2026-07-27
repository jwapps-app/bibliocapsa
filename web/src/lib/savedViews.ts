import type { SavedViewConfig } from "./api";

/** The library URL params a saved view round-trips through. */
export type ViewParams = {
  search?: string; series_id?: string; author_id?: string; tag_id?: string;
  sort_by?: string; sort_dir?: string; collapse?: string;
  format?: string; read?: string;
};

/**
 * Current URL params -> the shared, client-agnostic config.
 *
 * Series/author/tag are stored by NAME, not by Calibre id: the iOS app mirrors
 * the catalog locally and knows names but not Calibre's integer ids, so a
 * name-keyed view resolves on either client (and offline on the phone). The
 * caller passes the display name it already rendered for the active filter.
 */
export function paramsToConfig(p: ViewParams, activeFilterName?: string): SavedViewConfig {
  let filter: SavedViewConfig["filter"] = null;
  if (activeFilterName) {
    if (p.series_id) filter = { type: "series", value: activeFilterName };
    else if (p.author_id) filter = { type: "author", value: activeFilterName };
    else if (p.tag_id) filter = { type: "tag", value: activeFilterName };
  }
  const status = p.read === "unread" || p.read === "reading" || p.read === "read" ? p.read : null;
  const format = p.format === "physical" || p.format === "digital" ? p.format : "all";
  return {
    status,
    format,
    filter,
    search: p.search || null,
    sort_by: p.sort_by,
    sort_dir: p.sort_dir === "asc" ? "asc" : p.sort_dir === "desc" ? "desc" : undefined,
    collapse_series: p.collapse === "1",
    layout: "grid",
  };
}

/**
 * Config -> a library URL. Name-keyed filters need a lookup to Calibre's ids,
 * which the caller supplies from the sidebar counts it already loads. An
 * unresolvable name falls back to a plain search so the view still shows
 * something sensible rather than silently ignoring the filter.
 */
export function configToHref(
  config: SavedViewConfig,
  resolve?: (type: "series" | "author" | "tag", name: string) => number | undefined,
): string {
  const q = new URLSearchParams();
  if (config.search) q.set("search", config.search);
  if (config.status) q.set("read", config.status);
  if (config.format && config.format !== "all") q.set("format", config.format);
  if (config.sort_by) q.set("sort_by", config.sort_by);
  if (config.sort_dir) q.set("sort_dir", config.sort_dir);
  if (config.collapse_series) q.set("collapse", "1");

  const f = config.filter;
  if (f?.value) {
    const id = resolve?.(f.type, f.value);
    if (id != null) {
      q.set(f.type === "series" ? "series_id" : f.type === "author" ? "author_id" : "tag_id", String(id));
    } else if (!config.search) {
      q.set("search", f.value);
    }
  }
  const s = q.toString();
  return s ? `/?${s}` : "/";
}

/** Short human summary of what a view filters by, for tooltips. */
export function describeConfig(config: SavedViewConfig): string {
  const bits: string[] = [];
  if (config.filter?.value) bits.push(config.filter.value);
  if (config.status) bits.push(config.status);
  if (config.format && config.format !== "all") bits.push(config.format);
  if (config.search) bits.push(`"${config.search}"`);
  return bits.length ? bits.join(" · ") : "All books";
}
