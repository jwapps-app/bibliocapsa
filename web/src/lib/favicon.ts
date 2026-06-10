// Theme-aware favicon + Apple touch icon, applied client-side from the active
// CSS theme variables. Kept in one place so both the ThemePicker (on theme
// change) and the FaviconManager (on every page) use identical logic.

export function applyFavicon(): void {
  const cs = getComputedStyle(document.documentElement);
  const ink = (cs.getPropertyValue("--ink") || "#0f0d0b").trim();
  const gd = (cs.getPropertyValue("--gold-dim") || "#6b4e1e").trim();
  const gl = (cs.getPropertyValue("--gold-light") || "#e8b96a").trim();
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='${ink}'/><path d='M8 18 L32 21 L56 18 L54 44 L32 48 L10 44 Z' fill='${gd}'/><path d='M11 20 L31 22.5 L31 45.5 L13 42 Z' fill='${gl}'/><path d='M53 20 L33 22.5 L33 45.5 L51 42 Z' fill='${gl}'/></svg>`;
  let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
  if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
  link.type = "image/svg+xml";
  link.href = "data:image/svg+xml," + encodeURIComponent(svg);
}

export function applyAppleIcon(themeId: string): void {
  let link = document.querySelector("link[rel='apple-touch-icon']") as HTMLLinkElement | null;
  if (!link) { link = document.createElement("link"); link.rel = "apple-touch-icon"; document.head.appendChild(link); }
  link.href = `/icons/${themeId}.png`;
}
