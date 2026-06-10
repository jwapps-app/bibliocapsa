"""
Generated book covers — a Calibre-style fallback for physical/native books that
have no cover image. Produces a self-contained SVG (title + author on a coloured
background) so no image library or fonts are required. Deterministic by title,
with a `variant` to cycle palettes when the user wants a different look.
"""

import hashlib
import html

# Curated palettes: (background, title colour, accent). Dark grounds, light ink.
PALETTES = [
    ("#2c3e50", "#ecf0f1", "#e8b96a"),  # slate blue
    ("#7b241c", "#f9e9e8", "#f1c40f"),  # deep red
    ("#1b4332", "#e8f5e9", "#95d5b2"),  # forest green
    ("#4a235a", "#f3e5f5", "#d7bde2"),  # plum
    ("#1a5276", "#eaf2f8", "#aed6f1"),  # ocean blue
    ("#7e5109", "#fdf2e9", "#f5cba7"),  # amber
    ("#212f3d", "#fbfcfc", "#aeb6bf"),  # charcoal
    ("#641e16", "#fdedec", "#e6b0aa"),  # maroon
    ("#0e6251", "#e8f8f5", "#a3e4d7"),  # teal
    ("#5b2c6f", "#f5eef8", "#bb8fce"),  # purple
]

NUM_PALETTES = len(PALETTES)


def variant_index(title: str, author: str, variant) -> int:
    """The palette index: the explicit variant if given, else derived from the
    title so each book gets a stable, distinct colour."""
    if variant is not None:
        return int(variant) % NUM_PALETTES
    h = int(hashlib.md5((title or "").encode("utf-8")).hexdigest(), 16)
    return h % NUM_PALETTES


def _wrap(text: str, max_chars: int, max_lines: int) -> list:
    words = (text or "").split()
    lines: list = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    # Mark truncation if we ran out of room mid-title.
    used = sum(len(l.split()) for l in lines)
    if used < len(words) and lines:
        lines[-1] = lines[-1].rstrip(".") + "…"
    return lines


def generate_svg(title: str, author: str = "", variant=None) -> str:
    title = (title or "Untitled").strip()
    author = (author or "").strip()
    bg, fg, accent = PALETTES[variant_index(title, author, variant)]

    if len(title) <= 20:
        tsize, maxc = 62, 12
    elif len(title) <= 40:
        tsize, maxc = 50, 16
    else:
        tsize, maxc = 40, 21
    lines = _wrap(title, maxc, 5)

    W, H = 600, 900
    line_h = tsize * 1.16
    block_h = len(lines) * line_h
    # Centre the title block a little above the middle.
    start_y = (H * 0.40) - block_h / 2 + tsize
    title_svg = "".join(
        f'<text x="{W/2:.0f}" y="{start_y + i*line_h:.0f}" text-anchor="middle" '
        f'font-family="Georgia,\'Times New Roman\',serif" font-size="{tsize}" '
        f'font-weight="600" fill="{fg}">{html.escape(l)}</text>'
        for i, l in enumerate(lines)
    )
    rule_y = int(start_y + block_h + 18)
    rule_svg = (f'<line x1="{W/2-90:.0f}" y1="{rule_y}" x2="{W/2+90:.0f}" y2="{rule_y}" '
                f'stroke="{accent}" stroke-width="3"/>')

    author_svg = ""
    if author:
        a_lines = _wrap(author.upper(), 26, 2)
        ay = int(H * 0.84)
        author_svg = "".join(
            f'<text x="{W/2:.0f}" y="{ay + i*32}" text-anchor="middle" '
            f'font-family="Georgia,serif" font-size="24" letter-spacing="2" '
            f'fill="{accent}">{html.escape(l)}</text>'
            for i, l in enumerate(a_lines)
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
        f'<rect width="{W}" height="{H}" fill="{bg}"/>'
        f'<rect x="22" y="22" width="{W-44}" height="{H-44}" fill="none" '
        f'stroke="{accent}" stroke-width="2" opacity="0.45"/>'
        f'{title_svg}{rule_svg}{author_svg}'
        f'</svg>'
    )
