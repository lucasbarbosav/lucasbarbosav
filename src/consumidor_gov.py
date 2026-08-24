"""Fonte 2 — consumidor.gov.br (Senacon/MJ): recorte B2C por empresa.

Esta e a unica fonte deste pipeline que traz **nome de empresa**. O DataJud nao
expoe as partes de forma consultavel, entao toda analise por empresa nasce aqui.

Universo: reclamacoes B2C registradas na plataforma consumidor.gov.br. Nao e
processo judicial — e a etapa pre-judicial. Serve para (a) dimensionar o
conflito de consumo no transporte terrestre, (b) dar o denominador de
"reclamacao" na razao acoes/reclamacoes usada como sinal de litigancia de massa.

Recortes produzidos:
  - Transporte Terrestre  -> objeto do estudo (rodoviario de passageiros)
  - Transporte Aereo      -> benchmark comparativo (setor com regulacao de CX
                             madura e serie longa de reclamacoes)
Os dois NUNCA sao somados; ficam em colunas/arquivos distintos.
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd

from ._common import (
    DATA_RAW,
    DOCS,
    ErroDeFonte,
    Limitador,
    baixar,
    configurar_log,
    post_json,
    salvar_parquet,
    sessao,
)

log = configurar_log("consumidor_gov")

FONTE = "consumidor.gov.br — microdados abertos (Senacon/MJ)"
CKAN_BASE = "https://dados.mj.gov.br"
PACOTE = "reclamacoes-do-consumidor-gov-br"
CKAN_PACKAGE_SHOW = f"{CKAN_BASE}/api/3/action/package_show?id={PACOTE}"
PAGINA_DATASET = f"{CKAN_BASE}/dataset/{PACOTE}"

BRUTO = DATA_RAW / "consumidor_gov"

# Segmentos de interesse, em forma normalizada (sem acento, minusculo).
SEG_TERRESTRE = "transporte terrestre"
SEG_AEREO = "transporte aereo"

# Colunas que o pipeline precisa. Chave = nome canonico usado daqui pra frente;
# valor = nomes normalizados aceitos no CSV de origem (a Senacon ja mudou
# rotulos entre safras, entao aceitamos sinonimos e falhamos alto se sumirem).
MAPA_COLUNAS: dict[str, tuple[str, ...]] = {
    "uf": ("uf",),
    "regiao": ("regiao",),
    "cidade": ("cidade",),
    "ano_abertura": ("ano abertura", "ano de abertura"),
    "mes_abertura": ("mes abertura", "mes de abertura"),
    "data_abertura": ("data abertura", "data de abertura"),
    "data_finalizacao": ("data finalizacao", "data de finalizacao"),
    "empresa": ("nome fantasia", "empresa", "fornecedor"),
    "segmento": ("segmento de mercado", "segmento"),
    "area": ("area",),
    "assunto": ("assunto",),
    "grupo_problema": ("grupo problema", "grupo do problema"),
    "problema": ("problema",),
    "respondida": ("respondida",),
    "situacao": ("situacao",),
    "avaliacao": ("avaliacao reclamacao", "avaliacao da reclamacao", "avaliacao"),
    "nota_consumidor": ("nota do consumidor", "nota consumidor"),
    "tempo_resposta": ("tempo resposta", "tempo de resposta"),
    "canal_origem": ("canal de origem", "canal origem"),
    "como_contratou": ("como comprou contratou", "como comprou/contratou"),
    "procurou_empresa": ("procurou empresa",),
}

# Sem estas o recorte do estudo nao existe; o pipeline para.
OBRIGATORIAS = ("empresa", "segmento", "ano_abertura", "uf")


def normalizar(texto: object) -> str:
    """Minusculo, sem acento, espacos colapsados. Base de toda comparacao."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------
# Descoberta dos arquivos via CKAN
# --------------------------------------------------------------------------
_RE_PERIODO = re.compile(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])")
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
    "dezembro": 12,
}


def _periodo_do_nome(nome: str, url: str) -> tuple[int, int] | None:
    """Extrai (ano, mes) de nomes como 'basecompleta2025-08.csv' ou 'Agosto_2025'."""
    alvo = normalizar(f"{nome} {url}")
    m = _RE_PERIODO.search(alvo.replace("basecompleta", "basecompleta "))
    if m:
        return int(m.group(1)), int(m.group(2))
    for nome_mes, num in _MESES.items():
        if nome_mes in alvo:
            ano = re.search(r"(20\d{2})", alvo)
            if ano:
                return int(ano.group(1)), num
    return None


def descobrir_recursos(sess) -> list[dict]:
    """Lista os CSVs mensais do dataset via API CKAN do MJ.

    Preferimos a API a URLs cravadas no codigo: os UUIDs de recurso mudam a cada
    safra e uma lista fixa envelhece em silencio.
    """
    log.info("Consultando catalogo CKAN: %s", CKAN_PACKAGE_SHOW)
    try:
        payload = sess.get(CKAN_PACKAGE_SHOW, timeout=120)
        payload.raise_for_status()
        dados = payload.json()
    except Exception as exc:  # noqa: BLE001 - queremos mensagem clara, nao stack
        raise ErroDeFonte(
            f"Nao consegui ler o catalogo CKAN em {CKAN_PACKAGE_SHOW} ({exc}). "
            f"Confira o dataset em {PAGINA_DATASET} — se o portal mudou de "
            "estrutura, o pipeline precisa ser ajustado, e nao contornado."
        ) from exc

    if not dados.get("success"):
        raise ErroDeFonte(f"CKAN respondeu sem sucesso para {PACOTE}: {dados}")

    recursos = []
    for r in dados["result"].get("resources", []):
        url = r.get("url", "")
        nome = r.get("name", "")
        if normalizar(r.get("format", "")) != "csv" and not url.lower().endswith(".csv"):
            continue
        if "dicionario" in normalizar(nome):
            continue  # dicionario de dados: baixado a parte
        periodo = _periodo_do_nome(nome, url)
        if not periodo:
            log.warning("Recurso sem periodo identificavel, ignorado: %s", nome)
            continue
        ano, mes = periodo
        recursos.append({"nome": nome, "url": url, "ano": ano, "mes": mes})

    if not recursos:
        raise ErroDeFonte(
            f"O catalogo {PACOTE} nao devolveu nenhum CSV mensal reconhecivel. "
            "Verifique manualmente antes de seguir."
        )
    recursos.sort(key=lambda r: (r["ano"], r["mes"]))
    log.info(
        "Encontrados %d CSVs mensais (%04d-%02d a %04d-%02d)",
        len(recursos),
        recursos[0]["ano"], recursos[0]["mes"],
        recursos[-1]["ano"], recursos[-1]["mes"],
    )
    return recursos


# --------------------------------------------------------------------------
# Leitura e normalizacao
# --------------------------------------------------------------------------
def _ler_csv(caminho: Path) -> pd.DataFrame:
    """Le o CSV da Senacon tolerando separador e encoding variaveis entre safras."""
    ultimo_erro: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        for sep in (";", ","):
            try:
                df = pd.read_csv(
                    caminho,
                    sep=sep,
                    encoding=encoding,
                    dtype=str,
                    on_bad_lines="warn",
                    low_memory=False,
                )
            except Exception as exc:  # noqa: BLE001
                ultimo_erro = exc
                continue
            if df.shape[1] > 3:  # separador certo produz muitas colunas
                log.debug("%s lido com sep=%r encoding=%s", caminho.name, sep, encoding)
                return df
    raise ErroDeFonte(f"Nao consegui parsear {caminho} ({ultimo_erro}).")


def _renomear(df: pd.DataFrame, origem: str) -> pd.DataFrame:
    """Mapeia as colunas do CSV para os nomes canonicos do pipeline."""
    achadas = {normalizar(c): c for c in df.columns}
    renome: dict[str, str] = {}
    for canonico, sinonimos in MAPA_COLUNAS.items():
        for s in sinonimos:
            if s in achadas:
                renome[achadas[s]] = canonico
                break
    df = df.rename(columns=renome)
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise ErroDeFonte(
            f"{origem}: colunas obrigatorias ausentes {faltando}. "
            f"Colunas vistas: {sorted(achadas)[:40]}. "
            "O layout da Senacon mudou — atualize MAPA_COLUNAS em vez de adivinhar."
        )
    return df[[c for c in MAPA_COLUNAS if c in df.columns]].copy()


def _derivar(df: pd.DataFrame) -> pd.DataFrame:
    """Colunas derivadas usadas nas metricas."""
    df["segmento_norm"] = df["segmento"].map(normalizar)
    df["empresa_norm"] = df["empresa"].map(normalizar)
    df["uf"] = df["uf"].fillna("").str.strip().str.upper()

    df["ano"] = pd.to_numeric(df["ano_abertura"], errors="coerce").astype("Int64")
    if "mes_abertura" in df:
        df["mes"] = pd.to_numeric(df["mes_abertura"], errors="coerce").astype("Int64")

    if "tempo_resposta" in df:
        df["tempo_resposta_dias"] = pd.to_numeric(
            df["tempo_resposta"].str.replace(",", ".", regex=False), errors="coerce"
        )
    if "nota_consumidor" in df:
        df["nota"] = pd.to_numeric(
            df["nota_consumidor"].str.replace(",", ".", regex=False), errors="coerce"
        )
    if "avaliacao" in df:
        aval = df["avaliacao"].map(normalizar)
        # "Resolvida" / "Nao Resolvida". Vazio = consumidor nao avaliou: vira NA,
        # nunca False — contar nao-avaliada como nao-resolvida derrubaria o indice
        # de solucao de quem tem muita reclamacao sem avaliacao.
        avaliou = aval.ne("")
        df["resolvida"] = (
            ~aval.str.contains("nao", na=False)
        ).astype("boolean").where(avaliou)
    if "respondida" in df:
        df["respondida_bool"] = (
            df["respondida"].map(normalizar)
            .map({"s": True, "sim": True, "n": False, "nao": False})
            .astype("boolean")
        )
    return df


def _conferir_segmentos(df: pd.DataFrame) -> None:
    """Falha alto se o segmento do estudo nao aparece — nunca devolve vazio calado."""
    presentes = set(df["segmento_norm"].unique())
    for alvo, rotulo in ((SEG_TERRESTRE, "Transporte Terrestre"), (SEG_AEREO, "Transporte Aereo")):
        if not any(alvo in p for p in presentes):
            amostra = sorted(p for p in presentes if p)[:30]
            raise ErroDeFonte(
                f"Segmento '{rotulo}' nao encontrado nos microdados. "
                f"Segmentos presentes (amostra): {amostra}. "
                "Pare e confira a taxonomia da Senacon antes de interpretar numeros."
            )
    # Registra a taxonomia observada para auditoria posterior.
    (DOCS / "consumidor_gov_segmentos_observados.txt").write_text(
        "\n".join(sorted(p for p in presentes if p)), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Agregacoes
# --------------------------------------------------------------------------
def _agregar_empresa_ano(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["segmento_rotulo", "ano", "empresa", "uf"], dropna=False)
    out = g.agg(
        reclamacoes=("empresa", "size"),
        indice_solucao=("resolvida", "mean"),
        nota_media=("nota", "mean"),
        tempo_resposta_medio_dias=("tempo_resposta_dias", "mean"),
        avaliadas=("resolvida", "count"),
    ).reset_index()
    out["taxa_avaliacao"] = out["avaliadas"] / out["reclamacoes"]
    return out.sort_values(["segmento_rotulo", "ano", "reclamacoes"], ascending=[True, True, False])


def _agregar_problema(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["segmento_rotulo", "ano", "grupo_problema", "problema"]
    cols = [c for c in cols if c in df.columns]
    out = (
        df.groupby(cols, dropna=False)
        .agg(reclamacoes=("empresa", "size"), indice_solucao=("resolvida", "mean"))
        .reset_index()
    )
    return out.sort_values(["segmento_rotulo", "ano", "reclamacoes"], ascending=[True, True, False])


def _serie_mensal(df: pd.DataFrame) -> pd.DataFrame:
    if "mes" not in df.columns:
        return pd.DataFrame()
    out = (
        df.groupby(["segmento_rotulo", "ano", "mes", "uf"], dropna=False)
        .agg(reclamacoes=("empresa", "size"), indice_solucao=("resolvida", "mean"))
        .reset_index()
    )
    return out.sort_values(["segmento_rotulo", "ano", "mes"])


# --------------------------------------------------------------------------
# Orquestracao da fonte
# --------------------------------------------------------------------------
def executar(refresh: bool = False, ano_min: int = 2020, ano_max: int | None = None) -> dict:
    sess = sessao()
    lim = Limitador(1.0)
    recursos = descobrir_recursos(sess)
    recursos = [r for r in recursos if r["ano"] >= ano_min and (ano_max is None or r["ano"] <= ano_max)]
    if not recursos:
        raise ErroDeFonte(f"Nenhum CSV mensal no intervalo {ano_min}-{ano_max}.")

    quadros: list[pd.DataFrame] = []
    urls: list[str] = []
    for r in recursos:
        destino = BRUTO / f"basecompleta{r['ano']}-{r['mes']:02d}.csv"
        caminho, _ = baixar(
            r["url"],
            destino,
            FONTE,
            refresh=refresh,
            sess=sess,
            limitador=lim,
            ano_base=f"{r['ano']}-{r['mes']:02d}",
            observacao="Base completa mensal de reclamacoes do consumidor.gov.br.",
        )
        bruto = _ler_csv(caminho)
        log.info("%s: %d linhas brutas", destino.name, len(bruto))
        quadros.append(_renomear(bruto, destino.name))
        urls.append(r["url"])

    df = pd.concat(quadros, ignore_index=True)
    df = _derivar(df)
    _conferir_segmentos(df)

    total_geral = len(df)
    terrestre = df[df["segmento_norm"].str.contains(SEG_TERRESTRE, na=False)].copy()
    terrestre["segmento_rotulo"] = "Transporte Terrestre"
    aereo = df[df["segmento_norm"].str.contains(SEG_AEREO, na=False)].copy()
    aereo["segmento_rotulo"] = "Transporte Aereo"
    recorte = pd.concat([terrestre, aereo], ignore_index=True)

    log.info(
        "Universo: %d reclamacoes | Transporte Terrestre: %d | Transporte Aereo: %d",
        total_geral, len(terrestre), len(aereo),
    )

    periodo = f"{int(df['ano'].min())}-{int(df['ano'].max())}"
    ressalva = (
        "Reclamacoes pre-judiciais registradas na plataforma consumidor.gov.br; "
        "nao sao processos judiciais. Cobertura limitada as empresas aderentes a "
        "plataforma — ausencia de uma empresa NAO significa ausencia de conflito. "
        "Transporte Terrestre e Transporte Aereo mantidos em rotulos distintos e "
        "jamais somados."
    )

    salvos = {}
    salvos["consumidor_gov_transporte"] = salvar_parquet(
        recorte.drop(columns=["segmento_norm"], errors="ignore"),
        "consumidor_gov_transporte",
        fonte=FONTE, url=PAGINA_DATASET, ano_base=periodo,
        observacao=ressalva, derivado_de=urls,
    )[1]
    salvos["consumidor_gov_empresa_ano"] = salvar_parquet(
        _agregar_empresa_ano(recorte), "consumidor_gov_empresa_ano",
        fonte=FONTE, url=PAGINA_DATASET, ano_base=periodo,
        observacao="Agregado por segmento/ano/empresa/UF. " + ressalva,
        derivado_de=["data/clean/consumidor_gov_transporte.parquet"],
    )[1]
    salvos["consumidor_gov_problema_ano"] = salvar_parquet(
        _agregar_problema(recorte), "consumidor_gov_problema_ano",
        fonte=FONTE, url=PAGINA_DATASET, ano_base=periodo,
        observacao="Agregado por segmento/ano/grupo de problema. " + ressalva,
        derivado_de=["data/clean/consumidor_gov_transporte.parquet"],
    )[1]
    serie = _serie_mensal(recorte)
    if not serie.empty:
        salvos["consumidor_gov_serie_mensal"] = salvar_parquet(
            serie, "consumidor_gov_serie_mensal",
            fonte=FONTE, url=PAGINA_DATASET, ano_base=periodo,
            observacao="Serie mensal por segmento/UF. " + ressalva,
            derivado_de=["data/clean/consumidor_gov_transporte.parquet"],
        )[1]

    # Totais de todos os segmentos: denominador para "participacao do transporte".
    totais = (
        df.groupby(["ano", "segmento"], dropna=False)
        .size().reset_index(name="reclamacoes")
        .sort_values(["ano", "reclamacoes"], ascending=[True, False])
    )
    salvos["consumidor_gov_total_segmentos"] = salvar_parquet(
        totais, "consumidor_gov_total_segmentos",
        fonte=FONTE, url=PAGINA_DATASET, ano_base=periodo,
        observacao="Todos os segmentos, para calcular a participacao do transporte. " + ressalva,
        derivado_de=urls,
    )[1]
    return salvos


def main() -> None:
    ap = argparse.ArgumentParser(description="Fonte 2: microdados do consumidor.gov.br")
    ap.add_argument("--refresh", action="store_true", help="rebaixa arquivos ja em cache")
    ap.add_argument("--ano-min", type=int, default=2020)
    ap.add_argument("--ano-max", type=int, default=None)
    args = ap.parse_args()
    executar(refresh=args.refresh, ano_min=args.ano_min, ano_max=args.ano_max)


if __name__ == "__main__":
    main()
