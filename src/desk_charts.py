"""Painéis do censo de entrega da informação (mesma identidade visual da série).

Reusa a paleta validada e as regras de `charts.py`: rodapé de proveniência
obrigatório, nunca dois eixos y, rótulo direto como alívio de contraste,
gráfico sem dado é pulado com aviso.

Cores por estado — fixas, seguem a entidade em todos os painéis (paleta da
série reordenada e revalidada para daltonismo nesta ordem de adjacência):

  entregue_no_desk      verde  #1baf7a
  entregue_fora_do_desk âmbar  #eda100
  indeterminado         azul   #2a78d6  (o piso de incerteza, nunca diluído)
  nao_entregue          laranja #eb6834

Além dos PNGs, `executar()` grava `output/desk/resumo.md` com a tabela por
estado/área/assunto e trechos-evidência por classe (contém texto de tickets:
NÃO versionar; `output/` fica fora do git).
"""
from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from ._common import RAIZ, ErroDeFonte, carregar_parquet, configurar_log, rel  # noqa: E402
from .charts import GRADE, SUPERFICIE, TINTA, TINTA_2, _figura, _rodape, _salvar  # noqa: E402
from .desk_entrega import RESSALVA_PISO  # noqa: E402

log = configurar_log("desk_charts")

OUT_DESK = RAIZ / "output" / "desk"

ESTADOS = ["entregue_no_desk", "entregue_fora_do_desk", "indeterminado", "nao_entregue"]
COR = {
    "entregue_no_desk": "#1baf7a",
    "entregue_fora_do_desk": "#eda100",
    "indeterminado": "#2a78d6",
    "nao_entregue": "#eb6834",
}
ROTULO = {
    "entregue_no_desk": "Entregue no Desk",
    "entregue_fora_do_desk": "Entregue fora do Desk",
    "indeterminado": "Indeterminado",
    "nao_entregue": "Não entregue",
}


def _carregar():
    df, meta = carregar_parquet("desk_entrega_classificada")
    if df.empty:
        raise ErroDeFonte("`desk_entrega_classificada` está vazio.")
    return df, meta


def _shares(df: pd.DataFrame, por: str, topo: int | None = None) -> pd.DataFrame:
    """% de cada estado por grupo, com o `n` do grupo. Ordena por volume."""
    tab = df.groupby([por, "estado"]).size().unstack(fill_value=0)
    for e in ESTADOS:
        if e not in tab.columns:
            tab[e] = 0
    tab = tab[ESTADOS]
    tab["n"] = tab.sum(axis=1)
    tab = tab.sort_values("n", ascending=False)
    if topo and len(tab) > topo:
        resto = tab.iloc[topo:].sum()
        tab = tab.iloc[:topo]
        tab.loc["(demais)"] = resto
    for e in ESTADOS:
        tab[e] = tab[e] / tab["n"]
    return tab


def _margem_esquerda(ax, nomes: list[str]) -> None:
    """Reserva margem para o rótulo mais longo — sem isso o nome corta na borda."""
    maior = max((len(n) for n in nomes), default=10)
    ax.figure.subplots_adjust(left=min(0.34, 0.06 + 0.0105 * maior))


def _barras_empilhadas(ax, tab: pd.DataFrame) -> None:
    """Empilhado horizontal com vão de superfície entre segmentos e rótulo
    direto nos segmentos ≥ 5% (o alívio exigido pelo contraste da paleta)."""
    nomes = [str(i) if len(str(i)) <= 28 else str(i)[:27] + "…" for i in tab.index][::-1]
    y = np.arange(len(tab))
    esquerda = np.zeros(len(tab))
    for e in ESTADOS:
        vals = tab[e].to_numpy()[::-1]
        ax.barh(y, vals, left=esquerda, color=COR[e], height=0.72,
                edgecolor=SUPERFICIE, linewidth=1.5, label=ROTULO[e])
        for yi, (v, x0) in enumerate(zip(vals, esquerda)):
            if v >= 0.05:
                ax.text(x0 + v / 2, yi, f"{v:.0%}", ha="center", va="center",
                        fontsize=8.5, color=SUPERFICIE if e != "entregue_fora_do_desk" else TINTA)
        esquerda += vals
    ax.set_yticks(y, nomes)
    _margem_esquerda(ax, nomes)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1.0, 1.0),
              ncols=2, fontsize=9, labelcolor=TINTA_2)


# --------------------------------------------------------------------------
# Painéis
# --------------------------------------------------------------------------
def entrega_geral() -> str:
    df, meta = _carregar()
    freq = df["estado"].value_counts()
    fig, ax = _figura(
        "A informação pedida à área voltou?",
        f"Censo de {len(df):,} tickets com pendência interna (cf_area_pi preenchido)".replace(",", "."),
    )
    vals = [freq.get(e, 0) / len(df) for e in ESTADOS][::-1]
    nomes = [ROTULO[e] for e in ESTADOS][::-1]
    cores = [COR[e] for e in ESTADOS][::-1]
    ax.barh(nomes, vals, color=cores, height=0.62)
    _margem_esquerda(ax, nomes)
    for i, (v, e) in enumerate(zip(vals, ESTADOS[::-1])):
        ax.text(v + 0.008, i, f"{v:.1%}  (n={freq.get(e, 0):,})".replace(",", "."),
                va="center", fontsize=10, color=TINTA)
    ax.set_xlim(0, max(vals) * 1.28)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    _rodape(fig, meta, RESSALVA_PISO)
    return _salvar(fig, "10_desk_entrega_estados")


def entrega_por_area() -> str:
    df, meta = _carregar()
    tab = _shares(df, "area", topo=6)
    fig, ax = _figura("Entrega da informação por área acionada",
                      "Share de cada estado; áreas por volume",
                      tamanho=(11, 7))
    _barras_empilhadas(ax, tab)
    _rodape(fig, meta, "Rótulo à esquerda = área do cf_area_pi; n varia por área "
                       "(ver output/desk/resumo.md).")
    return _salvar(fig, "11_desk_entrega_por_area")


def entrega_por_assunto() -> str:
    df, meta = _carregar()
    tab = _shares(df, "assunto", topo=10)
    fig, ax = _figura("Entrega da informação por assunto",
                      "Top-10 assuntos por volume",
                      tamanho=(11, 7.5))
    _barras_empilhadas(ax, tab)
    _rodape(fig, meta, "Assunto = detalhe do motivo quando preenchido, senão o motivo. "
                       + RESSALVA_PISO)
    return _salvar(fig, "12_desk_entrega_por_assunto")


def latencia_por_area() -> str:
    df, meta = _carregar()
    com_lat = df.dropna(subset=["latencia_area_h"])
    if com_lat.empty:
        raise ErroDeFonte("Nenhum ticket com latência de resposta medida.")
    agr = (
        com_lat.groupby("area")["latencia_area_h"]
        .agg(mediana="median", p90=lambda s: s.quantile(0.9), n="size")
        .sort_values("n", ascending=False)
        .head(6)
    )
    fig, ax = _figura(
        "Quanto tempo a área leva para responder",
        "Horas entre o disparo e o retorno da área (só casos rastreáveis)",
    )
    y = np.arange(len(agr))
    ax.barh(y + 0.19, agr["mediana"][::-1], height=0.34, color="#1baf7a", label="mediana")
    ax.barh(y - 0.19, agr["p90"][::-1], height=0.34, color="#2a78d6", label="p90")
    maximo = float(agr["p90"].max())
    ax.set_xlim(0, maximo * 1.12)
    for yi, (med, p90) in enumerate(zip(agr["mediana"][::-1], agr["p90"][::-1])):
        ax.text(med + maximo * 0.012, yi + 0.19, f"{med:.0f}h", va="center", fontsize=9, color=TINTA)
        ax.text(p90 + maximo * 0.012, yi - 0.19, f"{p90:.0f}h", va="center", fontsize=9, color=TINTA)
    ax.set_yticks(y, list(agr.index)[::-1])
    _margem_esquerda(ax, [str(i) for i in agr.index])
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.set_xlabel("horas")
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncols=2,
              fontsize=9, labelcolor=TINTA_2)
    _rodape(fig, meta, "Latência só existe onde há disparo e retorno registrados no Desk — "
                       "o que foi entregue fora do Desk não tem tempo mensurável.")
    return _salvar(fig, "13_desk_latencia_por_area")


def caixa_preta() -> str:
    df, meta = _carregar()
    tab = _shares(df, "area", topo=6)
    fora = tab["entregue_fora_do_desk"] + tab["indeterminado"]
    fig, ax = _figura(
        "O tamanho da caixa-preta, por área",
        "Share de pendências cuja resposta não está registrada no Desk "
        "(entregue fora do Desk + indeterminado)",
    )
    ax.barh(list(fora.index)[::-1], fora[::-1], color="#2a78d6", height=0.62)
    _margem_esquerda(ax, [str(i) for i in fora.index])
    for i, v in enumerate(fora[::-1]):
        ax.text(v + 0.008, i, f"{v:.0%}", va="center", fontsize=10, color=TINTA)
    ax.set_xlim(0, min(1.0, float(fora.max()) * 1.25))
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    _rodape(fig, meta, RESSALVA_PISO)
    return _salvar(fig, "14_desk_caixa_preta")


# --------------------------------------------------------------------------
# Tabela + trechos-evidência
# --------------------------------------------------------------------------
def _tabela_md(tab: pd.DataFrame, titulo: str) -> str:
    linhas = [f"### {titulo}\n", "| grupo | n | " + " | ".join(ROTULO[e] for e in ESTADOS) + " |",
              "|---|---:|" + "---:|" * len(ESTADOS)]
    for grupo, r in tab.iterrows():
        linhas.append(
            f"| {grupo} | {int(r['n'])} | "
            + " | ".join(f"{r[e]:.1%}" for e in ESTADOS) + " |"
        )
    return "\n".join(linhas) + "\n"


def gerar_resumo() -> str:
    df, meta = _carregar()
    OUT_DESK.mkdir(parents=True, exist_ok=True)
    destino = OUT_DESK / "resumo.md"
    freq = df["estado"].value_counts()
    partes = [
        "# Taxa de entrega da informação — SAC ⇄ áreas internas\n",
        f"_{meta.rodape() if meta else ''}_\n",
        f"**Censo**: {len(df)} tickets com pendência interna. "
        f"{RESSALVA_PISO}\n",
        "## Total por estado\n",
        "| estado | n | % |", "|---|---:|---:|",
    ]
    for e in ESTADOS:
        n = int(freq.get(e, 0))
        partes.append(f"| {ROTULO[e]} | {n} | {n / len(df):.1%} |")
    extras = []
    if "retorno_cliente_falhou" in df.columns:
        n_bounce = int(df["retorno_cliente_falhou"].sum())
        extras.append(f"- Retorno ao cliente falhou (bounce) em **{n_bounce}** tickets.")
    n_sem_disparo = int((~df["disparo_no_desk"]).sum())
    extras.append(
        f"- Em **{n_sem_disparo}** tickets a pendência foi marcada (cf_area_pi) mas "
        "nunca disparada de forma rastreável no Desk."
    )
    n_llm = int(df["precisa_llm"].sum())
    if n_llm:
        extras.append(
            f"- **{n_llm}** casos ambíguos aguardam a passada de LLM "
            "(`python -m src.desk_entrega --llm`); até lá contam como indeterminado."
        )
    partes.append("\n" + "\n".join(extras) + "\n")
    partes.append(_tabela_md(_shares(df, "area", topo=8), "Por área acionada"))
    partes.append(_tabela_md(_shares(df, "assunto", topo=12), "Por assunto"))

    partes.append("## Trechos-evidência por classe\n")
    partes.append("_Texto real de tickets — uso interno; este arquivo não é versionado._\n")
    for e in ESTADOS:
        bloco = df[(df["estado"] == e) & (df["evidencia"].astype(str).str.len() > 0)]
        partes.append(f"### {ROTULO[e]}\n")
        if bloco.empty:
            partes.append("(sem trecho de evidência — classe definida por ausência de retorno)\n")
            continue
        for _, r in bloco.head(5).iterrows():
            partes.append(f"- `#{r['ticket_numero']}` ({r['area']} · {r['assunto']}): "
                          f"“{str(r['evidencia'])[:220]}”")
        partes.append("")
    destino.write_text("\n".join(partes), encoding="utf-8")
    log.info("Resumo gravado: %s", rel(destino))
    return rel(destino)


PAINEIS = [entrega_geral, entrega_por_area, entrega_por_assunto, latencia_por_area, caixa_preta]


def executar(refresh: bool = False) -> dict:
    feitos, pulados = [], []
    for fn in PAINEIS:
        try:
            feitos.append(fn())
        except ErroDeFonte as exc:
            pulados.append((fn.__name__, str(exc).split(".")[0]))
            log.warning("PULADO %s — %s", fn.__name__, str(exc).split(".")[0])
    try:
        feitos.append(gerar_resumo())
    except ErroDeFonte as exc:
        pulados.append(("gerar_resumo", str(exc).split(".")[0]))
    if not feitos:
        raise ErroDeFonte(
            "Nenhum painel do censo pôde ser gerado: rode `desk_ingestao` e "
            "`desk_entrega` antes."
        )
    log.info("%d painel(is) gerado(s), %d pulado(s)", len(feitos), len(pulados))
    return {"feitos": feitos, "pulados": pulados}


if __name__ == "__main__":
    try:
        executar()
    except ErroDeFonte as exc:
        log.error("%s", exc)
        sys.exit(1)
