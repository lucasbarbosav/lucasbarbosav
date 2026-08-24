"""Fonte 3 — Ouvidoria da ANTT: manifestacoes do setor (parse de PDF).

A RESSALVA QUE DEFINE ESTE MODULO
---------------------------------
O principal motivo de manifestacao na Ouvidoria da ANTT costuma ser **Passe
Livre / gratuidade** — acesso a politica publica, nao conflito de consumo
comercial. Somar Passe Livre com atraso, bagagem e reembolso produz um numero
grande e sem sentido, que ja circulou como "reclamacoes contra as viacoes".

Por isso este modulo classifica cada tema em tres categorias mutuamente
exclusivas — `CX`, `Passe Livre` e `Outros` — e **nunca** devolve um total que
as some. Quem quiser somar vai ter de faze-lo a mao, de olho aberto.

Segundo o proprio relatorio anual da Ouvidoria, ~73% das manifestacoes sao
pedido de informacao e apenas ~12% sao reclamacao sobre servico delegado: o
denominador "manifestacoes" nao e sinonimo de "reclamacoes".
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

log = configurar_log("antt_ouvidoria")

FONTE = "Ouvidoria da ANTT — relatorios (PDF)"
PAGINA_OUVIDORIA = "https://www.gov.br/antt/pt-br/canais-atendimento/ouvidoria"
BRUTO = DATA_RAW / "antt_ouvidoria"

CAT_CX = "CX"
CAT_PASSE_LIVRE = "Passe Livre"
CAT_OUTROS = "Outros"

# Experiencia do cliente: conflito de consumo comercial com a transportadora.
TERMOS_CX = (
    "atraso", "cancelamento", "cancelado", "bagagem", "extravio", "reembolso",
    "overbooking", "preterica", "preterido", "recusa de embarque", "nao embarque",
    "venda de passagem", "remarcacao", "veiculo", "conforto", "higiene",
    "acidente", "motorista", "tarifa", "cobranca", "descumprimento de horario",
)
# Acesso a politica publica de gratuidade. NAO e conflito de consumo comercial.
TERMOS_PASSE_LIVRE = (
    "passe livre", "gratuidade", "id jovem", "idoso", "pessoa com deficiencia",
    "pcd", "vaga gratuita", "desconto de 50", "jovem de baixa renda",
)


def classificar_tema(texto: object) -> str:
    """Classifica um rotulo de tema. Passe Livre tem precedencia deliberada.

    "Gratuidade para idoso com atraso na viagem" e um caso de Passe Livre com
    ruido de CX. Deixar CX vencer contaminaria a leitura de experiencia do
    cliente com demanda de politica publica — o erro que este modulo existe
    para evitar.
    """
    t = normalizar(texto)
    if not t:
        return CAT_OUTROS
    if any(termo in t for termo in TERMOS_PASSE_LIVRE):
        return CAT_PASSE_LIVRE
    if any(termo in t for termo in TERMOS_CX):
        return CAT_CX
    return CAT_OUTROS


def _numero(valor: object) -> float | None:
    """Converte '1.234' e '1.234,5' para numero; devolve None se nao for numero."""
    s = str(valor or "").strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.-]", "", s)
    if not re.search(r"\d", s):
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extrair_tabelas(caminho_pdf: Path) -> pd.DataFrame:
    """Extrai as tabelas do PDF com pdfplumber e as reduz a tema + quantidade.

    O layout dos relatorios da Ouvidoria varia entre edicoes, entao a heuristica
    e conservadora: uma linha so entra se tiver **um rotulo de texto e um numero**.
    O que nao casar e descartado e contabilizado no log — nunca preenchido por
    aproximacao.
    """
    import pdfplumber

    linhas, descartadas = [], 0
    with pdfplumber.open(caminho_pdf) as pdf:
        for n_pag, pagina in enumerate(pdf.pages, start=1):
            for tabela in pagina.extract_tables() or []:
                for linha in tabela:
                    celulas = [c for c in (linha or []) if c is not None]
                    if len(celulas) < 2:
                        descartadas += 1
                        continue
                    rotulo = str(celulas[0]).strip()
                    valores = [_numero(c) for c in celulas[1:]]
                    valores = [v for v in valores if v is not None]
                    if not rotulo or not valores or _numero(rotulo) is not None:
                        descartadas += 1
                        continue
                    linhas.append({
                        "pagina": n_pag,
                        "tema": re.sub(r"\s+", " ", rotulo),
                        "quantidade": valores[0],
                        "arquivo": caminho_pdf.name,
                    })
    log.info("%s: %d linhas aproveitadas, %d descartadas", caminho_pdf.name, len(linhas), descartadas)
    if not linhas:
        raise ErroDeFonte(
            f"Nenhuma tabela utilizavel em {caminho_pdf.name}. O layout dos "
            "relatorios da Ouvidoria muda entre edicoes: inspecione o PDF e ajuste "
            "extrair_tabelas() em vez de aceitar um recorte vazio."
        )
    df = pd.DataFrame(linhas)
    df["categoria"] = df["tema"].map(classificar_tema)
    ano = re.search(r"(20\d{2})", caminho_pdf.name)
    df["ano"] = int(ano.group(1)) if ano else pd.NA
    return df


def resumo_por_categoria(df: pd.DataFrame) -> pd.DataFrame:
    """Totais por categoria, em linhas separadas.

    NAO existe linha "total": somar CX com Passe Livre e precisamente o erro
    que este modulo evita. Se voce precisar de um total, escolha a categoria.
    """
    out = (
        df.groupby(["ano", "arquivo", "categoria"], dropna=False)["quantidade"]
        .sum().reset_index()
    )
    pivo = out.pivot_table(index=["ano", "arquivo"], columns="categoria",
                           values="quantidade", aggfunc="sum").reset_index()
    for cat in (CAT_CX, CAT_PASSE_LIVRE, CAT_OUTROS):
        if cat not in pivo.columns:
            pivo[cat] = 0.0
    pivo["participacao_passe_livre"] = pivo[CAT_PASSE_LIVRE] / (
        pivo[CAT_CX] + pivo[CAT_PASSE_LIVRE] + pivo[CAT_OUTROS]
    )
    return pivo


def descobrir_pdfs(sess) -> list[str]:
    """Procura links de PDF na pagina da Ouvidoria."""
    try:
        resp = sess.get(PAGINA_OUVIDORIA, timeout=120)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise ErroDeFonte(
            f"Nao consegui abrir {PAGINA_OUVIDORIA} ({exc}). Baixe os relatorios "
            "a mao e rode `python -m src.antt_ouvidoria --pdf <arquivo.pdf>`."
        ) from exc
    urls = re.findall(r'href="([^"]+\.pdf)"', resp.text, flags=re.I)
    urls = [u if u.startswith("http") else f"https://www.gov.br{u}" for u in urls]
    relatorios = [u for u in urls if "relatorio" in normalizar(u) or "ouvidoria" in normalizar(u)]
    if not relatorios:
        raise ErroDeFonte(
            f"Nenhum PDF de relatorio encontrado em {PAGINA_OUVIDORIA}. "
            "Baixe a mao e use --pdf."
        )
    log.info("%d PDF(s) de relatorio encontrados", len(relatorios))
    return sorted(set(relatorios))


def executar(refresh: bool = False, pdfs_locais: list[Path] | None = None) -> dict:
    caminhos: list[Path] = list(pdfs_locais or [])
    if not caminhos:
        sess, lim = sessao(), Limitador(1.5)
        for url in descobrir_pdfs(sess):
            destino = BRUTO / re.sub(r"[^\w.-]", "_", Path(url).name)
            caminho, _ = baixar(url, destino, FONTE, refresh=refresh, sess=sess,
                                limitador=lim, observacao="Relatorio da Ouvidoria da ANTT.")
            caminhos.append(caminho)

    df = pd.concat([extrair_tabelas(p) for p in caminhos], ignore_index=True)
    resumo = resumo_por_categoria(df)
    log.info("Participacao do Passe Livre por edicao:\n%s",
             resumo[["ano", "participacao_passe_livre"]].to_string(index=False))

    ressalva = (
        "Manifestacoes a Ouvidoria da ANTT, NAO processos e NAO reclamacoes de "
        "consumo em sentido estrito: pelo proprio relatorio, ~73% sao pedido de "
        "informacao e ~12% reclamacao sobre servico delegado. Categorias CX, "
        "Passe Livre e Outros sao mutuamente exclusivas e NUNCA devem ser "
        "somadas: Passe Livre e acesso a politica publica de gratuidade, nao "
        "conflito de consumo comercial. Extracao por heuristica de tabela em "
        "PDF — confira contra o relatorio antes de citar."
    )
    anos = df["ano"].dropna()
    periodo = f"{int(anos.min())}-{int(anos.max())}" if len(anos) else ""
    return {
        "antt_ouvidoria_temas": salvar_parquet(
            df, "antt_ouvidoria_temas", fonte=FONTE, url=PAGINA_OUVIDORIA,
            ano_base=periodo, observacao=ressalva)[1],
        "antt_ouvidoria_categorias": salvar_parquet(
            resumo, "antt_ouvidoria_categorias", fonte=FONTE, url=PAGINA_OUVIDORIA,
            ano_base=periodo, observacao=ressalva,
            derivado_de=["data/clean/antt_ouvidoria_temas.parquet"])[1],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fonte 3: Ouvidoria da ANTT")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--pdf", type=Path, nargs="*", help="PDFs locais, se ja baixados")
    args = ap.parse_args()
    try:
        executar(refresh=args.refresh, pdfs_locais=args.pdf)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
