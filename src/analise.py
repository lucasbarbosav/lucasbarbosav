"""Metricas derivadas: normalizacao e sinais de litigancia de massa.

Nada aqui baixa dado. Sao funcoes puras sobre os Parquets ja tratados, para
poderem ser testadas isoladamente.

SOBRE OS "SINAIS DE LITIGANCIA DE MASSA"
---------------------------------------
A API publica do DataJud nao expoe partes nem pecas processuais. Logo, e
**impossivel** medir similaridade textual, repeticao de peticoes ou identidade
de autor/advogado. O que este modulo calcula sao *sinais indiretos*:

  1. concentracao de processos por orgao julgador (HHI e share do topo);
  2. razao entre acoes judiciais e reclamacoes pre-judiciais (propensao a
     judicializar);
  3. picos anomalos na serie temporal, por z-score robusto (MAD).

Sinal nao e prova. Concentracao alta pode indicar litigancia predatoria **ou**
simplesmente uma empresa grande, com muitos clientes e servico ruim, num foro
onde ela opera. Toda funcao aqui devolve os numeros junto com a ressalva, e os
graficos imprimem a ressalva.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import configurar_log

log = configurar_log("analise")

RESSALVA_SINAL = (
    "Sinal indireto, nao prova de litigancia predatoria: o DataJud nao expoe "
    "partes nem pecas, entao repeticao/similaridade nao e mensuravel. "
    "Concentracao alta tambem e compativel com empresa grande e servico ruim."
)


# --------------------------------------------------------------------------
# Normalizacao por 100 mil passageiros
# --------------------------------------------------------------------------
def por_100k(
    metrica: pd.DataFrame,
    demanda: pd.DataFrame,
    *,
    coluna_valor: str,
    chaves: tuple[str, ...] = ("ano",),
    nome_saida: str = "por_100k_passageiros",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normaliza `coluna_valor` pelo total de passageiros das mesmas `chaves`.

    Devolve `(casadas, nao_casadas)`. As linhas sem denominador **nao viram
    zero nem somem em silencio**: saem no segundo quadro para inspecao. Um
    denominador ausente tratado como zero produziria taxa infinita; tratado
    como um produziria taxa absurda. Ambos ja apareceram em relatorio publicado.
    """
    faltando = [c for c in chaves if c not in metrica.columns or c not in demanda.columns]
    if faltando:
        raise KeyError(f"chaves ausentes em um dos quadros: {faltando}")

    den = (
        demanda.groupby(list(chaves), dropna=False)["passageiros"]
        .sum()
        .reset_index()
        .rename(columns={"passageiros": "passageiros_denominador"})
    )
    juntos = metrica.merge(den, on=list(chaves), how="left")
    sem_den = juntos["passageiros_denominador"].isna() | (juntos["passageiros_denominador"] <= 0)

    nao_casadas = juntos[sem_den].copy()
    casadas = juntos[~sem_den].copy()
    casadas[nome_saida] = casadas[coluna_valor] / casadas["passageiros_denominador"] * 100_000

    if len(nao_casadas):
        log.warning(
            "%d de %d linhas ficaram sem denominador de passageiros e foram "
            "separadas (nao zeradas). Chaves: %s",
            len(nao_casadas), len(juntos), list(chaves),
        )
    return casadas, nao_casadas


# --------------------------------------------------------------------------
# Concentracao
# --------------------------------------------------------------------------
def hhi(valores: pd.Series) -> float:
    """Indice Herfindahl-Hirschman em [0, 1]. 1 = tudo num ator so."""
    v = pd.to_numeric(valores, errors="coerce").dropna()
    v = v[v > 0]
    total = v.sum()
    if total <= 0:
        return float("nan")
    return float(((v / total) ** 2).sum())


def concentracao(
    df: pd.DataFrame, *, grupo: str, valor: str, por: tuple[str, ...] = ("ano",), topo: int = 5
) -> pd.DataFrame:
    """HHI e share do topo-N por periodo. Insumo do sinal 1."""
    linhas = []
    for chave, bloco in df.groupby(list(por), dropna=False):
        agr = bloco.groupby(grupo, dropna=False)[valor].sum().sort_values(ascending=False)
        total = agr.sum()
        if total <= 0:
            continue
        registro = dict(zip(por, chave if isinstance(chave, tuple) else (chave,)))
        registro.update({
            "n_atores": int((agr > 0).sum()),
            "total": float(total),
            "hhi": hhi(agr),
            f"share_top{topo}": float(agr.head(topo).sum() / total),
            "lider": agr.index[0] if len(agr) else None,
            "share_lider": float(agr.iloc[0] / total) if len(agr) else float("nan"),
            "ressalva": RESSALVA_SINAL,
        })
        linhas.append(registro)
    return pd.DataFrame(linhas).sort_values(list(por)) if linhas else pd.DataFrame()


# --------------------------------------------------------------------------
# Propensao a judicializar
# --------------------------------------------------------------------------
def razao_judicial_reclamacao(
    judicial: pd.DataFrame,
    reclamacoes: pd.DataFrame,
    *,
    chaves: tuple[str, ...] = ("ano", "uf"),
    col_judicial: str = "processos",
    col_reclamacao: str = "reclamacoes",
) -> pd.DataFrame:
    """Acoes judiciais por reclamacao pre-judicial.

    RESSALVA: os dois universos nao sao comparaveis linha a linha — o
    consumidor.gov.br so cobre empresas aderentes, e nem toda acao judicial
    passa por reclamacao previa. A razao mede *propensao relativa* entre
    recortes, nunca a probabilidade de um caso virar processo.
    """
    j = judicial.groupby(list(chaves), dropna=False)[col_judicial].sum().reset_index()
    r = reclamacoes.groupby(list(chaves), dropna=False)[col_reclamacao].sum().reset_index()
    out = j.merge(r, on=list(chaves), how="outer")
    out["razao_acoes_por_reclamacao"] = np.where(
        out[col_reclamacao].fillna(0) > 0,
        out[col_judicial] / out[col_reclamacao],
        np.nan,  # sem reclamacao nao existe razao; nao e infinito, e indefinido
    )
    out["ressalva"] = (
        "Universos distintos: consumidor.gov.br cobre so empresas aderentes e "
        "nem toda acao passa por reclamacao previa. Mede propensao relativa "
        "entre recortes, nao probabilidade de judicializacao."
    )
    return out.sort_values(list(chaves))


# --------------------------------------------------------------------------
# Picos anomalos
# --------------------------------------------------------------------------
def picos_anomalos(
    serie: pd.DataFrame, *, valor: str, por: tuple[str, ...] = (), limiar: float = 3.5
) -> pd.DataFrame:
    """Marca outliers por z-score robusto (mediana + MAD).

    Usamos MAD e nao desvio-padrao porque um unico surto de acoes contamina a
    media e o desvio, escondendo justamente o surto que se quer detectar.
    """
    df = serie.copy()
    v = pd.to_numeric(df[valor], errors="coerce")

    if por:
        chaves = [df[c] for c in por]
        mediana = v.groupby(chaves).transform("median")
        desvios = (v - mediana).abs()
        mad = desvios.groupby(chaves).transform("median")
        desvio_medio = desvios.groupby(chaves).transform("mean")
    else:
        mediana = pd.Series(v.median(), index=v.index)
        desvios = (v - mediana).abs()
        mad = pd.Series(desvios.median(), index=v.index)
        desvio_medio = pd.Series(desvios.mean(), index=v.index)

    z = pd.Series(np.nan, index=v.index, dtype="float64")
    # 0.6745: torna o MAD comparavel ao desvio-padrao numa normal.
    com_mad = mad > 0
    z[com_mad] = 0.6745 * (v - mediana)[com_mad] / mad[com_mad]
    # MAD zera quando mais da metade dos pontos e identica — exatamente o caso
    # "serie plana com um surto", em que o surto se esconderia. Cai para o
    # desvio absoluto medio (1.2533: mesmo ajuste de escala).
    com_dm = ~com_mad & (desvio_medio > 0)
    z[com_dm] = (v - mediana)[com_dm] / (1.2533 * desvio_medio[com_dm])
    # Sem variacao nenhuma nao ha pico a declarar.
    z[~com_mad & ~com_dm] = 0.0

    df["z_robusto"] = z
    df["pico"] = z > limiar
    df["ressalva"] = RESSALVA_SINAL
    n = int(df["pico"].fillna(False).sum())
    if n:
        log.info("%d ponto(s) marcado(s) como pico anomalo (z robusto > %.1f)", n, limiar)
    return df
