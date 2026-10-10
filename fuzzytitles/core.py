"""Candidate gathering is delegated to YOUR database (a plain `ILIKE '%word%'` per
significant word is enough, ideally backed by a pg_trgm GIN index, see sql/);
ranking happens here, in memory, so typos and partial titles still rank well.

The candidate queries are independent, so `search` runs them in parallel threads:
a 2-table, 4-word query goes from ~10 sequential round-trips to one batch.
"""
from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Optional

# Small multilingual list (pt / en / es / fr); pass your own to `search`.
STOPWORDS = frozenset({
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "um", "uma", "os", "as", "ou", "ao", "aos", "se", "me", "te",
    "the", "of", "in", "a", "an", "to", "and", "or", "is",
    "el", "la", "los", "las", "un", "una", "en", "es", "le", "les", "et",
})

_YEAR_AT_END = re.compile(r"\b(\d{4})\s*$")
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """lowercase, no accents, no punctuation, single spaces."""
    text = unicodedata.normalize("NFD", text.lower().strip())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def significant_words(words: list[str], stopwords: Iterable[str] = STOPWORDS) -> list[str]:
    stop = set(stopwords)
    sig = [w for w in words if len(w) >= 3 and w not in stop]
    return sig or [w for w in words if len(w) >= 2] or words


def split_year(query: str) -> tuple[str, str]:
    """'Duna 2021' -> ('Duna', '2021'). A query that is only a year keeps the year as text."""
    q = query.strip()
    m = _YEAR_AT_END.search(q)
    if m:
        return (q[:m.start()].strip() or q), m.group(1)
    return q, ""


def _word_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    prefix = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        prefix += 1
    longest = max(len(a), len(b))
    return max(0.0, prefix / longest - abs(len(a) - len(b)) / longest * 0.3) if longest else 0.0


def similarity(a: str, b: str, stopwords: Iterable[str] = STOPWORDS) -> float:
    """0..1. Exact = 1, one contains the other = 0.92, otherwise the best per-word
    prefix match (70%) blended with how many of b's words were covered (30%)."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    sig_a = significant_words(a.split(), stopwords)
    sig_b = significant_words(b.split(), stopwords)
    scores = [max((_word_sim(pa, pb) for pb in sig_b), default=0.0) for pa in sig_a]
    if not scores:
        return 0.0
    coverage = min(len(sig_a), len(sig_b)) / len(sig_b) if sig_b else 0.0
    return min(1.0, sum(scores) / len(scores) * 0.7 + coverage * 0.3)


Fetch = Callable[[str, str, int], list]     # (table, term, limit) -> rows with "id", "title"


def search(fetch: Fetch, query: str, tables: list[str], *, limit: int = 40,
           max_words: int = 4, stopwords: Iterable[str] = STOPWORDS,
           title_key: str = "titulo", year_key: str = "ano",
           on_error: Optional[Callable[[Exception], None]] = None) -> list[dict]:
    """Rank candidates for `query`.

    `fetch(table, term, limit)` must return a list of dict rows containing at
    least `id`, `title_key` and (optionally) `year_key`, e.g. with supabase-py:

        lambda table, term, n: (sb.table(table).select("id,titulo,ano")
                                .ilike("titulo", f"%{term}%").limit(n).execute().data or [])

    Rows come back sorted by score then year (newest first), each with a
    `_tabela` key. A failing fetch is skipped (reported to `on_error`).
    """
    name, year = split_year(query)
    words = significant_words(normalize(name).split(), stopwords)

    jobs: list[tuple[str, str, int]] = []
    for table in tables:
        for word in words[:max_words]:
            jobs.append((table, word, 60))
        if len(words) > 1:
            jobs.append((table, name, 20))          # the whole phrase too
    if not jobs:
        return []

    def run(job):
        return fetch(*job)

    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = [pool.submit(run, j) for j in jobs]
        results = []
        for fut in futures:
            try:
                results.append(fut.result() or [])
            except Exception as exc:  # noqa: BLE001 - one bad query must not sink the search
                if on_error:
                    on_error(exc)
                results.append([])

    candidates: dict[str, dict] = {}
    for (table, _term, _n), rows in zip(jobs, results):
        for row in rows:
            key = f"{table}_{row['id']}"
            if key not in candidates:
                candidates[key] = dict(row, _tabela=table)

    threshold = 0.35 if len(words) <= 1 else 0.40
    ranked = []
    for item in candidates.values():
        score = similarity(name, str(item.get(title_key) or ""), stopwords)
        if year and year in str(item.get(year_key) or ""):
            score = min(1.0, score + 0.05)
        if score >= threshold:
            ranked.append((score, _year_of(item.get(year_key)), item))
    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [item for _s, _y, item in ranked[:limit]]


def _year_of(value) -> int:
    m = re.search(r"\d{4}", str(value or ""))
    return int(m.group()) if m else 0
