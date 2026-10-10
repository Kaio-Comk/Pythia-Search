-- Typo-tolerant candidate fetch for fuzzytitles (PostgreSQL + pg_trgm).
--
-- 1) Index every title column you search (GIN trigram makes ILIKE '%x%' fast too):
--      CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
--      CREATE INDEX IF NOT EXISTS idx_movies_title_trgm
--          ON public.movies USING gin (title extensions.gin_trgm_ops);
--
-- 2) This function returns rows whose title is SIMILAR to the term (typos) or
--    CONTAINS it. Only tables listed in the CASE below can be queried: never build
--    table names from user input.
--
-- Edit the table / column names to your schema, then use it as your `fetch`:
--      lambda table, term, n: sb.rpc("search_titles",
--          {"p_table": table, "p_term": term, "p_limit": n}).execute().data or []

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

CREATE OR REPLACE FUNCTION public.search_titles(
    p_table text,
    p_term text,
    p_limit integer DEFAULT 40
)
RETURNS TABLE (id bigint, title text, year text, score double precision)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, extensions, pg_temp
AS $$
BEGIN
    IF p_table NOT IN ('movies', 'series') THEN          -- <- your allow-list
        RAISE EXCEPTION 'table not allowed: %', p_table USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 200 THEN
        p_limit := 40;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT t.id, t.title, t.year::text,
                GREATEST(similarity(t.title, $1)::float8,
                         CASE WHEN t.title ILIKE ''%%'' || $1 || ''%%'' THEN 0.75 ELSE 0 END)
           FROM public.%I t
          WHERE t.title %% $1 OR t.title ILIKE ''%%'' || $1 || ''%%''
          ORDER BY 4 DESC
          LIMIT $2', p_table)
    USING p_term, p_limit;
END;
$$;

REVOKE ALL ON FUNCTION public.search_titles(text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.search_titles(text, text, integer) TO service_role;
