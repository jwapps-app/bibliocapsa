"""
Pydantic response models for Bibliocapsa API.
All models are read-only — no write endpoints exist.
"""

from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Author(BaseModel):
    id: int
    name: str
    sort: Optional[str] = None
    book_count: Optional[int] = None


class SeriesRef(BaseModel):
    id: int
    name: str
    series_index: Optional[float] = None


class TagRef(BaseModel):
    id: int
    name: str


class FormatRef(BaseModel):
    format: str
    size: Optional[int] = None


class BookSummary(BaseModel):
    id: int
    title: str
    sort: Optional[str] = None
    authors: list[Author] = []
    series: Optional[SeriesRef] = None
    tags: list[TagRef] = []
    pubdate: Optional[datetime] = None
    cover_url: Optional[str] = None
    has_cover: bool = False
    rating: Optional[float] = None
    community_rating: Optional[float] = None  # external (Hardcover) avg, when known
    reading_status: Optional[str] = None      # 'read' | 'reading' | None (unread)
    date_read: Optional[str] = None           # 'YYYY-MM-DD' when finished
    last_modified: Optional[datetime] = None
    book_source: str = "calibre"
    has_physical: bool = False
    has_digital: bool = True
    physical_location: Optional[str] = None


class BookDetail(BookSummary):
    comment: Optional[str] = None
    publisher: Optional[str] = None
    isbn: Optional[str] = None
    uuid: Optional[str] = None
    formats: list[FormatRef] = []
    path: Optional[str] = None
    series_index: Optional[float] = None
    custom: list = []  # Calibre custom-column values (dynamic per library)


class SeriesDetail(BaseModel):
    id: int
    name: str
    book_count: int
    books: list[BookSummary] = []


class AuthorDetail(BaseModel):
    id: int
    name: str
    sort: Optional[str] = None
    book_count: int
    books: list[BookSummary] = []


class TagDetail(BaseModel):
    id: int
    name: str
    book_count: int


class PaginatedBooks(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    items: list[BookSummary]


class SyncResponse(BaseModel):
    since: Optional[datetime] = None
    until: datetime
    total: int
    items: list[BookDetail]


class HealthResponse(BaseModel):
    status: str
    calibre_db: str
    book_count: int        # total across all libraries
    calibre_count: int = 0 # digital books in Calibre
    native_count: int = 0  # physical-only books not in Calibre
    version: str = "1.0.0"
