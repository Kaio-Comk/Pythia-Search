import threading
import time

from fuzzytitles import normalize, search, significant_words, similarity, split_year

CATALOG = {
    "filmes": [
        {"id": 1, "titulo": "O Senhor dos Anéis: A Sociedade do Anel", "ano": "2001"},
        {"id": 2, "titulo": "Duna", "ano": "2021"},
        {"id": 3, "titulo": "Duna", "ano": "1984"},
        {"id": 4, "titulo": "Interestelar", "ano": "2014"},
    ],
    "series": [
        {"id": 10, "titulo": "Breaking Bad", "ano": "2008"},
        {"id": 11, "titulo": "Better Call Saul", "ano": "2015"},
    ],
}


def fetch(table, term, limit):
    term = normalize(term)
    return [r for r in CATALOG[table] if term in normalize(r["titulo"])][:limit]


def test_normalize_e_split_year():
    assert normalize("  Ação!!  Máxima, ") == "acao maxima"
    assert split_year("Duna 2021") == ("Duna", "2021")
    assert split_year("2012") == ("2012", "2012")
    assert significant_words(["o", "de", "duna"]) == ["duna"]


def test_similarity_basica():
    assert similarity("Duna", "duna") == 1.0
    assert similarity("duna", "Duna: Parte Dois") == 0.92
    assert similarity("breaking", "Better Call Saul") < 0.4
    assert similarity("", "x") == 0.0


def test_acha_sem_acento_e_com_palavras_de_menos():
    r = search(fetch, "senhor aneis", ["filmes", "series"])
    assert r and r[0]["id"] == 1 and r[0]["_tabela"] == "filmes"
    r = search(fetch, "interest", ["filmes", "series"])
    assert r and r[0]["titulo"] == "Interestelar"


def test_erro_de_digitacao_depende_do_fetch():
    # ILIKE only returns rows that CONTAIN the typed text, so a typo finds nothing...
    assert search(fetch, "interestellar", ["filmes"]) == []

    # ...unless the fetch is typo-tolerant (e.g. the pg_trgm function in sql/).
    def tolerant(table, term, limit):
        return CATALOG[table]
    r = search(tolerant, "interestellar", ["filmes"])
    assert r and r[0]["titulo"] == "Interestelar"


def test_ano_desempata_e_aparece_primeiro():
    r = search(fetch, "duna 2021", ["filmes"])
    assert [x["id"] for x in r][:2] == [2, 3]          # 2021 first (year bonus)


def test_busca_em_varias_tabelas_e_ordem_estavel():
    r = search(fetch, "breaking bad", ["filmes", "series"])
    assert r[0]["titulo"] == "Breaking Bad" and r[0]["_tabela"] == "series"


def test_consultas_rodam_em_paralelo():
    seen = []

    def slow(table, term, limit):
        seen.append(threading.current_thread().name)
        time.sleep(0.2)
        return []
    t0 = time.monotonic()
    search(slow, "senhor aneis sociedade", ["filmes", "series"])
    assert time.monotonic() - t0 < 0.8                  # 8 queries x 0.2s serial = 1.6s
    assert len(set(seen)) > 1


def test_falha_numa_consulta_nao_derruba_a_busca():
    errors = []

    def flaky(table, term, limit):
        if table == "series":
            raise TimeoutError("db")
        return fetch(table, term, limit)
    r = search(flaky, "duna", ["filmes", "series"], on_error=errors.append)
    assert r and errors and isinstance(errors[0], TimeoutError)


def test_query_vazia():
    assert search(fetch, "", ["filmes"]) == []
