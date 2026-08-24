"""Tabela Processual Unificada (TPU) — dicionario de assuntos do CNJ.

Este modulo produz `docs/tpu_dicionario.csv`, que e pre-requisito de qualquer
consulta em massa ao DataJud: sem saber quais codigos de assunto compoem
"Direito do Consumidor" e "Transporte", nao existe recorte, existe chute.

**Nao ha codigo de assunto embutido neste arquivo, de proposito.** Os codigos
vem do SGT (Sistema de Gestao de Tabelas Processuais Unificadas) do CNJ, por um
destes dois caminhos:

    # 1) importar um CSV exportado a mao do SGT (caminho recomendado e auditavel)
    python -m src.tpu --de-csv ~/Downloads/assuntos_sgt.csv

    # 2) tentar a consulta publica do SGT (endpoint NAO confirmado nesta sessao)
    python -m src.tpu --do-sgt

O passo manual esta descrito em `docs/tpu_como_obter.md`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ._common import DOCS, ErroDeFonte, agora_iso, configurar_log, registrar, Proveniencia, rel

log = configurar_log("tpu")

FONTE = "SGT/CNJ — Tabela Processual Unificada (assuntos)"
SGT_CONSULTA_PUBLICA = "https://www.cnj.jus.br/sgt/consulta_publica_assuntos.php"
SGT_PORTAL = "https://www.cnj.jus.br/sgt/"

DICIONARIO = DOCS / "tpu_dicionario.csv"

# Colunas minimas do dicionario. `ramo` e o rotulo de primeiro nivel da TPU
# (ex.: "DIREITO DO CONSUMIDOR"); `codigo_pai` permite reconstruir a hierarquia.
COLUNAS = ["codigo", "nome", "ramo", "codigo_pai", "nivel", "caminho"]
OBRIGATORIAS = ["codigo", "nome"]

# Rotulos usados para recortar o dicionario. Sao filtros por TEXTO sobre o que o
# SGT devolver — nunca listas de codigos escritas a mao.
ROTULO_CONSUMO = "consumidor"
ROTULOS_TRANSPORTE = ("transporte", "transporte terrestre", "contrato de transporte")


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    ren = {}
    for c in df.columns:
        chave = c.strip().lower().replace(" ", "_")
        if chave in {"cod", "codigo", "cod_assunto", "codigo_assunto"}:
            ren[c] = "codigo"
        elif chave in {"nome", "assunto", "descricao", "nome_assunto"}:
            ren[c] = "nome"
        elif chave in {"ramo", "ramo_direito", "area"}:
            ren[c] = "ramo"
        elif chave in {"pai", "codigo_pai", "cod_pai"}:
            ren[c] = "codigo_pai"
        elif chave in {"nivel", "grau"}:
            ren[c] = "nivel"
        elif chave in {"caminho", "hierarquia", "path"}:
            ren[c] = "caminho"
    return df.rename(columns=ren)


def validar(df: pd.DataFrame) -> pd.DataFrame:
    """Recusa dicionario vazio ou sem as colunas minimas."""
    df = _normalizar_colunas(df)
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise ErroDeFonte(
            f"Dicionario TPU sem as colunas {faltando}. Colunas recebidas: "
            f"{list(df.columns)}. Veja docs/tpu_como_obter.md."
        )
    df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["codigo"]).drop_duplicates(subset=["codigo"])
    if df.empty:
        raise ErroDeFonte("Dicionario TPU vazio apos validacao — nao ha o que consultar.")
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = pd.NA
    log.info("Dicionario TPU valido: %d assuntos distintos", len(df))
    return df[COLUNAS]


def gravar(df: pd.DataFrame, url: str, observacao: str) -> Path:
    df = validar(df)
    df.to_csv(DICIONARIO, index=False, encoding="utf-8")
    registrar(
        Proveniencia(
            fonte=FONTE, url=url, data_extracao=agora_iso(), n_registros=len(df),
            arquivo=rel(DICIONARIO), origem="manual" if "Downloads" in url or url.startswith("/") else "rede",
            observacao=observacao,
        )
    )
    return DICIONARIO


def carregar() -> pd.DataFrame:
    """Le o dicionario. Erro instrutivo — nunca um fallback silencioso."""
    if not DICIONARIO.exists():
        raise ErroDeFonte(
            f"`{rel(DICIONARIO)}` nao existe. Nenhuma consulta em massa ao DataJud "
            "roda sem ele: os codigos de assunto precisam vir do SGT/CNJ, nao de "
            "memoria. Gere com `python -m src.tpu --de-csv <arquivo>` ou "
            "`--do-sgt`; o passo manual esta em docs/tpu_como_obter.md."
        )
    return validar(pd.read_csv(DICIONARIO))


def _filtrar(df: pd.DataFrame, termos: tuple[str, ...] | str) -> pd.DataFrame:
    termos = (termos,) if isinstance(termos, str) else termos
    alvo = (
        df["nome"].fillna("").str.lower()
        + " | " + df["ramo"].fillna("").astype(str).str.lower()
        + " | " + df["caminho"].fillna("").astype(str).str.lower()
    )
    mascara = pd.Series(False, index=df.index)
    for t in termos:
        mascara |= alvo.str.contains(t.lower(), regex=False, na=False)
    return df[mascara]


def codigos_consumo() -> list[int]:
    """Assuntos do ramo Direito do Consumidor."""
    sel = _filtrar(carregar(), ROTULO_CONSUMO)
    if sel.empty:
        raise ErroDeFonte(
            "Nenhum assunto de consumo encontrado no dicionario TPU. "
            "Confira se a exportacao do SGT incluiu o ramo Direito do Consumidor."
        )
    log.info("Assuntos de consumo: %d codigos", len(sel))
    return sel["codigo"].astype(int).tolist()


def codigos_transporte() -> list[int]:
    """Assuntos de transporte (usados no recorte setorial, sempre aproximado)."""
    sel = _filtrar(carregar(), ROTULOS_TRANSPORTE)
    if sel.empty:
        raise ErroDeFonte("Nenhum assunto de transporte encontrado no dicionario TPU.")
    log.info("Assuntos de transporte: %d codigos", len(sel))
    return sel["codigo"].astype(int).tolist()


def codigos_consumo_transporte() -> list[int]:
    """Intersecao consumo x transporte.

    RESSALVA: a TPU nao tem um assunto que isole "transporte rodoviario
    interestadual de passageiros". O cruzamento abaixo e a melhor aproximacao
    disponivel e deve ser rotulado como aproximacao em todo grafico.
    """
    consumo = set(codigos_consumo())
    transporte = set(codigos_transporte())
    inter = sorted(consumo & transporte)
    log.warning(
        "Intersecao consumo x transporte: %d codigos. APROXIMACAO: a TPU nao "
        "isola transporte rodoviario interestadual de passageiros.",
        len(inter),
    )
    return inter


def do_sgt() -> pd.DataFrame:
    """Tenta a consulta publica do SGT.

    ATENCAO: o endpoint abaixo NAO foi confirmado contra a documentacao viva
    (o dominio cnj.jus.br estava inacessivel quando este modulo foi escrito).
    A funcao valida a estrutura do que voltar e falha alto se nao reconhecer —
    prefira o caminho `--de-csv`, que e auditavel.
    """
    from ._common import sessao

    log.warning("Endpoint do SGT NAO confirmado; validando a resposta antes de gravar.")
    sess = sessao()
    try:
        resp = sess.get(SGT_CONSULTA_PUBLICA, timeout=120)
        resp.raise_for_status()
        tabelas = pd.read_html(resp.text)
    except Exception as exc:  # noqa: BLE001
        raise ErroDeFonte(
            f"Nao consegui obter a TPU pelo SGT ({exc}). Use o caminho manual: "
            f"exporte os assuntos em {SGT_PORTAL} e rode "
            "`python -m src.tpu --de-csv <arquivo>`. Veja docs/tpu_como_obter.md."
        ) from exc

    for t in tabelas:
        try:
            return validar(t)
        except ErroDeFonte:
            continue
    raise ErroDeFonte(
        f"O SGT respondeu, mas nenhuma tabela tinha codigo+nome de assunto. "
        f"Confira {SGT_PORTAL} e use o caminho manual."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Dicionario TPU de assuntos (SGT/CNJ)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--de-csv", type=Path, help="CSV exportado do SGT")
    g.add_argument("--do-sgt", action="store_true", help="tenta a consulta publica (endpoint nao confirmado)")
    g.add_argument("--resumo", action="store_true", help="mostra o recorte do dicionario atual")
    args = ap.parse_args()

    try:
        if args.de_csv:
            df = pd.read_csv(args.de_csv, sep=None, engine="python")
            caminho = gravar(df, url=str(args.de_csv), observacao="Exportacao manual do SGT/CNJ.")
            print(f"Dicionario gravado em {rel(caminho)}")
        elif args.do_sgt:
            df = do_sgt()
            caminho = gravar(df, url=SGT_CONSULTA_PUBLICA, observacao="Consulta publica do SGT (endpoint a confirmar).")
            print(f"Dicionario gravado em {rel(caminho)}")
        else:
            df = carregar()
            print(f"{len(df)} assuntos | consumo: {len(codigos_consumo())} | "
                  f"transporte: {len(codigos_transporte())} | "
                  f"intersecao: {len(codigos_consumo_transporte())}")
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
