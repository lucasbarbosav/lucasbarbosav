"""Graficos estaticos em `output/charts/`.

Regras aplicadas em todos:
- **Rodape de proveniencia obrigatorio**: fonte, ano-base e data de extracao,
  lidos do `.meta.json` do Parquet — nunca digitados a mao.
- **Nunca dois eixos y.** Medidas de escalas diferentes viram graficos separados.
- Cores categoricas em ordem fixa (paleta validada para daltonismo em modo claro
  e escuro); series rotuladas diretamente, porque tres slots ficam abaixo de 3:1
  de contraste no fundo claro e o rotulo e o alivio exigido.
- Um grafico cujo dado nao existe e **pulado com aviso**, nunca desenhado vazio.
"""
from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from ._common import CHARTS, ErroDeFonte, carregar_parquet, configurar_log, rel  # noqa: E402

log = configurar_log("charts")

# Paleta categorica validada (slots 1-4, modo claro).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRADE = "#e5e4e0"

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE, "font.size": 11,
    "axes.edgecolor": GRADE, "axes.labelcolor": TINTA_2,
    "xtick.color": TINTA_2, "ytick.color": TINTA_2,
    "axes.spines.top": False, "axes.spines.right": False,
})

_MILHAR = FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", "."))


def _figura(titulo: str, subtitulo: str = "", tamanho=(11, 6)):
    fig, ax = plt.subplots(figsize=tamanho)
    fig.suptitle(titulo, x=0.02, y=0.97, ha="left", fontsize=15, color=TINTA, weight="bold")
    if subtitulo:
        ax.set_title(subtitulo, loc="left", fontsize=11, color=TINTA_2, pad=14)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _rodape(fig, metas, extra: str = "") -> None:
    """Proveniencia + ressalva. Sem isso o grafico nao sai daqui."""
    partes = []
    for m in metas if isinstance(metas, (list, tuple)) else [metas]:
        if m is not None:
            partes.append(m.rodape())
    texto = " • ".join(dict.fromkeys(partes))
    if extra:
        texto += f"\n{extra}"
    fig.text(0.02, 0.015, texto, fontsize=8, color=TINTA_2, va="bottom", ha="left", wrap=True)
    fig.subplots_adjust(bottom=0.22 if extra else 0.16, top=0.85)


def _salvar(fig, nome: str) -> str:
    destino = CHARTS / f"{nome}.png"
    fig.savefig(destino, dpi=160)
    plt.close(fig)
    log.info("Grafico gravado: %s", rel(destino))
    return rel(destino)


def _rotular_linhas(ax, series: dict[str, tuple], gap_min: float = 0.05) -> None:
    """Rotulo direto no fim de cada linha — alivio para os slots de baixo contraste.

    Duas correcoes que o olho pega e o teste automatico nao: series que terminam
    no mesmo valor teriam os rotulos empilhados um sobre o outro, e nomes longos
    transbordavam a borda direita da figura. Aqui os rotulos sao empurrados para
    manter um vao minimo, e a margem direita e reservada conforme o nome mais
    longo.
    """
    pontos = [(nome, x[-1], y[-1]) for nome, (x, y) in series.items() if len(x)]
    if not pontos:
        return
    pontos.sort(key=lambda p: p[2])

    y0, y1 = ax.get_ylim()
    span = (y1 - y0) or 1.0
    fracs = [(p[2] - y0) / span for p in pontos]
    # empurra para cima quem estiver perto demais do rotulo de baixo
    for i in range(1, len(fracs)):
        fracs[i] = max(fracs[i], fracs[i - 1] + gap_min)
    excesso = fracs[-1] - 1.0
    if excesso > 0:  # estourou o topo: desce o conjunto inteiro
        fracs = [f - excesso for f in fracs]

    rotulos = [(n if len(n) <= 22 else n[:21] + "…", x, y) for n, x, y in pontos]
    for (nome, _, _), f in zip(rotulos, fracs):
        ax.annotate(nome, xy=(1.015, f), xycoords="axes fraction", va="center",
                    ha="left", fontsize=9, color=TINTA, annotation_clip=False)

    maior = max(len(n) for n, _, _ in rotulos)
    ax.figure.subplots_adjust(right=max(0.60, 0.97 - 0.0135 * maior))


# --------------------------------------------------------------------------
# Graficos
# --------------------------------------------------------------------------
def serie_nacional_consumo() -> str:
    df, meta = carregar_parquet("datajud_b2c_serie_mensal")
    df = df.dropna(subset=["ano"])
    fig, ax = _figura(
        "Casos novos de consumo na Justica Estadual",
        "Processos distintos por ano (contagem por numeroProcesso, nao por assunto)",
    )
    nacional = df.groupby("ano")["processos"].sum()
    ax.plot(nacional.index, nacional.values, linewidth=2.5, color=SERIES[0], zorder=3)
    ax.scatter(nacional.index, nacional.values, s=36, color=SERIES[0], zorder=4,
               edgecolor=SUPERFICIE, linewidth=2)
    ax.set_ylabel("processos distintos")
    ax.yaxis.set_major_formatter(_MILHAR)
    ax.set_xlabel("")
    _rodape(fig, meta, "Soma das UFs prioritarias (SP, RJ, MG, CE) — nao e o total do pais.")
    return _salvar(fig, "01_serie_nacional_consumo")


def serie_por_uf() -> str:
    df, meta = carregar_parquet("datajud_b2c_serie_mensal")
    df = df.dropna(subset=["ano", "uf"])
    fig, ax = _figura("Casos novos de consumo por UF", "Processos distintos por ano")
    series = {}
    for i, (uf, bloco) in enumerate(sorted(df.groupby("uf"))):
        s = bloco.groupby("ano")["processos"].sum()
        ax.plot(s.index, s.values, linewidth=2, color=SERIES[i % len(SERIES)], label=uf)
        series[uf] = (list(s.index), list(s.values))
    _rotular_linhas(ax, series)
    ax.legend(frameon=False, loc="upper left", ncols=4, fontsize=9, labelcolor=TINTA_2)
    ax.set_ylabel("processos distintos")
    ax.yaxis.set_major_formatter(_MILHAR)
    _rodape(fig, meta)
    return _salvar(fig, "02_serie_consumo_por_uf")


def participacao_consumo() -> str:
    df, meta = carregar_parquet("datajud_participacao_consumo")
    fig, ax = _figura(
        "Participacao do consumo no total de casos novos",
        "Documentos processuais em 1o grau: numerador e denominador medidos igual",
    )
    series = {}
    for i, (uf, bloco) in enumerate(sorted(df.groupby("uf"))):
        s = bloco.groupby("ano").apply(
            lambda b: b["documentos_consumo"].sum() / b["documentos_total"].sum(),
            include_groups=False,
        )
        ax.plot(s.index, s.values, linewidth=2, color=SERIES[i % len(SERIES)], label=uf)
        series[uf] = (list(s.index), list(s.values))
    _rotular_linhas(ax, series)
    ax.legend(frameon=False, loc="upper left", ncols=4, fontsize=9, labelcolor=TINTA_2)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=1))
    ax.set_ylabel("% dos casos novos")
    _rodape(fig, meta, "Conta documentos por processo-grau, filtrado em G1 — nao e "
                       "identico a processos distintos, mas e comparavel entre numerador e denominador.")
    return _salvar(fig, "03_participacao_consumo")


def terrestre_por_empresa(topo: int = 15) -> str:
    df, meta = carregar_parquet("consumidor_gov_empresa_ano")
    df = df[df["segmento_rotulo"] == "Transporte Terrestre"]
    agr = df.groupby("empresa")["reclamacoes"].sum().sort_values(ascending=False).head(topo)
    fig, ax = _figura(
        f"Transporte terrestre: {topo} empresas mais reclamadas",
        "Reclamacoes no consumidor.gov.br (volume absoluto, sem normalizar)",
        tamanho=(11, 7),
    )
    ax.barh(agr.index[::-1], agr.values[::-1], color=SERIES[0], height=0.72)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.xaxis.set_major_formatter(_MILHAR)
    ax.set_xlabel("reclamacoes")
    _rodape(fig, meta, "Volume absoluto premia empresa pequena e pune quem transporta mais gente: "
                       "veja o grafico normalizado por 100 mil passageiros antes de concluir.")
    return _salvar(fig, "04_terrestre_por_empresa")


def terrestre_por_problema(topo: int = 12) -> str:
    df, meta = carregar_parquet("consumidor_gov_problema_ano")
    df = df[df["segmento_rotulo"] == "Transporte Terrestre"]
    coluna = "grupo_problema" if "grupo_problema" in df.columns else "problema"
    agr = df.groupby(coluna)["reclamacoes"].sum().sort_values(ascending=False).head(topo)
    fig, ax = _figura("Transporte terrestre: principais problemas relatados",
                      "Reclamacoes no consumidor.gov.br", tamanho=(11, 7))
    ax.barh(agr.index[::-1], agr.values[::-1], color=SERIES[0], height=0.72)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.xaxis.set_major_formatter(_MILHAR)
    ax.set_xlabel("reclamacoes")
    _rodape(fig, meta)
    return _salvar(fig, "05_terrestre_por_problema")


def benchmark_modal() -> str:
    df, meta = carregar_parquet("consumidor_gov_empresa_ano")
    fig, ax = _figura("Terrestre x aereo: reclamacoes por ano",
                      "Modais lado a lado, nunca somados")
    series = {}
    for i, (seg, bloco) in enumerate(sorted(df.groupby("segmento_rotulo"))):
        s = bloco.groupby("ano")["reclamacoes"].sum()
        ax.plot(s.index, s.values, linewidth=2.5, color=SERIES[i], label=seg)
        series[seg] = (list(s.index), list(s.values))
    _rotular_linhas(ax, series)
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=TINTA_2)
    ax.yaxis.set_major_formatter(_MILHAR)
    ax.set_ylabel("reclamacoes")
    _rodape(fig, meta, "O aereo entra so como referencia comparativa: tem regulacao de CX "
                       "mais antiga e base de passageiros de outra ordem de grandeza.")
    return _salvar(fig, "06_benchmark_terrestre_aereo")


def normalizado_100k() -> str:
    from .analise import por_100k

    rec, meta_r = carregar_parquet("consumidor_gov_empresa_ano")
    dem, meta_d = carregar_parquet("demanda_passageiros")
    rec = rec[rec["segmento_rotulo"] == "Transporte Terrestre"]
    agr = rec.groupby("ano", as_index=False)["reclamacoes"].sum()
    casadas, sobras = por_100k(agr, dem[dem["modal"] == "Rodoviario"], coluna_valor="reclamacoes")
    if casadas.empty:
        raise ErroDeFonte("Nenhum ano com reclamacoes e passageiros ao mesmo tempo.")
    fig, ax = _figura("Transporte terrestre: reclamacoes por 100 mil passageiros",
                      "A metrica que permite comparar empresas e modais")
    ax.bar(casadas["ano"].astype(int).astype(str), casadas["por_100k_passageiros"],
           color=SERIES[0], width=0.62)
    ax.set_ylabel("reclamacoes / 100 mil passageiros")
    extra = ""
    if len(sobras):
        extra = (f"{len(sobras)} ano(s) sem denominador de passageiros ficaram de fora "
                 "(nao foram zerados).")
    _rodape(fig, [meta_r, meta_d], extra)
    return _salvar(fig, "07_normalizado_100k")


def concentracao_orgaos() -> str:
    from .analise import concentracao

    df, meta = carregar_parquet("datajud_b2c_por_orgao")
    c = concentracao(df, grupo="orgao_julgador_nome", valor="processos", topo=5)
    if c.empty:
        raise ErroDeFonte("Sem dados para calcular concentracao.")
    fig, ax = _figura("Sinal indireto: concentracao de processos por orgao julgador",
                      "HHI (0 = disperso, 1 = tudo num orgao so)")
    ax.plot(c["ano"], c["hhi"], linewidth=2.5, color=SERIES[0], marker="o",
            markersize=7, markeredgecolor=SUPERFICIE, markeredgewidth=2)
    ax.set_ylabel("HHI")
    ax.set_ylim(0, max(0.2, float(c["hhi"].max()) * 1.25))
    _rodape(fig, meta, "SINAL, NAO PROVA: o DataJud nao expoe partes nem pecas, entao "
                       "repeticao/similaridade nao e mensuravel. Concentracao alta tambem e "
                       "compativel com empresa grande e servico ruim num foro onde ela opera.")
    return _salvar(fig, "08_concentracao_orgaos")


GRAFICOS = [
    serie_nacional_consumo, serie_por_uf, participacao_consumo,
    terrestre_por_empresa, terrestre_por_problema, benchmark_modal,
    normalizado_100k, concentracao_orgaos,
]


def executar(refresh: bool = False) -> dict:
    """Desenha o que da para desenhar; reporta o que falta e por que."""
    feitos, pulados = [], []
    for fn in GRAFICOS:
        try:
            feitos.append(fn())
        except ErroDeFonte as exc:
            pulados.append((fn.__name__, str(exc).split(".")[0]))
            log.warning("PULADO %s — %s", fn.__name__, str(exc).split(".")[0])
    log.info("%d grafico(s) gerado(s), %d pulado(s)", len(feitos), len(pulados))
    if not feitos:
        raise ErroDeFonte(
            "Nenhum grafico pode ser gerado: rode as etapas de coleta antes. "
            f"Faltando: {[p[0] for p in pulados]}"
        )
    return {"feitos": feitos, "pulados": pulados}


if __name__ == "__main__":
    try:
        executar()
    except ErroDeFonte as exc:
        log.error("%s", exc)
        sys.exit(1)
