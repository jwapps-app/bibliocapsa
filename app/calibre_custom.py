"""
Calibre custom columns — dynamic detection + per-book value reading.

Calibre stores user-defined columns in `custom_columns`; values live in
`custom_column_<id>` (simple columns: book,value) or, for normalized/multiple
columns, via `books_custom_column_<id>_link` → `custom_column_<id>`. Everyone's
columns differ, so everything here is discovered at runtime (read-only).
"""

import logging

logger = logging.getLogger(__name__)


def list_columns(conn) -> list[dict]:
    """All custom-column definitions: label (#lookup), name, datatype, is_multiple."""
    try:
        rows = conn.execute(
            "SELECT id, label, name, datatype, is_multiple, normalized "
            "FROM custom_columns ORDER BY name"
        ).fetchall()
    except Exception as e:
        logger.warning("custom_columns unavailable: %s", e)
        return []
    return [
        {
            "id": r["id"], "label": r["label"], "name": r["name"],
            "datatype": r["datatype"], "is_multiple": bool(r["is_multiple"]),
        }
        for r in rows
    ]


def _read_value(conn, col: dict, book_id: int):
    cid, mult, norm = col["id"], col["is_multiple"], col["normalized"]
    try:
        if norm:
            rows = conn.execute(
                f"SELECT v.value AS value FROM books_custom_column_{cid}_link l "
                f"JOIN custom_column_{cid} v ON v.id = l.value WHERE l.book = ?",
                (book_id,),
            ).fetchall()
            vals = [r["value"] for r in rows]
            return vals if mult else (vals[0] if vals else None)
        rows = conn.execute(
            f"SELECT value FROM custom_column_{cid} WHERE book = ?", (book_id,)
        ).fetchall()
        if mult:
            return [r["value"] for r in rows]
        return rows[0]["value"] if rows else None
    except Exception:
        return None


def filter_predicate(conn, label: str, value: str):
    """SQL predicate (referencing `b.id`) for filtering Calibre books by a custom
    column value. Returns (sql, params) or None if the column is unknown."""
    col = conn.execute(
        "SELECT id, datatype, normalized FROM custom_columns WHERE label = ?", (label,)
    ).fetchone()
    if not col:
        return None
    cid = int(col["id"])  # int from our own DB → safe to interpolate as table name
    if col["datatype"] == "bool":
        truthy = str(value).lower() in ("1", "true", "yes", "read")
        clause = f"EXISTS (SELECT 1 FROM custom_column_{cid} cc WHERE cc.book = b.id AND cc.value = 1)"
        return (clause if truthy else f"NOT {clause}", [])
    if col["normalized"]:
        return (
            f"EXISTS (SELECT 1 FROM books_custom_column_{cid}_link l "
            f"JOIN custom_column_{cid} v ON v.id = l.value WHERE l.book = b.id AND v.value = ?)",
            [value],
        )
    return (f"EXISTS (SELECT 1 FROM custom_column_{cid} cc WHERE cc.book = b.id AND cc.value = ?)", [value])


def merge_overlay(conn, current: list[dict], custom_edits: dict) -> list[dict]:
    """Overlay pending custom-column edits (`{label: value}`) onto the values
    read from Calibre, so edits show instantly on the detail page."""
    if not custom_edits:
        return current
    cols = {c["label"]: c for c in list_columns(conn)}
    by_label = {c["label"]: c for c in current}
    for label, val in custom_edits.items():
        if val is None or val == "" or val == []:
            by_label.pop(label, None)
            continue
        col = cols.get(label, {})
        dt = col.get("datatype", "text")
        by_label[label] = {
            "label": label, "name": col.get("name", label), "datatype": dt,
            "is_multiple": col.get("is_multiple", False),
            "value": bool(val) if dt == "bool" else val,
        }
    return list(by_label.values())


def fetch_for_book(conn, book_id: int) -> list[dict]:
    """Custom-column values for one book, in definition order, omitting empties.
    Each: {label, name, datatype, is_multiple, value}."""
    try:
        cols = conn.execute(
            "SELECT id, label, name, datatype, is_multiple, normalized "
            "FROM custom_columns ORDER BY name"
        ).fetchall()
    except Exception:
        return []
    out = []
    for col in cols:
        c = dict(col)
        val = _read_value(conn, c, book_id)
        if val is None or val == [] or val == "":
            continue
        if c["datatype"] == "bool":
            val = bool(val)
        out.append({
            "label": c["label"], "name": c["name"], "datatype": c["datatype"],
            "is_multiple": bool(c["is_multiple"]), "value": val,
        })
    return out
