"""
Lending management — track physical books loaned to anyone.
Who has it, when it's due, overdue alerts.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


def _require_admin(request: Request) -> dict:
    """Lending is owner-managed (tracks who borrowed physical books) and exposes
    borrower PII, so every endpoint is admin-only."""
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return u


class LoanCreate(BaseModel):
    book_id: int
    book_source: str = "native"  # native or calibre
    borrower_name: str
    borrower_email: Optional[str] = None
    borrower_phone: Optional[str] = None
    lent_by: Optional[int] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


class LoanUpdate(BaseModel):
    due_date: Optional[datetime] = None
    returned_date: Optional[datetime] = None
    notes: Optional[str] = None


class Loan(BaseModel):
    id: int
    book_id: int
    book_source: str
    borrower_name: str
    borrower_email: Optional[str] = None
    borrower_phone: Optional[str] = None
    lent_by: Optional[int] = None
    loan_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    returned_date: Optional[datetime] = None
    notes: Optional[str] = None
    is_overdue: bool = False
    book_title: Optional[str] = None
    cover_url: Optional[str] = None
    has_cover: bool = False


def _pg():
    from ..pg_database import get_pg
    return get_pg()


def _to_loan(row: dict) -> Loan:
    loan = Loan(**{k: v for k, v in row.items() if k in Loan.model_fields})
    if loan.due_date and not loan.returned_date:
        loan.is_overdue = datetime.now(loan.due_date.tzinfo) > loan.due_date
    return loan


def _enrich(loans: list[Loan]) -> list[Loan]:
    """Attach book title + cover to each loan (Calibre and native sources)."""
    cal_ids = [l.book_id for l in loans if l.book_source == "calibre"]
    nat_ids = [l.book_id for l in loans if l.book_source == "native"]

    cal_map: dict = {}
    if cal_ids:
        try:
            from ..database import get_conn
            with get_conn() as conn:
                ph = ",".join("?" * len(cal_ids))
                for r in conn.execute(f"SELECT id, title, has_cover FROM books WHERE id IN ({ph})", cal_ids):
                    cal_map[r["id"]] = (r["title"], bool(r["has_cover"]))
        except Exception:
            pass

    nat_map: dict = {}
    if nat_ids:
        try:
            conn = _pg()
            cur = conn.cursor()
            cur.execute("SELECT id, title, cover_url FROM native_books WHERE id = ANY(%s)", (nat_ids,))
            for r in cur.fetchall():
                nat_map[r["id"]] = (r["title"], r["cover_url"])
            conn.close()
        except Exception:
            pass

    for l in loans:
        if l.book_source == "calibre" and l.book_id in cal_map:
            title, has_cover = cal_map[l.book_id]
            l.book_title = title
            l.has_cover = has_cover
            l.cover_url = f"/api/covers/{l.book_id}" if has_cover else None
        elif l.book_source == "native" and l.book_id in nat_map:
            title, cover = nat_map[l.book_id]
            l.book_title = title
            l.has_cover = bool(cover)
            l.cover_url = f"/api/native/books/{l.book_id}/cover" if cover else None
    return loans


@router.get("", response_model=list[Loan], summary="List all loans (admin)")
def list_loans(
    request: Request,
    active_only: bool = Query(True, description="Only show unreturned loans"),
    borrower: Optional[str] = Query(None),
):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        conditions = ["1=1"]
        params = []

        if active_only:
            conditions.append("returned_date IS NULL")
        if borrower:
            conditions.append("borrower_name ILIKE %s")
            params.append(f"%{borrower}%")

        where = " AND ".join(conditions)
        cur.execute(f"SELECT * FROM lending WHERE {where} ORDER BY loan_date DESC", params)
        rows = cur.fetchall()
        conn.close()
        return _enrich([_to_loan(dict(r)) for r in rows])
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database unavailable")


@router.post("", response_model=Loan, status_code=201, summary="Create a loan (admin)")
def create_loan(loan: LoanCreate, request: Request):
    admin = _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO lending
                (book_id, book_source, borrower_name, borrower_email, borrower_phone,
                 lent_by, due_date, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            # lent_by comes from the session, never the client body.
            (loan.book_id, loan.book_source, loan.borrower_name, loan.borrower_email,
             loan.borrower_phone, admin["id"], loan.due_date, loan.notes)
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return _to_loan(dict(row))
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.put("/{loan_id}", response_model=Loan, summary="Update a loan (return, extend) (admin)")
def update_loan(loan_id: int, updates: LoanUpdate, request: Request):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        fields = {k: v for k, v in updates.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [loan_id]

        cur.execute(
            f"UPDATE lending SET {set_clause} WHERE id = %s RETURNING *",
            values
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Loan {loan_id} not found")
        return _to_loan(dict(row))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.get("/overdue", response_model=list[Loan], summary="Get overdue loans (admin)")
def get_overdue(request: Request):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM lending WHERE returned_date IS NULL AND due_date < NOW() ORDER BY due_date ASC"
        )
        rows = cur.fetchall()
        conn.close()
        return _enrich([_to_loan(dict(r)) for r in rows])
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database unavailable")
