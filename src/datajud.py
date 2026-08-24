"""Fonte 1 — DataJud / API Publica do CNJ: volume judicial por assunto e tempo.

O QUE ESTA FONTE MEDE (e o que NAO mede)
----------------------------------------
Mede: quantidade de processos distintos por assunto, classe, tribunal, orgao
julgador e data de ajuizamento.

NAO mede: quem sao as partes. A API publica **nao expoe o nome das partes de
forma estruturada e consultavel**. E impossivel filtrar "acoes contra a viacao
X" por aqui, e qualquer tentativa nesse sentido seria invencao. A analise por
empresa vem do consumidor.gov.br (`src/consumidor_gov.py`).

DOIS UNIVERSOS QUE NUNCA SE SOMAM
---------------------------------
- **B2C** — Justica Estadual (aliases `tj*`) + assuntos de consumo. E a leitura
  de experiencia do cliente.
- **Regulatorio/concorrencial** — Justica Federal (aliases `trf*`), tipicamente
  com a ANTT como parte (casos tipo Buser, Gadotti, Rota Transportes). E
  dimensionado para se saber o tamanho, e entao **excluido** da leitura de CX.

CONTAGEM
--------
Um processo pode ter varios assuntos. Toda contagem e por `numeroProcesso`
distinto, nunca por ocorrencia de assunto — somar ocorrencias infla o volume.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd

from ._common import (
    DATA_RAW,
    ErroDeFonte,
    Limitador,
    Proveniencia,
    agora_iso,
    configurar_log,
    post_json,
    registrar,
    rel,
    salvar_parquet,
    sessao,
)

log = configurar_log("datajud")

FONTE = "DataJud — API Publica (CNJ)"
BASE_URL = "https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search"
WIKI_ACESSO = "https://datajud-wiki.cnj.jus.br/api-publica/acesso"
WIKI_ENDPOINTS = "https://datajud-wiki.cnj.jus.br/api-publica/endpoints"

BRUTO = DATA_RAW / "datajud"

# UFs prioritarias do estudo -> alias do tribunal estadual.
TRIBUNAIS_ESTADUAIS = {"SP": "tjsp", "RJ": "tjrj", "MG": "tjmg", "CE": "tjce"}
# Justica Federal: universo regulatorio, dimensionado e excluido da leitura B2C.
TRIBUNAIS_FEDERAIS = {f"TRF{n}": f"trf{n}" for n in range(1, 7)}

UNIVERSO_B2C = "B2C (Justica Estadual)"
UNIVERSO_REGULATORIO = "Regulatorio (Justica Federal)"

TAMANHO_PAGINA = 1000  # maximo aceito pela API


def universo_do_alias(alias: str) -> str:
    """Classifica o alias no universo correto. Nunca ha um terceiro balde."""
    a = alias.lower()
    if a.startswith("tj"):
        return UNIVERSO_B2C
    if a.startswith("trf"):
        return UNIVERSO_REGULATORIO
    raise ValueError(
        f"Alias '{alias}' nao e estadual (tj*) nem federal (trf*). "
        "Classifique-o explicitamente antes de misturar universos."
    )


def uf_do_alias(alias: str) -> str:
    for uf, a in TRIBUNAIS_ESTADUAIS.items():
        if a == alias.lower():
            return uf
    return ""


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------
def obter_chave() -> str:
    """Le DATAJUD_API_KEY do ambiente/.env. Sem chave inventada, jamais."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    chave = (os.getenv("DATAJUD_API_KEY") or "").strip()
    if not chave:
        raise ErroDeFonte(
            "DATAJUD_API_KEY nao definida. A chave publica do DataJud e divulgada "
            f"pelo proprio CNJ em {WIKI_ACESSO} — copie de la para o seu `.env`. "
            "Este repositorio nao embute chave alguma de proposito: credencial "
            "adivinhada e erro silencioso esperando para acontecer."
        )
    return chave


@dataclass
class ClienteDataJud:
    """Cliente minimo da API publica: POST de Query DSL, paginado e com freio."""

    api_key: str = field(default_factory=obter_chave)
    sleep_s: float = float(os.getenv("DATAJUD_SLEEP_S", "1.5"))
    max_paginas: int | None = None

    def __post_init__(self) -> None:
        self.sess = sessao()
        self.limitador = Limitador(self.sleep_s)  # sem paralelismo: um por vez

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"APIKey {self.api_key}", "Content-Type": "application/json"}

    def _pagina(self, alias: str, corpo: dict[str, Any]) -> dict[str, Any]:
        self.limitador.espera()
        url = BASE_URL.format(alias=alias)
        try:
            return post_json(self.sess, url, corpo, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            raise ErroDeFonte(
                f"Falha na consulta ao DataJud ({alias}): {exc}. "
                f"Confira a chave e os endpoints em {WIKI_ENDPOINTS}."
            ) from exc

    def contar(self, alias: str, query: dict[str, Any]) -> int:
        """Conta documentos sem baixa-los (`size: 0`).

        Barato e exato para totais, mas conta DOCUMENTOS, nao processos
        distintos: o DataJud guarda um documento por processo *por grau*. Use
        sempre com filtro de grau (ver `serie_participacao`) quando o numero
        for comparado com outra contagem.
        """
        resp = self._pagina(alias, {"size": 0, "query": query, "track_total_hits": True})
        total = resp.get("hits", {}).get("total", {})
        return int(total.get("value", 0) if isinstance(total, dict) else total or 0)

    def buscar(
        self, alias: str, query: dict[str, Any], tamanho: int = TAMANHO_PAGINA
    ) -> Iterator[dict[str, Any]]:
        """Itera todos os hits paginando com `search_after` ordenado por `_id`.

        `search_after` e a unica paginacao segura em volume: `from`/`size` estoura
        o limite de janela do Elasticsearch e repete/pula documentos.
        """
        corpo = {"size": tamanho, "query": query, "sort": [{"_id": {"order": "asc"}}]}
        pagina = 0
        total_declarado: int | None = None
        vistos = 0
        while True:
            resp = self._pagina(alias, corpo)
            hits = resp.get("hits", {})
            if total_declarado is None:
                total = hits.get("total", {})
                total_declarado = total.get("value") if isinstance(total, dict) else total
                log.info("%s: total declarado pela API = %s", alias, total_declarado)
            lote = hits.get("hits", [])
            if not lote:
                break
            for h in lote:
                vistos += 1
                yield h
            pagina += 1
            log.info("%s: pagina %d, %d hits acumulados", alias, pagina, vistos)
            if self.max_paginas and pagina >= self.max_paginas:
                log.warning(
                    "%s: parando em %d paginas (limite --max-paginas). "
                    "A serie fica TRUNCADA: %d de %s documentos.",
                    alias, pagina, vistos, total_declarado,
                )
                break
            ultimo = lote[-1].get("sort")
            if not ultimo:
                log.warning("%s: resposta sem campo `sort`; paginacao interrompida.", alias)
                break
            corpo["search_after"] = ultimo


# --------------------------------------------------------------------------
# Query DSL
# --------------------------------------------------------------------------
def montar_query(
    *,
    assuntos: list[int] | None = None,
    classes: list[int] | None = None,
    inicio: str | None = None,
    fim: str | None = None,
    orgaos: list[int] | None = None,
    graus: list[str] | None = None,
) -> dict[str, Any]:
    """Monta o filtro booleano. Datas em AAAA-MM-DD."""
    must: list[dict[str, Any]] = []
    if assuntos:
        must.append({"terms": {"assuntos.codigo": list(assuntos)}})
    if classes:
        must.append({"terms": {"classe.codigo": list(classes)}})
    if orgaos:
        must.append({"terms": {"orgaoJulgador.codigo": list(orgaos)}})
    if graus:
        must.append({"terms": {"grau": list(graus)}})
    if inicio or fim:
        faixa: dict[str, str] = {}
        if inicio:
            faixa["gte"] = inicio
        if fim:
            faixa["lte"] = fim
        must.append({"range": {"dataAjuizamento": faixa}})
    return {"bool": {"must": must}} if must else {"match_all": {}}


# --------------------------------------------------------------------------
# Achatamento e deduplicacao
# --------------------------------------------------------------------------
def _assuntos(fonte: dict[str, Any]) -> tuple[list[int], list[str]]:
    bruto = fonte.get("assuntos") or []
    if isinstance(bruto, dict):
        bruto = [bruto]
    codigos, nomes = [], []
    for a in bruto:
        if not isinstance(a, dict):
            continue
        if a.get("codigo") is not None:
            codigos.append(int(a["codigo"]))
        if a.get("nome"):
            nomes.append(str(a["nome"]))
    return codigos, nomes


def achatar(hits: list[dict[str, Any]], alias: str) -> pd.DataFrame:
    """Um hit -> uma linha. Tolerante a campo ausente; nada e inventado."""
    linhas = []
    for h in hits:
        f = h.get("_source", h) or {}
        classe = f.get("classe") or {}
        orgao = f.get("orgaoJulgador") or {}
        codigos, nomes = _assuntos(f)
        linhas.append(
            {
                "numero_processo": f.get("numeroProcesso"),
                "alias": alias,
                "tribunal": f.get("tribunal") or alias.upper(),
                "uf": uf_do_alias(alias),
                "universo": universo_do_alias(alias),
                "grau": f.get("grau"),
                "classe_codigo": (classe or {}).get("codigo"),
                "classe_nome": (classe or {}).get("nome"),
                "orgao_julgador_codigo": (orgao or {}).get("codigo"),
                "orgao_julgador_nome": (orgao or {}).get("nome"),
                "municipio_ibge": (orgao or {}).get("codigoMunicipioIBGE"),
                "data_ajuizamento": f.get("dataAjuizamento"),
                "assuntos_codigos": codigos,
                "assuntos_nomes": nomes,
                "n_assuntos": len(codigos),
            }
        )
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df["data_ajuizamento"] = pd.to_datetime(df["data_ajuizamento"], errors="coerce", utc=True)
    df["ano"] = df["data_ajuizamento"].dt.year.astype("Int64")
    df["mes"] = df["data_ajuizamento"].dt.month.astype("Int64")
    return df


def deduplicar(df: pd.DataFrame) -> pd.DataFrame:
    """Um processo, um registro. Base de toda contagem deste modulo."""
    if df.empty:
        return df
    antes = len(df)
    df = df.drop_duplicates(subset=["numero_processo"], keep="first")
    if antes != len(df):
        log.info("Deduplicacao por numeroProcesso: %d -> %d linhas", antes, len(df))
    return df


# --------------------------------------------------------------------------
# Agregacoes (sempre sobre processos distintos)
# --------------------------------------------------------------------------
def serie_mensal(df: pd.DataFrame) -> pd.DataFrame:
    """Casos novos por mes. Conta `numero_processo` distinto."""
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby(["universo", "tribunal", "uf", "ano", "mes"], dropna=False)["numero_processo"]
        .nunique()
        .reset_index(name="processos")
        .sort_values(["universo", "tribunal", "ano", "mes"])
    )


def por_assunto(df: pd.DataFrame) -> pd.DataFrame:
    """Processos distintos por assunto.

    ATENCAO: as linhas NAO somam ao total de processos. Um processo com tres
    assuntos aparece em tres linhas — de proposito, para se ver a composicao
    tematica. Para totais, use `serie_mensal`.
    """
    if df.empty:
        return pd.DataFrame()
    expl = df.explode("assuntos_codigos").dropna(subset=["assuntos_codigos"])
    if expl.empty:
        return pd.DataFrame()
    expl["assunto_codigo"] = expl["assuntos_codigos"].astype(int)
    return (
        expl.groupby(["universo", "tribunal", "ano", "assunto_codigo"], dropna=False)["numero_processo"]
        .nunique()
        .reset_index(name="processos")
        .sort_values(["universo", "ano", "processos"], ascending=[True, True, False])
    )


def por_orgao(df: pd.DataFrame) -> pd.DataFrame:
    """Concentracao por orgao julgador — insumo do sinal de litigancia de massa."""
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby(["universo", "tribunal", "uf", "ano", "orgao_julgador_codigo", "orgao_julgador_nome"], dropna=False)["numero_processo"]
        .nunique()
        .reset_index(name="processos")
        .sort_values(["ano", "processos"], ascending=[True, False])
    )


def serie_participacao(
    aliases: list[str], assuntos: list[int], inicio: str, fim: str, grau: str = "G1"
) -> pd.DataFrame:
    """Participacao do consumo no total de casos novos, mes a mes.

    Numerador e denominador sao medidos do MESMO jeito — contagem de documentos
    no mesmo `grau` — para que a razao signifique alguma coisa. Comparar
    processos deduplicados (numerador) com documentos (denominador) daria uma
    participacao artificialmente baixa, porque o denominador contaria cada
    processo uma vez por grau.
    """
    cliente = ClienteDataJud()
    linhas = []
    for alias in aliases:
        for periodo in pd.date_range(inicio, fim, freq="MS"):
            ini = periodo.strftime("%Y-%m-%d")
            fimm = (periodo + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
            base = dict(inicio=ini, fim=fimm, graus=[grau])
            total = cliente.contar(alias, montar_query(**base))
            consumo = cliente.contar(alias, montar_query(assuntos=assuntos, **base))
            if total <= 0:
                log.warning("%s %s: total zero — mes ignorado, nao zerado.", alias, ini)
                continue
            linhas.append({
                "alias": alias, "tribunal": alias.upper(), "uf": uf_do_alias(alias),
                "universo": universo_do_alias(alias), "grau": grau,
                "ano": periodo.year, "mes": periodo.month,
                "documentos_total": total, "documentos_consumo": consumo,
                "participacao_consumo": consumo / total,
            })
            log.info("%s %s: consumo %d / total %d", alias, ini, consumo, total)
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------
# Consulta piloto
# --------------------------------------------------------------------------
def piloto(alias: str = "tjsp", ano: int = 2024, mes: int = 1, limite: int = 200) -> pd.DataFrame:
    """Consulta pequena (um tribunal, um mes) para inspecao antes do volume.

    Grava a resposta crua em `data/raw/datajud/` e imprime os campos realmente
    presentes — e assim que o layout do documento se confirma, e nao por suposicao.
    """
    from calendar import monthrange

    cliente = ClienteDataJud(max_paginas=max(1, limite // TAMANHO_PAGINA + 1))
    ultimo_dia = monthrange(ano, mes)[1]
    query = montar_query(inicio=f"{ano}-{mes:02d}-01", fim=f"{ano}-{mes:02d}-{ultimo_dia}")
    log.info("PILOTO %s %04d-%02d — query: %s", alias, ano, mes, json.dumps(query, ensure_ascii=False))

    hits = []
    for h in cliente.buscar(alias, query, tamanho=min(limite, TAMANHO_PAGINA)):
        hits.append(h)
        if len(hits) >= limite:
            break

    BRUTO.mkdir(parents=True, exist_ok=True)
    destino = BRUTO / f"piloto_{alias}_{ano}{mes:02d}.json"
    destino.write_text(json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")
    registrar(
        Proveniencia(
            fonte=FONTE, url=BASE_URL.format(alias=alias), data_extracao=agora_iso(),
            n_registros=len(hits), arquivo=rel(destino), origem="rede",
            ano_base=f"{ano}-{mes:02d}",
            observacao=f"Consulta piloto para validar layout do documento ({alias}).",
        )
    )

    if not hits:
        raise ErroDeFonte(
            f"O piloto em {alias} {ano}-{mes:02d} voltou vazio. Antes de seguir, "
            "confira a chave, o alias e o intervalo — serie vazia nao vira zero."
        )

    campos = sorted({k for h in hits for k in (h.get("_source") or {})})
    log.info("Campos presentes no _source: %s", campos)
    df = deduplicar(achatar(hits, alias))
    log.info("PILOTO: %d hits -> %d processos distintos", len(hits), len(df))
    return df


# --------------------------------------------------------------------------
# Coleta completa
# --------------------------------------------------------------------------
def coletar(
    aliases: list[str],
    *,
    assuntos: list[int] | None,
    inicio: str,
    fim: str,
    max_paginas: int | None = None,
) -> pd.DataFrame:
    cliente = ClienteDataJud(max_paginas=max_paginas)
    query = montar_query(assuntos=assuntos, inicio=inicio, fim=fim)
    partes = []
    for alias in aliases:
        log.info("Coletando %s (%s a %s)", alias, inicio, fim)
        hits = list(cliente.buscar(alias, query))
        df = achatar(hits, alias)
        log.info("%s: %d hits", alias, len(hits))
        partes.append(df)
    if not partes:
        return pd.DataFrame()
    return deduplicar(pd.concat(partes, ignore_index=True))


def executar(refresh: bool = False, inicio: str | None = None, fim: str | None = None) -> dict:
    """Etapa completa: exige o dicionario TPU e trata os dois universos separados."""
    from . import tpu

    inicio = inicio or os.getenv("JANELA_INICIO", "2020-01-01")
    fim = fim or pd.Timestamp.today().strftime("%Y-%m-%d")
    assuntos = tpu.codigos_consumo()  # levanta ErroDeFonte se o dicionario faltar

    b2c = coletar(list(TRIBUNAIS_ESTADUAIS.values()), assuntos=assuntos, inicio=inicio, fim=fim)
    reg = coletar(list(TRIBUNAIS_FEDERAIS.values()), assuntos=assuntos, inicio=inicio, fim=fim)

    ressalva = (
        "A API publica do DataJud NAO expoe as partes: e impossivel atribuir "
        "processos a uma empresa por esta fonte. Contagem por numeroProcesso "
        "distinto. Universos B2C (estadual) e regulatorio (federal) mantidos "
        "separados e jamais somados."
    )
    periodo = f"{inicio} a {fim}"
    salvos = {}
    for nome, df, universo in (
        ("datajud_b2c", b2c, UNIVERSO_B2C),
        ("datajud_regulatorio", reg, UNIVERSO_REGULATORIO),
    ):
        if df.empty:
            raise ErroDeFonte(
                f"Coleta de {universo} voltou vazia para {periodo}. "
                "Serie vazia nao e serie zerada — investigue antes de publicar."
            )
        salvos[nome] = salvar_parquet(
            df.drop(columns=["assuntos_codigos", "assuntos_nomes"], errors="ignore"),
            nome, fonte=FONTE, url=BASE_URL.format(alias="{alias}"),
            ano_base=periodo, observacao=f"{universo}. {ressalva}",
        )[1]
        salvos[f"{nome}_serie"] = salvar_parquet(
            serie_mensal(df), f"{nome}_serie_mensal", fonte=FONTE,
            url=BASE_URL.format(alias="{alias}"), ano_base=periodo,
            observacao=f"Casos novos por mes, {universo}. {ressalva}",
            derivado_de=[f"data/clean/{nome}.parquet"],
        )[1]
    salvos["datajud_b2c_assunto"] = salvar_parquet(
        por_assunto(b2c), "datajud_b2c_por_assunto", fonte=FONTE,
        url=BASE_URL.format(alias="{alias}"), ano_base=periodo,
        observacao="Linhas NAO somam ao total: um processo com N assuntos aparece "
                   "N vezes. Para totais use a serie mensal. " + ressalva,
        derivado_de=["data/clean/datajud_b2c.parquet"],
    )[1]
    participacao = serie_participacao(list(TRIBUNAIS_ESTADUAIS.values()), assuntos, inicio, fim)
    if not participacao.empty:
        salvos["datajud_participacao"] = salvar_parquet(
            participacao, "datajud_participacao_consumo", fonte=FONTE,
            url=BASE_URL.format(alias="{alias}"), ano_base=periodo,
            observacao="Participacao do consumo no total de casos novos. Numerador e "
                       "denominador contam DOCUMENTOS no mesmo grau (G1), nao processos "
                       "deduplicados — so assim a razao e comparavel. " + ressalva,
        )[1]
    salvos["datajud_b2c_orgao"] = salvar_parquet(
        por_orgao(b2c), "datajud_b2c_por_orgao", fonte=FONTE,
        url=BASE_URL.format(alias="{alias}"), ano_base=periodo,
        observacao="Concentracao por orgao julgador: sinal indireto de litigancia "
                   "de massa, nunca prova. " + ressalva,
        derivado_de=["data/clean/datajud_b2c.parquet"],
    )[1]
    return salvos


def main() -> int:
    ap = argparse.ArgumentParser(description="Fonte 1: DataJud / API Publica do CNJ")
    ap.add_argument("--piloto", action="store_true", help="consulta pequena para inspecao")
    ap.add_argument("--alias", default="tjsp")
    ap.add_argument("--ano", type=int, default=2024)
    ap.add_argument("--mes", type=int, default=1)
    ap.add_argument("--limite", type=int, default=200)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    try:
        if args.piloto:
            df = piloto(args.alias, args.ano, args.mes, args.limite)
            pd.set_option("display.max_columns", None, "display.width", 200)
            print(df.head(15).to_string(index=False))
        else:
            executar(refresh=args.refresh)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
