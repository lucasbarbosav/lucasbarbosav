"""Fonte 5 — passageiros transportados: o denominador das comparacoes.

Comparar empresas ou modais por volume absoluto de reclamacao premia quem e
pequeno e pune quem carrega mais gente. Toda comparacao deste projeto usa
**reclamacoes (ou acoes) por 100 mil passageiros**, e o denominador vem daqui.

- Rodoviario interestadual/internacional: portal de dados abertos da ANTT (CKAN).
- Aereo (benchmark): ANAC. A ANAC nao publica um CKAN equivalente, entao o
  caminho e importar o CSV baixado do portal — `--anac-csv <arquivo>`. Nao ha
  URL adivinhada aqui.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from ._common import (
    DATA_RAW,
    ErroDeFonte,
    Limitador,
    baixar,
    configurar_log,
    salvar_parquet,
    sessao,
)
from .consumidor_gov import normalizar

log = configurar_log("demanda")

FONTE_ANTT = "ANTT — Portal de Dados Abertos (transporte rodoviario de passageiros)"
FONTE_ANAC = "ANAC — estatisticas de passageiros (importacao manual)"
CKAN_ANTT = "https://dados.antt.gov.br/api/3/action/package_show?id=transporte-rodoviario-de-passageiros"
PAGINA_ANTT = "https://dados.antt.gov.br/dataset/transporte-rodoviario-de-passageiros"
PORTAL_ANAC = "https://www.gov.br/anac/pt-br/assuntos/regulados/empresas-aereas/envio-de-informacoes/microdados"

BRUTO = DATA_RAW / "demanda"

# Nomes de coluna aceitos para a contagem de passageiros e para o periodo.
COLS_PASSAGEIROS = ("passageiros", "passageiros transportados", "qtd passageiros",
                    "quantidade de passageiros", "total de passageiros", "pax")
COLS_ANO = ("ano", "ano referencia", "ano de referencia")
COLS_MES = ("mes", "mes referencia", "mes de referencia")
COLS_EMPRESA = ("empresa", "razao social", "nome empresa", "transportadora")


def _achar(df: pd.DataFrame, candidatos: tuple[str, ...]) -> str | None:
    mapa = {normalizar(c): c for c in df.columns}
    for c in candidatos:
        if c in mapa:
            return mapa[c]
    # tentativa por conteudo do nome, ainda deterministica
    for chave, original in mapa.items():
        if any(c in chave for c in candidatos):
            return original
    return None


def padronizar(df: pd.DataFrame, modal: str, origem: str) -> pd.DataFrame:
    """Reduz uma planilha de demanda ao minimo que o pipeline usa."""
    col_pax = _achar(df, COLS_PASSAGEIROS)
    col_ano = _achar(df, COLS_ANO)
    if not col_pax or not col_ano:
        raise ErroDeFonte(
            f"{origem}: nao identifiquei coluna de passageiros ({col_pax}) ou de ano "
            f"({col_ano}). Colunas: {list(df.columns)[:30]}. Ajuste COLS_* em "
            "src/demanda.py em vez de deixar o denominador errado passar."
        )
    out = pd.DataFrame({
        "ano": pd.to_numeric(df[col_ano], errors="coerce").astype("Int64"),
        "passageiros": pd.to_numeric(
            df[col_pax].astype(str).str.replace(r"[.\s]", "", regex=True).str.replace(",", ".", regex=False),
            errors="coerce",
        ),
    })
    col_mes = _achar(df, COLS_MES)
    if col_mes is not None:
        out["mes"] = pd.to_numeric(df[col_mes], errors="coerce").astype("Int64")
    col_emp = _achar(df, COLS_EMPRESA)
    if col_emp is not None:
        out["empresa"] = df[col_emp].astype(str).str.strip()
        out["empresa_norm"] = out["empresa"].map(normalizar)
    out["modal"] = modal
    out = out.dropna(subset=["ano", "passageiros"])
    if out.empty:
        raise ErroDeFonte(f"{origem}: nenhuma linha valida apos padronizacao.")
    log.info("%s: %d linhas, %s passageiros no total", origem, len(out),
             f"{int(out['passageiros'].sum()):,}".replace(",", "."))
    return out


def _ler_tabela(caminho: Path) -> pd.DataFrame:
    if caminho.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(caminho)
    for enc in ("utf-8-sig", "latin-1"):
        for sep in (";", ","):
            try:
                df = pd.read_csv(caminho, sep=sep, encoding=enc, dtype=str, low_memory=False)
                if df.shape[1] > 1:
                    return df
            except Exception:  # noqa: BLE001,S112
                continue
    raise ErroDeFonte(f"Nao consegui parsear {caminho}.")


def antt(refresh: bool = False) -> pd.DataFrame:
    """Descobre e baixa os recursos de passageiros do CKAN da ANTT."""
    sess, lim = sessao(), Limitador(1.0)
    try:
        resp = sess.get(CKAN_ANTT, timeout=120)
        resp.raise_for_status()
        dados = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ErroDeFonte(
            f"Nao consegui ler o catalogo da ANTT ({exc}). Confira {PAGINA_ANTT}."
        ) from exc
    if not dados.get("success"):
        raise ErroDeFonte(f"CKAN da ANTT respondeu sem sucesso: {dados}")

    recursos = [
        r for r in dados["result"].get("resources", [])
        if "passageiro" in normalizar(r.get("name", "") + " " + r.get("description", ""))
        and (normalizar(r.get("format", "")) in {"csv", "xlsx"} or r.get("url", "").lower().endswith((".csv", ".xlsx")))
    ]
    if not recursos:
        nomes = [r.get("name") for r in dados["result"].get("resources", [])][:20]
        raise ErroDeFonte(
            f"Nenhum recurso de passageiros no dataset da ANTT. Recursos vistos: {nomes}. "
            f"Confira {PAGINA_ANTT} — sem denominador nao ha normalizacao por 100 mil."
        )

    partes = []
    for r in recursos:
        url = r["url"]
        destino = BRUTO / re.sub(r"[^\w.-]", "_", Path(url).name or f"{r['id']}.csv")
        caminho, _ = baixar(url, destino, FONTE_ANTT, refresh=refresh, sess=sess,
                            limitador=lim, observacao=f"Recurso ANTT: {r.get('name')}")
        partes.append(padronizar(_ler_tabela(caminho), "Rodoviario", destino.name))
    return pd.concat(partes, ignore_index=True)


def anac(caminho_csv: Path) -> pd.DataFrame:
    if not caminho_csv.exists():
        raise ErroDeFonte(
            f"{caminho_csv} nao existe. Baixe as estatisticas de passageiros em "
            f"{PORTAL_ANAC} e rode `python -m src.demanda --anac-csv <arquivo>`. "
            "Nao ha URL da ANAC embutida aqui porque nao foi possivel confirma-la."
        )
    return padronizar(_ler_tabela(caminho_csv), "Aereo", caminho_csv.name)


def executar(refresh: bool = False, anac_csv: Path | None = None) -> dict:
    partes = [antt(refresh=refresh)]
    if anac_csv:
        partes.append(anac(anac_csv))
    else:
        log.warning(
            "Sem CSV da ANAC: o benchmark aereo fica SEM denominador e nao podera "
            "ser normalizado por 100 mil passageiros. Use --anac-csv."
        )
    df = pd.concat(partes, ignore_index=True)
    periodo = f"{int(df['ano'].min())}-{int(df['ano'].max())}"
    salvos = {"demanda_passageiros": salvar_parquet(
        df, "demanda_passageiros", fonte=FONTE_ANTT, url=PAGINA_ANTT, ano_base=periodo,
        observacao="Denominador das metricas por 100 mil passageiros. Rodoviario: ANTT. "
                   "Aereo: ANAC (importacao manual). Modais em linhas distintas, "
                   "jamais somados.",
    )[1]}
    return salvos


def main() -> int:
    ap = argparse.ArgumentParser(description="Fonte 5: passageiros transportados")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--anac-csv", type=Path, default=None, help="CSV de passageiros baixado da ANAC")
    args = ap.parse_args()
    try:
        executar(refresh=args.refresh, anac_csv=args.anac_csv)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
