"""Testes de unidade da fonte 2.

ATENCAO: os dados aqui sao FIXTURES SINTETICAS, criadas so para exercitar a
logica de normalizacao e agregacao. Nao alimentam nenhum grafico nem entram em
`data/clean/`. Todo numero publicado pelo pipeline vem de download real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.consumidor_gov import (  # noqa: E402
    _agregar_empresa_ano,
    _derivar,
    _periodo_do_nome,
    _renomear,
    normalizar,
)
from src._common import ErroDeFonte  # noqa: E402


def test_normalizar():
    assert normalizar("Transporte Aéreo") == "transporte aereo"
    assert normalizar("  SÃO  PAULO ") == "sao paulo"
    assert normalizar(None) == ""


def test_periodo_do_nome():
    assert _periodo_do_nome("basecompleta2025-08.csv", "") == (2025, 8)
    assert _periodo_do_nome("Base Completa - agosto_2025", "") == (2025, 8)
    assert _periodo_do_nome("Dicionario", "") is None


FIXTURE = pd.DataFrame(
    {
        "UF": ["SP", "SP", "RJ", "CE"],
        "Ano Abertura": ["2024", "2024", "2024", "2023"],
        "Mês Abertura": ["1", "2", "3", "4"],
        "Nome Fantasia": ["Viação Alfa", "Viação Alfa", "Aérea Beta", "Viação Alfa"],
        "Segmento de Mercado": [
            "Transporte Terrestre", "Transporte Terrestre",
            "Transporte Aéreo", "Transporte Terrestre",
        ],
        "Grupo Problema": ["Atraso", "Bagagem", "Cancelamento", "Reembolso"],
        "Problema": ["Atraso na partida", "Extravio", "Voo cancelado", "Nao devolvido"],
        "Avaliação Reclamação": ["Resolvida", "Não Resolvida", "Resolvida", ""],
        "Nota do Consumidor": ["5", "1", "4", ""],
        "Tempo Resposta": ["3,5", "8,0", "2,0", ""],
        "Respondida": ["S", "S", "S", "N"],
        "Situação": ["Finalizada avaliada"] * 4,
    }
)


def test_renomear_e_derivar():
    df = _derivar(_renomear(FIXTURE, "fixture"))
    assert list(df["segmento_norm"].unique()) == ["transporte terrestre", "transporte aereo"]
    assert df["ano"].tolist() == [2024, 2024, 2024, 2023]
    # avaliacao vazia => NA (consumidor nao avaliou), nunca contada como "nao resolvida"
    assert df["resolvida"].tolist()[:2] == [True, False]
    assert pd.isna(df["resolvida"].iloc[3])
    assert df["tempo_resposta_dias"].iloc[0] == 3.5


def test_renomear_falha_alto_sem_coluna_obrigatoria():
    ruim = FIXTURE.drop(columns=["Segmento de Mercado"])
    try:
        _renomear(ruim, "fixture-ruim")
    except ErroDeFonte as exc:
        assert "segmento" in str(exc)
    else:
        raise AssertionError("deveria ter falhado alto em vez de seguir sem o segmento")


def test_agregar_empresa_ano():
    df = _derivar(_renomear(FIXTURE, "fixture"))
    df["segmento_rotulo"] = df["segmento_norm"].map(
        {"transporte terrestre": "Transporte Terrestre", "transporte aereo": "Transporte Aereo"}
    )
    ag = _agregar_empresa_ano(df)
    alfa24 = ag[(ag["empresa"] == "Viação Alfa") & (ag["ano"] == 2024)].iloc[0]
    assert alfa24["reclamacoes"] == 2
    assert alfa24["indice_solucao"] == 0.5  # 1 resolvida de 2 avaliadas
    assert alfa24["taxa_avaliacao"] == 1.0
    # o ano de 2023 (avaliacao vazia) nao vira "0% de solucao": fica sem avaliada
    alfa23 = ag[(ag["empresa"] == "Viação Alfa") & (ag["ano"] == 2023)].iloc[0]
    assert alfa23["avaliadas"] == 0
    assert pd.isna(alfa23["indice_solucao"])


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
