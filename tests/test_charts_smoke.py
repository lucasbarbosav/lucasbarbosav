"""Teste de fumaca dos graficos.

FIXTURES SINTETICAS gravadas num diretorio TEMPORARIO. Nada toca `data/clean/`
nem `output/charts/` do projeto — o objetivo e so provar que cada grafico
renderiza, rotula e escreve o rodape de proveniencia sem estourar.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _common, charts  # noqa: E402
from src._common import Proveniencia  # noqa: E402


def _prov(nome, n):
    return Proveniencia(
        fonte="FIXTURE SINTETICA (teste)", url="https://exemplo.invalido",
        data_extracao="2026-08-24T12:00:00-03:00", n_registros=n,
        arquivo=f"data/clean/{nome}.parquet", ano_base="2020-2025",
        observacao="fixture de teste",
    )


def _gravar(pasta: Path, nome: str, df: pd.DataFrame):
    df.to_parquet(pasta / f"{nome}.parquet", index=False)
    (pasta / f"{nome}.meta.json").write_text(
        json.dumps(asdict(_prov(nome, len(df))), ensure_ascii=False), encoding="utf-8"
    )


ANOS = list(range(2020, 2026))
UFS = ["CE", "MG", "RJ", "SP"]


def _fixtures(pasta: Path):
    _gravar(pasta, "datajud_b2c_serie_mensal", pd.DataFrame([
        {"universo": "B2C (Justica Estadual)", "tribunal": f"TJ{uf}", "uf": uf,
         "ano": a, "mes": m, "processos": 100 + a % 100 + i * 30 + m}
        for i, uf in enumerate(UFS) for a in ANOS for m in range(1, 13)
    ]))
    _gravar(pasta, "datajud_participacao_consumo", pd.DataFrame([
        {"uf": uf, "ano": a, "mes": m, "documentos_total": 10_000,
         "documentos_consumo": 900 + i * 200 + (a - 2020) * 50}
        for i, uf in enumerate(UFS) for a in ANOS for m in range(1, 13)
    ]))
    _gravar(pasta, "consumidor_gov_empresa_ano", pd.DataFrame([
        {"segmento_rotulo": seg, "ano": a, "empresa": f"Empresa {j}", "uf": "SP",
         "reclamacoes": 500 - j * 20 + a % 7, "indice_solucao": 0.6,
         "nota_media": 3.2, "tempo_resposta_medio_dias": 6.0, "avaliadas": 100,
         "taxa_avaliacao": 0.5}
        for seg in ("Transporte Terrestre", "Transporte Aereo")
        for a in ANOS for j in range(1, 20)
    ]))
    _gravar(pasta, "consumidor_gov_problema_ano", pd.DataFrame([
        {"segmento_rotulo": "Transporte Terrestre", "ano": a, "grupo_problema": g,
         "problema": g, "reclamacoes": 300 - k * 15, "indice_solucao": 0.5}
        for a in ANOS
        for k, g in enumerate(["Atraso", "Cancelamento", "Bagagem", "Reembolso",
                               "Overbooking", "Cobranca", "Motorista"])
    ]))
    _gravar(pasta, "demanda_passageiros", pd.DataFrame([
        {"ano": a, "modal": "Rodoviario", "passageiros": 60_000_000 + a * 1000}
        for a in ANOS
    ]))
    _gravar(pasta, "datajud_b2c_por_orgao", pd.DataFrame([
        {"universo": "B2C (Justica Estadual)", "tribunal": "TJSP", "uf": "SP", "ano": a,
         "orgao_julgador_codigo": o, "orgao_julgador_nome": f"Vara {o}",
         "processos": 1000 // (o + 1)}
        for a in ANOS for o in range(1, 9)
    ]))


def test_todos_os_graficos_renderizam():
    with tempfile.TemporaryDirectory() as tmp:
        limpo, saida = Path(tmp) / "clean", Path(tmp) / "charts"
        limpo.mkdir(); saida.mkdir()
        _fixtures(limpo)

        orig_clean, orig_charts = _common.DATA_CLEAN, charts.CHARTS
        _common.DATA_CLEAN, charts.CHARTS = limpo, saida
        try:
            resultado = charts.executar()
        finally:
            _common.DATA_CLEAN, charts.CHARTS = orig_clean, orig_charts

        assert not resultado["pulados"], f"graficos pulados: {resultado['pulados']}"
        pngs = sorted(p.name for p in saida.glob("*.png"))
        assert len(pngs) == len(charts.GRAFICOS), pngs
        for p in saida.glob("*.png"):
            assert p.stat().st_size > 10_000, f"{p.name} saiu pequeno demais para ter conteudo"
        print(f"    {len(pngs)} PNGs: {', '.join(pngs)}")


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
