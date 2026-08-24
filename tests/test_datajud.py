"""Testes de unidade da fonte 1 (DataJud).

FIXTURES SINTETICAS: as respostas de API abaixo sao inventadas para exercitar
paginacao, deduplicacao e agregacao. Nenhuma delas vira dado publicado — o
pipeline so grava Parquet a partir de consulta real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datajud import (  # noqa: E402
    UNIVERSO_B2C,
    UNIVERSO_REGULATORIO,
    ClienteDataJud,
    achatar,
    deduplicar,
    montar_query,
    por_assunto,
    serie_mensal,
    universo_do_alias,
)


def _hit(id_, numero, assuntos, data="2024-03-15T00:00:00.000Z", orgao=1):
    return {
        "_id": id_,
        "sort": [id_],
        "_source": {
            "numeroProcesso": numero,
            "tribunal": "TJSP",
            "grau": "G1",
            "classe": {"codigo": 319, "nome": "Procedimento do Juizado Especial Civel"},
            "orgaoJulgador": {"codigo": orgao, "nome": f"Vara {orgao}", "codigoMunicipioIBGE": 3550308},
            "dataAjuizamento": data,
            "assuntos": assuntos,
        },
    }


def test_universos_nunca_se_misturam():
    assert universo_do_alias("tjsp") == UNIVERSO_B2C
    assert universo_do_alias("TJCE") == UNIVERSO_B2C
    assert universo_do_alias("trf3") == UNIVERSO_REGULATORIO
    try:
        universo_do_alias("stj")
    except ValueError:
        pass
    else:
        raise AssertionError("alias desconhecido deveria falhar, nao cair num balde qualquer")


def test_montar_query():
    q = montar_query(assuntos=[1156, 7771], inicio="2020-01-01", fim="2020-12-31")
    must = q["bool"]["must"]
    assert {"terms": {"assuntos.codigo": [1156, 7771]}} in must
    assert {"range": {"dataAjuizamento": {"gte": "2020-01-01", "lte": "2020-12-31"}}} in must
    assert montar_query() == {"match_all": {}}


def test_achatar_tolera_formatos():
    hits = [
        _hit("a", "0001", [{"codigo": 1156, "nome": "Consumidor"}, {"codigo": 7771, "nome": "Transporte"}]),
        _hit("b", "0002", {"codigo": 1156, "nome": "Consumidor"}),  # dict solto
        _hit("c", "0003", []),                                      # sem assunto
    ]
    df = achatar(hits, "tjsp")
    assert df["n_assuntos"].tolist() == [2, 1, 0]
    assert df["uf"].unique().tolist() == ["SP"]
    assert df["universo"].unique().tolist() == [UNIVERSO_B2C]
    assert df["ano"].tolist() == [2024, 2024, 2024]


def test_deduplicar_por_numero_processo():
    hits = [_hit("a", "0001", []), _hit("b", "0001", []), _hit("c", "0002", [])]
    df = deduplicar(achatar(hits, "tjsp"))
    assert len(df) == 2


def test_serie_mensal_conta_processo_nao_ocorrencia_de_assunto():
    """O ponto metodologico central: 1 processo com 3 assuntos conta 1, nao 3."""
    hits = [
        _hit("a", "0001", [{"codigo": 1}, {"codigo": 2}, {"codigo": 3}]),
        _hit("b", "0002", [{"codigo": 1}]),
    ]
    df = deduplicar(achatar(hits, "tjsp"))
    serie = serie_mensal(df)
    assert serie["processos"].sum() == 2  # e nao 4


def test_por_assunto_nao_soma_ao_total():
    hits = [_hit("a", "0001", [{"codigo": 1}, {"codigo": 2}, {"codigo": 3}])]
    df = deduplicar(achatar(hits, "tjsp"))
    pa = por_assunto(df)
    assert len(pa) == 3                       # composicao tematica
    assert pa["processos"].sum() == 3         # NAO e o total de processos (1)
    assert serie_mensal(df)["processos"].sum() == 1


class _ClienteFake(ClienteDataJud):
    """Substitui so o transporte HTTP; paginacao e do codigo real."""

    def __init__(self, paginas):
        self.paginas = list(paginas)
        self.corpos = []
        self.api_key = "fake"
        self.sleep_s = 0.0
        self.max_paginas = None
        super().__post_init__()

    def _pagina(self, alias, corpo):
        self.corpos.append({k: v for k, v in corpo.items()})
        return self.paginas.pop(0) if self.paginas else {"hits": {"hits": []}}


def test_paginacao_search_after():
    p1 = {"hits": {"total": {"value": 3}, "hits": [_hit("a", "0001", []), _hit("b", "0002", [])]}}
    p2 = {"hits": {"total": {"value": 3}, "hits": [_hit("c", "0003", [])]}}
    cli = _ClienteFake([p1, p2, {"hits": {"hits": []}}])
    hits = list(cli.buscar("tjsp", montar_query(), tamanho=2))
    assert [h["_id"] for h in hits] == ["a", "b", "c"]
    # a 1a pagina nao manda search_after; as seguintes mandam o sort do ultimo hit
    assert "search_after" not in cli.corpos[0]
    assert cli.corpos[0]["sort"] == [{"_id": {"order": "asc"}}]
    assert cli.corpos[1]["search_after"] == ["b"]
    assert cli.corpos[2]["search_after"] == ["c"]


def test_paginacao_para_sem_campo_sort():
    """Resposta sem `sort` interrompe em vez de repetir a mesma pagina para sempre."""
    ruim = {"hits": {"total": {"value": 9}, "hits": [{"_id": "x", "_source": {"numeroProcesso": "9"}}]}}
    cli = _ClienteFake([ruim, ruim, ruim])
    assert len(list(cli.buscar("tjsp", montar_query()))) == 1


def test_max_paginas_trunca_explicitamente():
    p = {"hits": {"total": {"value": 99}, "hits": [_hit("a", "0001", [])]}}
    cli = _ClienteFake([p, p, p])
    cli.max_paginas = 2
    assert len(list(cli.buscar("tjsp", montar_query()))) == 2


if __name__ == "__main__":
    import traceback
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {nome}")
            except Exception:
                falhas += 1
                print(f"  FAIL  {nome}")
                traceback.print_exc()
    print(f"\n{falhas} falha(s)")
    sys.exit(1 if falhas else 0)
