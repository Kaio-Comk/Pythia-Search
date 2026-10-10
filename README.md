# fuzzytitles

Forgiving title search for catalogs (movies, series, products, songs): accents,
punctuation, missing words, a trailing year, partial titles. Works on top of any
database: you supply a small `fetch` function, the ranking runs in memory.

Extracted from the search of a production streaming bot.

## Install

```bash
pip install git+https://github.com/Kaio-Comk/fuzzytitles.git
```

## Use

```python
from fuzzytitles import search

def fetch(table, term, limit):          # e.g. supabase-py; any DB works
    return (sb.table(table).select("id,title,year")
            .ilike("title", f"%{term}%").limit(limit).execute().data or [])

results = search(fetch, "senhor dos aneis 2001", ["movies", "series"],
                 limit=20, title_key="title", year_key="year")
```

Each result is your row plus `_tabela` (the table it came from), sorted by score
and then year.

How it works:

1. The query is split into a title and an optional trailing year.
2. One `fetch` per table and significant word (plus the whole phrase) runs **in
   parallel threads**: ~10 sequential round-trips become one batch.
3. Candidates are merged, scored with `similarity()` and filtered by a threshold.
   A matching year adds a small bonus.

## Typos

A plain `ILIKE '%text%'` only returns rows that **contain** what was typed, so
`interestellar` finds nothing for `Interestelar`. For typo tolerance use
`sql/001_trigram_search.sql` (PostgreSQL `pg_trgm`) as your `fetch`:

```python
fetch = lambda table, term, n: sb.rpc(
    "search_titles", {"p_table": table, "p_term": term, "p_limit": n}).execute().data or []
```

The SQL file is syntax-checked with a PostgreSQL parser but has not been run
against a database in this repository: test it in staging.

## API

- `normalize(text)`, `split_year(query)`, `significant_words(words)`
- `similarity(a, b)` -> 0..1 (exact 1.0, containment 0.92, otherwise word-prefix blend)
- `search(fetch, query, tables, *, limit=40, max_words=4, stopwords=..., title_key, year_key, on_error)`

A failing `fetch` is skipped (reported to `on_error`), so one slow table does not
sink the search. Stop words are multilingual (pt/en/es/fr); pass your own list.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

## License

MIT
