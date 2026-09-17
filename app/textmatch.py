"""
Title/author comparison shared by the Goodreads importer and Calibre enrichment.

Both decide "is this the same book?" and then WRITE to that book -- ownership,
ratings, shelves, descriptive metadata. A wrong answer silently corrupts a
different book, so the rules here lean towards "not sure": an unresolved match
costs a manual fix, a wrong one costs data.
"""

import re
import unicodedata
from typing import Iterable, Optional

_ARTICLES = re.compile(r"^(the|a|an)\s+")


def norm(s: Optional[str]) -> str:
    """Case-, accent- and punctuation-insensitive form that KEEPS non-Latin
    text. (The old ASCII-only version turned every Chinese, Cyrillic or Greek
    title into the empty string -- and two empty strings compare as identical.)"""
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = re.sub(r"[\W_]+", " ", t)          # Unicode-aware: letters/digits of any script stay
    t = _ARTICLES.sub("", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def _tokens(name: str) -> set:
    # Initials and particles carry no signal ("J", "de") -- but a short token in
    # a non-Latin script is a whole name, so keep those.
    return {w for w in norm(name).split() if len(w) > 2 or not w.isascii()}


def authors_agree(a: Iterable[str], b: Iterable[str]) -> Optional[bool]:
    """True/False when both sides name authors; None when either side doesn't
    (nothing to compare -- the caller decides how much that is worth)."""
    ta = set().union(*[_tokens(x) for x in a if x] or [set()])
    tb = set().union(*[_tokens(x) for x in b if x] or [set()])
    if not ta or not tb:
        return None
    if ta & tb:
        return True
    # Scripts without word breaks: "曹雪芹" vs "曹雪芹 著".
    ja, jb = "".join(sorted(ta)), "".join(sorted(tb))
    return any(x in jb for x in ta if not x.isascii()) or any(x in ja for x in tb if not x.isascii())
