"""Per-user saved library views — a named bundle of filters, sort and layout.

Shared by the web app and the iOS app, so `config` is deliberately
client-agnostic and keyed by NAME rather than Calibre ids: the iOS catalog is a
local mirror that has series/author/tag names but not Calibre's integer ids, and
name-keyed config lets it resolve a saved view entirely offline. The web app
resolves a name to its id when building the query.

Unknown/extra keys in `config` are preserved as-is, so a newer client can store
fields an older one ignores.
"""

import json
from typing import Optional, Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

MAX_VIEWS_PER_USER = 50
MAX_NAME_LEN = 60


def _user(request: Request) -> dict:
    from .. import auth
    u = auth.authenticate_request(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


from ..pg_database import get_pg as _pg


class SavedViewBody(BaseModel):
    name: str
    config: dict[str, Any]
    position: Optional[int] = None


def _row(r: dict) -> dict:
    """Normalize a DB row; `config` may come back as str or dict by driver."""
    config = r.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            config = {}
    return {
        "id": r["id"],
        "name": r["name"],
        "config": config or {},
        "position": r.get("position") or 0,
    }


_FILTER_TABLE = {"series": "series", "author": "authors", "tag": "tags"}


def _attach_filter_ids(rows: list) -> list:
    """Resolve name-keyed filters (series/author/tag) to their Calibre ids.

    Views deliberately store the NAME, not the id, because the iOS app mirrors
    the catalog locally and can resolve names offline. The web client has no
    such mirror — without an id it falls back to a plain text search for the
    name, which matches no titles and renders the view empty. So we resolve here,
    where the Calibre database is already at hand. Best-effort: anything that
    doesn't resolve is left as None and the client keeps its old fallback."""
    wanted: dict = {}
    for r in rows:
        f = (r.get("config") or {}).get("filter") or {}
        t, v = f.get("type"), f.get("value")
        if t in _FILTER_TABLE and v:
            wanted.setdefault(t, set()).add(v)
    if not wanted:
        return rows

    found: dict = {}
    try:
        from ..database import get_conn
        with get_conn() as cal:
            for t, names in wanted.items():
                ns = list(names)
                ph = ",".join("?" * len(ns))
                for row in cal.execute(
                    f"SELECT id, name FROM {_FILTER_TABLE[t]} "
                    f"WHERE name COLLATE NOCASE IN ({ph})", ns
                ).fetchall():
                    found[(t, (row["name"] or "").lower())] = row["id"]
    except Exception:
        return rows  # Calibre unreadable — leave ids unset, client falls back

    for r in rows:
        f = (r.get("config") or {}).get("filter") or {}
        t, v = f.get("type"), f.get("value")
        if t in _FILTER_TABLE and v:
            r["filter_id"] = found.get((t, v.lower()))
    return rows


@router.get("", summary="The current user's saved views")
def list_views(request: Request):
    u = _user(request)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, config, position FROM saved_views "
            "WHERE user_id=%s ORDER BY position, id",
            (u["id"],),
        )
        rows = [_row(dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()
    return _attach_filter_ids(rows)


@router.post("", summary="Save the current view")
def create_view(body: SavedViewBody, request: Request):
    u = _user(request)
    name = (body.name or "").strip()[:MAX_NAME_LEN]
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM saved_views WHERE user_id=%s", (u["id"],))
        if (cur.fetchone()["n"] or 0) >= MAX_VIEWS_PER_USER:
            raise HTTPException(status_code=400,
                                detail=f"Saved-view limit reached ({MAX_VIEWS_PER_USER}).")
        # Re-saving under an existing name overwrites it, so "save" is idempotent
        # from the user's point of view instead of piling up duplicates.
        cur.execute("SELECT id FROM saved_views WHERE user_id=%s AND name=%s", (u["id"], name))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE saved_views SET config=%s WHERE id=%s AND user_id=%s",
                (json.dumps(body.config or {}), existing["id"], u["id"]),
            )
            conn.commit()
            return {"id": existing["id"], "updated": True}

        position = body.position
        if position is None:
            cur.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM saved_views WHERE user_id=%s",
                        (u["id"],))
            position = cur.fetchone()["p"]
        cur.execute(
            "INSERT INTO saved_views (user_id, name, config, position) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (u["id"], name, json.dumps(body.config or {}), position),
        )
        rid = cur.fetchone()["id"]
        conn.commit()
        return {"id": rid, "updated": False}
    finally:
        conn.close()


@router.put("/{view_id}", summary="Rename or update a saved view")
def update_view(view_id: int, body: SavedViewBody, request: Request):
    u = _user(request)
    name = (body.name or "").strip()[:MAX_NAME_LEN]
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE saved_views SET name=%s, config=%s, position=COALESCE(%s, position) "
            "WHERE id=%s AND user_id=%s",
            (name, json.dumps(body.config or {}), body.position, view_id, u["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Saved view not found")
        conn.commit()
        return {"updated": cur.rowcount}
    finally:
        conn.close()


@router.delete("/{view_id}", summary="Delete a saved view")
def delete_view(view_id: int, request: Request):
    u = _user(request)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM saved_views WHERE id=%s AND user_id=%s", (view_id, u["id"]))
        conn.commit()
        return {"deleted": cur.rowcount}
    finally:
        conn.close()
