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
        return [_row(dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()


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
