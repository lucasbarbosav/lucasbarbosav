"""Fonte 4 — Painel dos Grandes Litigantes (CNJ): checagem de concentracao.

O painel do CNJ e um **produto publicado**, nao uma API consultavel: os numeros
sao servidos por um painel interativo, sem endpoint documentado que aceite
consulta arbitraria. Raspar a camada interna de um painel produz um pipeline que
quebra em silencio na primeira mudanca de layout — e um numero errado que ninguem
percebe e pior do que um passo manual.

Entao o caminho aqui e o mesmo do dicionario TPU: **importacao auditavel**.
Voce exporta a tabela do painel, e este modulo valida, normaliza e registra a
proveniencia.

    python -m src.grandes_litigantes --de-csv ~/Downloads/grandes_litigantes.csv

O passo manual esta em `docs/grandes_litigantes_como_obter.md`.

Para que serve: responder se empresas de transporte aparecem entre os maiores
reus, por UF e segmento. E uma **checagem de sanidade** do sinal de concentracao
calculado em `src/analise.py`, nao a medida principal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ._common import ErroDeFonte, configurar_log, salvar_parquet
from .consumidor_gov import normalizar

log = configurar_log("grandes_litigantes")

FONTE = "Painel dos Grandes Litigantes (CNJ) — exportacao manual"
PAINEL = "https://painelgrandeslitigantes.cnj.jus.br/"
NOTICIA_CNJ = "https://www.cnj.jus.br/primeira-versao-de-painel-sobre-grandes-litigantes-no-brasil-e-lancada/"

MAPA = {
    "litigante": ("litigante", "nome", "parte", "razao social", "nome do litigante"),
    "polo": ("polo", "posicao", "tipo", "polo processual"),
    "ramo_justica": ("ramo", "ramo da justica", "segmento", "justica"),
    "uf": ("uf", "estado", "tribunal"),
    "setor": ("setor", "atividade", "cnae", "ramo de atividade"),
    "processos": ("processos", "quantidade", "casos novos", "pendentes", "total"),
    "ano": ("ano", "ano base", "periodo"),
}
OBRIGATORIAS = ("litigante", "processos")

# Termos que sinalizam transporte rodoviario de passageiros na lista de litigantes.
TERMOS_TRANSPORTE = (
    "viacao", "viação", "expresso", "transporte", "rodoviaria", "auto viacao",
    "turismo", "onibus", "buser", "gadotti", "rota transportes", "itapemirim",
    "cometa", "catarinense", "gontijo", "util", "aguia branca", "eucatur",
)


def _renomear(df: pd.DataFrame) -> pd.DataFrame:
    achadas = {normalizar(c): c for c in df.columns}
    renome = {}
    for canonico, sinonimos in MAPA.items():
        for s in sinonimos:
            if s in achadas:
                renome[achadas[s]] = canonico
                break
    df = df.rename(columns=renome)
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise ErroDeFonte(
            f"Exportacao do painel sem as colunas {faltando}. Colunas vistas: "
            f"{sorted(achadas)}. Veja docs/grandes_litigantes_como_obter.md."
        )
    return df[[c for c in MAPA if c in df.columns]].copy()


def marcar_transporte(df: pd.DataFrame) -> pd.DataFrame:
    """Marca litigantes que parecem ser do transporte rodoviario de passageiros.

    RESSALVA: e um filtro por nome, sujeito a falso positivo ("Turismo" tambem
    aparece em agencia de viagem) e a falso negativo (holding com nome neutro).
    A coluna e um ponto de partida para conferencia humana, nao um classificador.
    """
    alvo = df["litigante"].map(normalizar)
    setor = df["setor"].map(normalizar) if "setor" in df.columns else ""
    df = df.copy()
    df["parece_transporte"] = False
    for termo in TERMOS_TRANSPORTE:
        df["parece_transporte"] |= alvo.str.contains(normalizar(termo), regex=False, na=False)
        if isinstance(setor, pd.Series):
            df["parece_transporte"] |= setor.str.contains(normalizar(termo), regex=False, na=False)
    n = int(df["parece_transporte"].sum())
    log.info("%d de %d litigantes marcados como possivel transporte (conferir a mao)", n, len(df))
    if n == 0:
        log.warning(
            "Nenhum litigante de transporte no painel. Isso e um ACHADO, nao um erro: "
            "sugere que as viacoes nao estao entre os maiores reus — coerente com a "
            "lacuna do rodoviario B2C observada no DataJud."
        )
    return df


def executar(refresh: bool = False, caminho_csv: Path | None = None) -> dict:
    if caminho_csv is None or not Path(caminho_csv).exists():
        raise ErroDeFonte(
            "O Painel dos Grandes Litigantes e um painel publicado, sem API "
            f"consultavel. Exporte a tabela em {PAINEL} e rode "
            "`python -m src.grandes_litigantes --de-csv <arquivo>`. "
            "O passo esta documentado em docs/grandes_litigantes_como_obter.md — "
            "raspar a camada interna do painel daria um pipeline que quebra calado."
        )
    bruto = pd.read_csv(caminho_csv, sep=None, engine="python")
    df = marcar_transporte(_renomear(bruto))
    df["processos"] = pd.to_numeric(
        df["processos"].astype(str).str.replace(r"[.\s]", "", regex=True).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    df = df.dropna(subset=["processos"])
    if df.empty:
        raise ErroDeFonte("Exportacao sem nenhuma linha com contagem valida de processos.")

    return {"grandes_litigantes": salvar_parquet(
        df, "grandes_litigantes", fonte=FONTE, url=PAINEL,
        observacao="Exportacao manual do painel do CNJ. A coluna `parece_transporte` "
                   "e um filtro por nome, sujeito a falso positivo e negativo: e ponto "
                   "de partida para conferencia humana, nao classificador. Checagem de "
                   "sanidade do sinal de concentracao, nao a medida principal.",
    )[1]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fonte 4: Painel dos Grandes Litigantes (CNJ)")
    ap.add_argument("--de-csv", type=Path, default=None, help="tabela exportada do painel")
    args = ap.parse_args()
    try:
        executar(caminho_csv=args.de_csv)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
