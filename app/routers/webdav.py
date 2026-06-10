"""
Minimal WebDAV endpoint so KOReader's Statistics "Cloud sync" can push its
`statistics.sqlite3` to Bibliocapsa (and merge across devices). Per-user storage,
HTTP Basic auth (KOReader sends Bibliocapsa username/password). Supports the
subset KOReader uses: OPTIONS, PROPFIND, GET/HEAD, PUT, MKCOL, DELETE.
"""

import os
import shutil
from email.utils import formatdate
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response, HTTPException

router = APIRouter()
ROOT = os.getenv("WEBDAV_DIR", "/app/webdav")
MAX_PUT_BYTES = int(os.getenv("WEBDAV_MAX_FILE_MB", "50")) * 1024 * 1024
MAX_USER_BYTES = int(os.getenv("WEBDAV_MAX_USER_MB", "500")) * 1024 * 1024


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _require_user(request: Request) -> dict:
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or not u.get("username"):
        raise HTTPException(status_code=401, detail="Authentication required",
                            headers={"WWW-Authenticate": 'Basic realm="Bibliocapsa WebDAV"'})
    return u


def _resolve(username: str, rel: str):
    """Map a request path (under /dav) to a path inside the user's folder."""
    base = os.path.join(ROOT, username)
    full = os.path.normpath(os.path.join(base, (rel or "").lstrip("/")))
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(status_code=403, detail="Forbidden")
    return base, full


def _href(rel: str, is_dir: bool) -> str:
    p = "/dav/" + (rel or "").lstrip("/")
    if is_dir and not p.endswith("/"):
        p += "/"
    return escape(p)


def _prop(href: str, name: str, is_dir: bool, size: int, mtime: float) -> str:
    rtype = "<d:collection/>" if is_dir else ""
    length = "" if is_dir else f"<d:getcontentlength>{size}</d:getcontentlength>"
    return (f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
            f"<d:displayname>{escape(name)}</d:displayname>"
            f"<d:resourcetype>{rtype}</d:resourcetype>{length}"
            f"<d:getlastmodified>{formatdate(mtime, usegmt=True)}</d:getlastmodified>"
            f"</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")


@router.api_route("", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "MKCOL", "DELETE"])
@router.api_route("/{path:path}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "MKCOL", "DELETE"])
async def webdav(request: Request, path: str = ""):
    user = _require_user(request)
    username = user["username"]
    base, full = _resolve(username, path)
    os.makedirs(base, exist_ok=True)
    m = request.method

    if m == "OPTIONS":
        return Response(status_code=200, headers={
            "DAV": "1,2", "MS-Author-Via": "DAV",
            "Allow": "OPTIONS, PROPFIND, GET, HEAD, PUT, MKCOL, DELETE",
        })

    if m == "PROPFIND":
        if not os.path.exists(full):
            raise HTTPException(status_code=404)
        is_dir = os.path.isdir(full)
        depth = request.headers.get("Depth", "1")
        st = os.stat(full)
        out = []
        # Self entry only for Depth:0 (or a file). For a directory LISTING (Depth:1)
        # we return children only — KOReader doesn't self-filter and would otherwise
        # render the folder's own entry as a phantom child and navigate into it (→404).
        if depth == "0" or not is_dir:
            out.append(_prop(escape(request.url.path), os.path.basename(full) or username, is_dir, st.st_size, st.st_mtime))
        if is_dir and depth != "0":
            for entry in sorted(os.listdir(full)):
                ep = os.path.join(full, entry)
                est = os.stat(ep)
                ed = os.path.isdir(ep)
                crel = f"{path.rstrip('/')}/{entry}" if path else entry
                out.append(_prop(_href(crel, ed), entry, ed, est.st_size, est.st_mtime))
        body = '<?xml version="1.0" encoding="utf-8"?>\n<d:multistatus xmlns:d="DAV:">' + "".join(out) + "</d:multistatus>"
        return Response(content=body, status_code=207, media_type="application/xml; charset=utf-8")

    if m in ("GET", "HEAD"):
        if not os.path.isfile(full):
            raise HTTPException(status_code=404)
        st = os.stat(full)
        headers = {"Content-Length": str(st.st_size), "Last-Modified": formatdate(st.st_mtime, usegmt=True)}
        if m == "HEAD":
            return Response(status_code=200, headers=headers)
        with open(full, "rb") as f:
            data = f.read()
        return Response(content=data, media_type="application/octet-stream", headers=headers)

    if m == "PUT":
        body = await request.body()
        # Per-file and per-user quota so a client can't fill the host disk.
        if len(body) > MAX_PUT_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        replacing = os.path.getsize(full) if os.path.exists(full) else 0
        if _dir_size(base) - replacing + len(body) > MAX_USER_BYTES:
            raise HTTPException(status_code=507, detail="Storage quota exceeded")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        existed = os.path.exists(full)
        with open(full, "wb") as f:
            f.write(body)
        return Response(status_code=204 if existed else 201)

    if m == "MKCOL":
        if os.path.exists(full):
            raise HTTPException(status_code=405)
        os.makedirs(full, exist_ok=True)
        return Response(status_code=201)

    if m == "DELETE":
        if not os.path.exists(full):
            raise HTTPException(status_code=404)
        shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
        return Response(status_code=204)

    raise HTTPException(status_code=405)
