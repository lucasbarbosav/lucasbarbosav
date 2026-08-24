"""Testes do classificador CX x Passe Livre (fixtures sinteticas)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.antt_ouvidoria import (  # noqa: E402
    CAT_CX, CAT_OUTROS, CAT_PASSE_LIVRE, _numero, classificar_tema, resumo_por_categoria,
)


def test_classificar_cx():
    for t in ["Atraso na partida", "Extravio de bagagem", "Reembolso não realizado",
              "Overbooking", "Cancelamento de viagem"]:
        assert classificar_tema(t) == CAT_CX, t


def test_classificar_passe_livre():
    for t in ["Passe Livre - dificuldade de reserva", "Gratuidade idoso",
              "ID Jovem", "Vaga gratuita para pessoa com deficiência"]:
        assert classificar_tema(t) == CAT_PASSE_LIVRE, t


def test_passe_livre_tem_precedencia_sobre_cx():
    """Tema misto nao pode contaminar a leitura de experiencia do cliente."""
    assert classificar_tema("Gratuidade para idoso com atraso na viagem") == CAT_PASSE_LIVRE


def test_outros():
    assert classificar_tema("Solicitação de informação sobre a agência") == CAT_OUTROS
    assert classificar_tema("") == CAT_OUTROS
    assert classificar_tema(None) == CAT_OUTROS


def test_numero_formato_brasileiro():
    assert _numero("1.234") == 1234.0
    assert _numero("1.234,5") == 1234.5
    assert _numero("12%") == 12.0
    assert _numero("Passe Livre") is None
    assert _numero("") is None


def test_resumo_nao_produz_total_somado():
    df = pd.DataFrame({
        "ano": [2025] * 3,
        "arquivo": ["rel.pdf"] * 3,
        "tema": ["Atraso", "Passe Livre", "Informação"],
        "quantidade": [100.0, 700.0, 200.0],
        "categoria": [CAT_CX, CAT_PASSE_LIVRE, CAT_OUTROS],
    })
    r = resumo_por_categoria(df)
    assert "total" not in [c.lower() for c in r.columns]  # somar e o erro que evitamos
    assert r.loc[0, CAT_CX] == 100.0 and r.loc[0, CAT_PASSE_LIVRE] == 700.0
    assert abs(r.loc[0, "participacao_passe_livre"] - 0.7) < 1e-9


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
