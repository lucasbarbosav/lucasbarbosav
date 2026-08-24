"""Testes de unidade das metricas derivadas (fixtures sinteticas)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analise import concentracao, hhi, picos_anomalos, por_100k, razao_judicial_reclamacao  # noqa: E402


def test_hhi():
    assert hhi(pd.Series([100])) == 1.0                    # monopolio
    assert abs(hhi(pd.Series([25, 25, 25, 25])) - 0.25) < 1e-9  # 4 iguais
    assert pd.isna(hhi(pd.Series([0, 0])))


def test_por_100k_nao_zera_o_que_nao_tem_denominador():
    """O ponto: linha sem passageiros sai separada, nao vira taxa infinita."""
    metrica = pd.DataFrame({"ano": [2023, 2024, 2025], "reclamacoes": [10, 20, 30]})
    demanda = pd.DataFrame({"ano": [2023, 2024], "passageiros": [1_000_000, 2_000_000]})
    casadas, sobras = por_100k(metrica, demanda, coluna_valor="reclamacoes")
    assert len(casadas) == 2 and len(sobras) == 1
    assert casadas["por_100k_passageiros"].tolist() == [1.0, 1.0]
    assert sobras["ano"].tolist() == [2025]
    assert "por_100k_passageiros" not in sobras.columns


def test_por_100k_denominador_zero_tambem_e_separado():
    metrica = pd.DataFrame({"ano": [2024], "reclamacoes": [5]})
    demanda = pd.DataFrame({"ano": [2024], "passageiros": [0]})
    casadas, sobras = por_100k(metrica, demanda, coluna_valor="reclamacoes")
    assert casadas.empty and len(sobras) == 1


def test_normalizacao_inverte_o_ranking_absoluto():
    """Motivo de existir da normalizacao: volume absoluto premia quem e pequeno."""
    metrica = pd.DataFrame({"ano": [2024, 2024], "empresa": ["Grande", "Pequena"], "reclamacoes": [900, 100]})
    demanda = pd.DataFrame({"ano": [2024, 2024], "empresa": ["Grande", "Pequena"], "passageiros": [90_000_000, 1_000_000]})
    casadas, _ = por_100k(metrica, demanda, coluna_valor="reclamacoes", chaves=("ano", "empresa"))
    taxa = casadas.set_index("empresa")["por_100k_passageiros"]
    assert taxa["Grande"] == 1.0 and taxa["Pequena"] == 10.0
    assert taxa.idxmax() == "Pequena"  # lider absoluto era "Grande"


def test_concentracao():
    df = pd.DataFrame({
        "ano": [2024] * 4 + [2025] * 4,
        "orgao": ["A", "B", "C", "D"] * 2,
        "processos": [97, 1, 1, 1, 25, 25, 25, 25],
    })
    c = concentracao(df, grupo="orgao", valor="processos", topo=2).set_index("ano")
    assert c.loc[2024, "hhi"] > 0.9 and abs(c.loc[2025, "hhi"] - 0.25) < 1e-9
    assert c.loc[2024, "lider"] == "A" and abs(c.loc[2024, "share_lider"] - 0.97) < 1e-9
    assert "ressalva" in c.columns  # o numero nunca viaja sem a ressalva


def test_razao_sem_reclamacao_e_indefinida_nao_infinita():
    j = pd.DataFrame({"ano": [2024, 2025], "uf": ["SP", "SP"], "processos": [100, 50]})
    r = pd.DataFrame({"ano": [2024, 2025], "uf": ["SP", "SP"], "reclamacoes": [200, 0]})
    out = razao_judicial_reclamacao(j, r).set_index("ano")
    assert out.loc[2024, "razao_acoes_por_reclamacao"] == 0.5
    assert pd.isna(out.loc[2025, "razao_acoes_por_reclamacao"])


def test_picos_usa_mad_e_nao_media():
    """Com desvio-padrao o proprio surto se esconde; com MAD ele aparece."""
    serie = pd.DataFrame({"mes": range(1, 13), "processos": [10] * 11 + [500]})
    out = picos_anomalos(serie, valor="processos")
    assert out["pico"].tolist() == [False] * 11 + [True]


def test_picos_por_grupo():
    serie = pd.DataFrame({
        "orgao": ["A"] * 6 + ["B"] * 6,
        "mes": list(range(1, 7)) * 2,
        "processos": [10, 11, 9, 10, 10, 400] + [50, 52, 48, 51, 49, 50],
    })
    out = picos_anomalos(serie, valor="processos", por=("orgao",))
    picos = out[out["pico"]]
    assert picos["orgao"].tolist() == ["A"] and picos["processos"].tolist() == [400]


def test_picos_serie_plana_nao_inventa_pico():
    serie = pd.DataFrame({"mes": range(1, 7), "processos": [10] * 6})
    out = picos_anomalos(serie, valor="processos")
    assert not out["pico"].any()


if __name__ == "__main__":
    import traceback
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  PASS  {nome}")
            except Exception:
                falhas += 1; print(f"  FAIL  {nome}"); traceback.print_exc()
    print(f"\n{falhas} falha(s)")
    sys.exit(1 if falhas else 0)
