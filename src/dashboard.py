"""Dashboard estatico em `output/dashboard/index.html`.

Sem backend, sem CDN e sem `localStorage`: o plotly.js vai embutido no arquivo e
os dados viajam como JSON dentro da propria pagina. Abrir o HTML basta.

Filtros por ano, UF, segmento e empresa sao aplicados em JavaScript puro sobre
os dados embutidos. Cada cartao carrega o rodape de proveniencia do seu Parquet
e, quando existe, a ressalva metodologica gravada no `.meta.json`.
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from ._common import DASHBOARD, ErroDeFonte, carregar_parquet, configurar_log, rel

log = configurar_log("dashboard")

# Mesma paleta validada dos graficos estaticos (slots 1-4), com passo escuro.
SERIES_CLARO = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SERIES_ESCURO = ["#3987e5", "#d95926", "#199e70", "#c98500"]


def _carregar(nome: str):
    try:
        return carregar_parquet(nome)
    except ErroDeFonte as exc:
        log.warning("Sem `%s`: os cartoes que dependem dele nao serao gerados.", nome)
        log.debug("%s", exc)
        return None, None


def _registros(df: pd.DataFrame, colunas: list[str]) -> list[dict]:
    faltando = [c for c in colunas if c not in df.columns]
    if faltando:
        raise ErroDeFonte(f"colunas ausentes para o dashboard: {faltando}")
    limpo = df[colunas].copy()
    for c in limpo.columns:
        if pd.api.types.is_numeric_dtype(limpo[c]):
            limpo[c] = limpo[c].astype(float).where(limpo[c].notna(), None)
        else:
            limpo[c] = limpo[c].astype(str)
    return json.loads(limpo.to_json(orient="records"))


def montar_dados() -> tuple[dict, list[str]]:
    """Reune o que existe. O que faltar vira aviso na propria pagina."""
    dados: dict = {}
    ausentes: list[str] = []

    serie, meta_serie = _carregar("datajud_b2c_serie_mensal")
    if serie is not None:
        dados["serie_judicial"] = {
            "registros": _registros(serie, ["uf", "tribunal", "ano", "mes", "processos"]),
            "proveniencia": meta_serie.rodape(),
            "ressalva": meta_serie.observacao,
        }
    else:
        ausentes.append("Série judicial (DataJud) — rode a etapa `datajud`.")

    part, meta_part = _carregar("datajud_participacao_consumo")
    if part is not None:
        dados["participacao"] = {
            "registros": _registros(part, ["uf", "ano", "mes", "documentos_total",
                                           "documentos_consumo"]),
            "proveniencia": meta_part.rodape(),
            "ressalva": meta_part.observacao,
        }
    else:
        ausentes.append("Participação do consumo no total — rode a etapa `datajud`.")

    emp, meta_emp = _carregar("consumidor_gov_empresa_ano")
    if emp is not None:
        dados["consumidor_empresa"] = {
            "registros": _registros(emp, ["segmento_rotulo", "ano", "empresa", "uf",
                                          "reclamacoes", "indice_solucao"]),
            "proveniencia": meta_emp.rodape(),
            "ressalva": meta_emp.observacao,
        }
    else:
        ausentes.append("Reclamações por empresa — rode a etapa `consumidor`.")

    prob, meta_prob = _carregar("consumidor_gov_problema_ano")
    if prob is not None:
        col = "grupo_problema" if "grupo_problema" in prob.columns else "problema"
        tmp = prob.rename(columns={col: "problema_rotulo"})
        dados["consumidor_problema"] = {
            "registros": _registros(tmp, ["segmento_rotulo", "ano", "problema_rotulo",
                                          "reclamacoes"]),
            "proveniencia": meta_prob.rodape(),
            "ressalva": meta_prob.observacao,
        }
    else:
        ausentes.append("Reclamações por problema — rode a etapa `consumidor`.")

    dem, meta_dem = _carregar("demanda_passageiros")
    if dem is not None:
        dados["demanda"] = {
            "registros": _registros(dem.groupby(["ano", "modal"], as_index=False)["passageiros"].sum(),
                                    ["ano", "modal", "passageiros"]),
            "proveniencia": meta_dem.rodape(),
            "ressalva": meta_dem.observacao,
        }
    else:
        ausentes.append("Passageiros transportados — rode a etapa `demanda`. "
                        "Sem eles não há normalização por 100 mil.")

    orgao, meta_orgao = _carregar("datajud_b2c_por_orgao")
    if orgao is not None:
        dados["orgaos"] = {
            "registros": _registros(orgao, ["uf", "ano", "orgao_julgador_nome", "processos"]),
            "proveniencia": meta_orgao.rodape(),
            "ressalva": meta_orgao.observacao,
        }
    else:
        ausentes.append("Concentração por órgão julgador — rode a etapa `datajud`.")

    ouv, meta_ouv = _carregar("antt_ouvidoria_categorias")
    if ouv is not None:
        cols = [c for c in ["ano", "CX", "Passe Livre", "Outros"] if c in ouv.columns]
        dados["ouvidoria"] = {
            "registros": _registros(ouv, cols),
            "proveniencia": meta_ouv.rodape(),
            "ressalva": meta_ouv.observacao,
        }
    else:
        ausentes.append("Ouvidoria da ANTT — rode a etapa `antt_ouvidoria`.")

    return dados, ausentes


def executar(refresh: bool = False) -> dict:
    dados, ausentes = montar_dados()
    if not dados:
        raise ErroDeFonte(
            "Nenhum dataset tratado disponivel: o dashboard ficaria vazio. "
            "Rode as etapas de coleta antes."
        )

    import plotly.offline as po

    plotly_js = po.get_plotlyjs()
    html = _TEMPLATE.replace("/*PLOTLY_JS*/", plotly_js)
    html = html.replace("/*DADOS*/", json.dumps(dados, ensure_ascii=False))
    html = html.replace("/*AUSENTES*/", json.dumps(ausentes, ensure_ascii=False))
    html = html.replace("/*PALETA_CLARO*/", json.dumps(SERIES_CLARO))
    html = html.replace("/*PALETA_ESCURO*/", json.dumps(SERIES_ESCURO))

    DASHBOARD.mkdir(parents=True, exist_ok=True)
    destino = DASHBOARD / "index.html"
    destino.write_text(html, encoding="utf-8")
    tamanho = destino.stat().st_size / 1024
    log.info("Dashboard gravado: %s (%.0f KB, %d cartoes, %d ausentes)",
             rel(destino), tamanho, len(dados), len(ausentes))
    return {"arquivo": rel(destino), "cartoes": list(dados), "ausentes": ausentes}


_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Judicialização do consumo — transporte rodoviário de passageiros</title>
<script>/*PLOTLY_JS*/</script>
<style>
:root{
  color-scheme: light;
  --surface:#fcfcfb; --surface-2:#f4f3f0; --border:#e5e4e0;
  --text:#0b0b0b; --text-2:#52514e; --text-3:#77756f;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --aviso-bg:#fdf3e3; --aviso-borda:#eda100;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --surface:#1a1a19; --surface-2:#232322; --border:#383835;
    --text:#ffffff; --text-2:#c3c2b7; --text-3:#8e8d85;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
    --aviso-bg:#2b2418; --aviso-borda:#c98500;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --surface:#1a1a19; --surface-2:#232322; --border:#383835;
  --text:#ffffff; --text-2:#c3c2b7; --text-3:#8e8d85;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --aviso-bg:#2b2418; --aviso-borda:#c98500;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);
  font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1220px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--text-2);margin:0 0 24px;max-width:70ch}
.filtros{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;
  background:var(--surface-2);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px;margin-bottom:26px;position:sticky;top:0;z-index:5}
.campo{display:flex;flex-direction:column;gap:4px}
.campo label{font-size:12px;color:var(--text-2);text-transform:uppercase;letter-spacing:.04em}
select,input{background:var(--surface);color:var(--text);border:1px solid var(--border);
  border-radius:7px;padding:7px 9px;font:inherit;font-size:14px;min-width:130px}
select[multiple]{min-height:78px}
button{background:var(--surface);color:var(--text);border:1px solid var(--border);
  border-radius:7px;padding:7px 12px;font:inherit;font-size:14px;cursor:pointer}
button:hover{border-color:var(--text-3)}
.card{border:1px solid var(--border);border-radius:12px;background:var(--surface);
  padding:18px 18px 12px;margin-bottom:22px}
.card h2{font-size:17px;margin:0 0 2px}
.card .desc{color:var(--text-2);font-size:13.5px;margin:0 0 12px;max-width:80ch}
.rodape{border-top:1px solid var(--border);margin-top:10px;padding-top:9px;
  font-size:11.5px;color:var(--text-3)}
.ressalva{background:var(--aviso-bg);border-left:3px solid var(--aviso-borda);
  padding:9px 12px;border-radius:0 6px 6px 0;font-size:12.5px;color:var(--text-2);
  margin:10px 0 0}
.grafico{width:100%;min-height:380px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
th,td{border-bottom:1px solid var(--border);padding:6px 9px;text-align:left}
th{color:var(--text-2);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.oculto{display:none}
.faltando{background:var(--aviso-bg);border-left:3px solid var(--aviso-borda);
  padding:12px 15px;border-radius:0 8px 8px 0;margin-bottom:22px}
.faltando ul{margin:6px 0 0;padding-left:20px}
.vazio{color:var(--text-3);padding:40px 0;text-align:center}
</style>
</head>
<body>
<div class="wrap">
<h1>Judicialização do direito do consumidor</h1>
<p class="sub">Recorte: transporte rodoviário interestadual de passageiros. Todos os números
carregam fonte e data de extração. Universos B2C e regulatório nunca são somados;
comparações entre empresas ou modais usam a métrica por 100 mil passageiros.</p>

<div id="faltando"></div>

<div class="filtros">
  <div class="campo"><label for="f-ano-ini">Ano inicial</label><select id="f-ano-ini"></select></div>
  <div class="campo"><label for="f-ano-fim">Ano final</label><select id="f-ano-fim"></select></div>
  <div class="campo"><label for="f-uf">UF</label><select id="f-uf" multiple size="4"></select></div>
  <div class="campo"><label for="f-segmento">Segmento</label><select id="f-segmento"></select></div>
  <div class="campo"><label for="f-empresa">Empresa contém</label><input id="f-empresa" type="search" placeholder="ex.: viação"></div>
  <div class="campo"><label for="f-topo">Top N</label><select id="f-topo"></select></div>
  <div class="campo"><label>&nbsp;</label><button id="b-limpar">Limpar filtros</button></div>
  <div class="campo"><label>&nbsp;</label><button id="b-tabela">Ver como tabela</button></div>
  <div class="campo"><label>&nbsp;</label><button id="b-tema">Tema claro/escuro</button></div>
</div>

<div id="cartoes"></div>
</div>

<script>
const DADOS = /*DADOS*/;
const AUSENTES = /*AUSENTES*/;
const PAL_CLARO = /*PALETA_CLARO*/;
const PAL_ESCURO = /*PALETA_ESCURO*/;

const escuro = () => {
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
};
const paleta = () => escuro() ? PAL_ESCURO : PAL_CLARO;
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();

const num = (v) => v == null ? "—" : v.toLocaleString("pt-BR", {maximumFractionDigits: 2});
const soma = (arr, k) => arr.reduce((t, r) => t + (Number(r[k]) || 0), 0);

function agrupar(registros, chaves, valor, modo) {
  const mapa = new Map();
  for (const r of registros) {
    const k = chaves.map(c => r[c]).join("␟");
    if (!mapa.has(k)) mapa.set(k, {chave: chaves.map(c => r[c]), soma: 0, n: 0});
    const e = mapa.get(k);
    const v = Number(r[valor]);
    if (!Number.isNaN(v) && r[valor] != null) { e.soma += v; e.n += 1; }
  }
  return [...mapa.values()].map(e => {
    const o = {};
    chaves.forEach((c, i) => o[c] = e.chave[i]);
    o[valor] = modo === "media" ? (e.n ? e.soma / e.n : null) : e.soma;
    return o;
  });
}

// ---- estado dos filtros -------------------------------------------------
const F = {anoIni: null, anoFim: null, ufs: [], segmento: "Transporte Terrestre",
           empresa: "", topo: 15, tabela: false};

function anosDisponiveis() {
  const s = new Set();
  for (const bloco of Object.values(DADOS))
    for (const r of bloco.registros) if (r.ano != null) s.add(Number(r.ano));
  return [...s].sort((a, b) => a - b);
}
function ufsDisponiveis() {
  const s = new Set();
  for (const bloco of Object.values(DADOS))
    for (const r of bloco.registros) if (r.uf) s.add(r.uf);
  return [...s].sort();
}
function segmentosDisponiveis() {
  const s = new Set();
  for (const chave of ["consumidor_empresa", "consumidor_problema"])
    if (DADOS[chave]) for (const r of DADOS[chave].registros) if (r.segmento_rotulo) s.add(r.segmento_rotulo);
  return [...s].sort();
}

const filtraAno = (r) => r.ano == null ||
  (Number(r.ano) >= F.anoIni && Number(r.ano) <= F.anoFim);
const filtraUf = (r) => !F.ufs.length || !r.uf || F.ufs.includes(r.uf);
const filtraSeg = (r) => !r.segmento_rotulo || r.segmento_rotulo === F.segmento;
const filtraEmp = (r) => !F.empresa || !r.empresa ||
  r.empresa.toLowerCase().includes(F.empresa.toLowerCase());

// ---- montagem dos cartoes ----------------------------------------------
const cartoes = [];
function cartao(id, titulo, desc, fonteChave, construir, colunasTabela) {
  cartoes.push({id, titulo, desc, fonteChave, construir, colunasTabela});
}

const layoutBase = () => ({
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  font: {color: css("--text-2"), size: 12,
         family: 'ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'},
  margin: {l: 64, r: 24, t: 12, b: 44},
  xaxis: {gridcolor: css("--border"), zeroline: false, linecolor: css("--border")},
  yaxis: {gridcolor: css("--border"), zeroline: false, linecolor: css("--border"),
          separatethousands: true},
  legend: {orientation: "h", y: 1.12, x: 0, font: {color: css("--text-2")}},
  hovermode: "x unified",
  hoverlabel: {bgcolor: css("--surface-2"), bordercolor: css("--border"),
               font: {color: css("--text")}},
});

if (DADOS.serie_judicial) cartao(
  "serie", "Casos novos de consumo na Justiça Estadual",
  "Processos distintos por ano — contagem por número de processo, nunca por ocorrência de assunto.",
  "serie_judicial",
  () => {
    const reg = DADOS.serie_judicial.registros.filter(r => filtraAno(r) && filtraUf(r));
    if (!reg.length) return null;
    const cores = paleta();
    const ufs = [...new Set(reg.map(r => r.uf))].sort();
    const traces = ufs.map((uf, i) => {
      const g = agrupar(reg.filter(r => r.uf === uf), ["ano"], "processos", "soma")
        .sort((a, b) => a.ano - b.ano);
      return {type: "scatter", mode: "lines+markers", name: uf,
              x: g.map(d => d.ano), y: g.map(d => d.processos),
              line: {width: 2, color: cores[i % cores.length]},
              marker: {size: 8, color: cores[i % cores.length],
                       line: {width: 2, color: css("--surface")}}};
    });
    return {traces, layout: Object.assign(layoutBase(),
      {yaxis: Object.assign(layoutBase().yaxis, {title: {text: "processos distintos"}})})};
  },
  ["uf", "ano", "processos"]
);

if (DADOS.participacao) cartao(
  "participacao", "Participação do consumo no total de casos novos",
  "Numerador e denominador contam documentos no mesmo grau (1º) — só assim a razão significa algo.",
  "participacao",
  () => {
    const reg = DADOS.participacao.registros.filter(r => filtraAno(r) && filtraUf(r));
    if (!reg.length) return null;
    const cores = paleta();
    const ufs = [...new Set(reg.map(r => r.uf))].sort();
    const traces = ufs.map((uf, i) => {
      const anos = [...new Set(reg.filter(r => r.uf === uf).map(r => Number(r.ano)))].sort((a, b) => a - b);
      const y = anos.map(a => {
        const bloco = reg.filter(r => r.uf === uf && Number(r.ano) === a);
        const t = soma(bloco, "documentos_total");
        return t ? soma(bloco, "documentos_consumo") / t : null;
      });
      return {type: "scatter", mode: "lines+markers", name: uf, x: anos, y,
              hovertemplate: "%{y:.1%}<extra>" + uf + "</extra>",
              line: {width: 2, color: cores[i % cores.length]},
              marker: {size: 8, color: cores[i % cores.length],
                       line: {width: 2, color: css("--surface")}}};
    });
    const lay = layoutBase();
    lay.yaxis = Object.assign(lay.yaxis, {tickformat: ".1%", title: {text: "% dos casos novos"}});
    return {traces, layout: lay};
  },
  ["uf", "ano", "documentos_consumo", "documentos_total"]
);

if (DADOS.consumidor_empresa) cartao(
  "empresas", "Empresas mais reclamadas no segmento",
  "Volume absoluto no consumidor.gov.br. Antes de concluir qualquer coisa, veja o cartão normalizado por 100 mil passageiros.",
  "consumidor_empresa",
  () => {
    const reg = DADOS.consumidor_empresa.registros
      .filter(r => filtraAno(r) && filtraUf(r) && filtraSeg(r) && filtraEmp(r));
    if (!reg.length) return null;
    const g = agrupar(reg, ["empresa"], "reclamacoes", "soma")
      .sort((a, b) => b.reclamacoes - a.reclamacoes).slice(0, F.topo).reverse();
    const lay = layoutBase();
    lay.margin.l = 210; lay.hovermode = "closest";
    return {traces: [{type: "bar", orientation: "h",
        x: g.map(d => d.reclamacoes), y: g.map(d => d.empresa),
        marker: {color: paleta()[0], line: {width: 2, color: css("--surface")}},
        hovertemplate: "%{y}: %{x:,} reclamações<extra></extra>"}], layout: lay};
  },
  ["empresa", "ano", "reclamacoes", "indice_solucao"]
);

if (DADOS.consumidor_problema) cartao(
  "problemas", "Principais problemas relatados",
  "Composição temática das reclamações do segmento selecionado.",
  "consumidor_problema",
  () => {
    const reg = DADOS.consumidor_problema.registros.filter(r => filtraAno(r) && filtraSeg(r));
    if (!reg.length) return null;
    const g = agrupar(reg, ["problema_rotulo"], "reclamacoes", "soma")
      .sort((a, b) => b.reclamacoes - a.reclamacoes).slice(0, F.topo).reverse();
    const lay = layoutBase();
    lay.margin.l = 210; lay.hovermode = "closest";
    return {traces: [{type: "bar", orientation: "h",
        x: g.map(d => d.reclamacoes), y: g.map(d => d.problema_rotulo),
        marker: {color: paleta()[0], line: {width: 2, color: css("--surface")}},
        hovertemplate: "%{y}: %{x:,}<extra></extra>"}], layout: lay};
  },
  ["problema_rotulo", "ano", "reclamacoes"]
);

if (DADOS.consumidor_empresa) cartao(
  "benchmark", "Terrestre × aéreo: reclamações por ano",
  "Modais lado a lado, jamais somados. O aéreo é referência comparativa: regulação de CX mais antiga e base de passageiros de outra ordem de grandeza.",
  "consumidor_empresa",
  () => {
    const reg = DADOS.consumidor_empresa.registros.filter(r => filtraAno(r) && filtraUf(r));
    if (!reg.length) return null;
    const cores = paleta();
    const segs = [...new Set(reg.map(r => r.segmento_rotulo))].sort();
    const traces = segs.map((seg, i) => {
      const g = agrupar(reg.filter(r => r.segmento_rotulo === seg), ["ano"], "reclamacoes", "soma")
        .sort((a, b) => a.ano - b.ano);
      return {type: "scatter", mode: "lines+markers", name: seg,
              x: g.map(d => d.ano), y: g.map(d => d.reclamacoes),
              line: {width: 2, color: cores[i % cores.length]},
              marker: {size: 8, color: cores[i % cores.length],
                       line: {width: 2, color: css("--surface")}}};
    });
    return {traces, layout: layoutBase()};
  },
  ["segmento_rotulo", "ano", "reclamacoes"]
);

if (DADOS.consumidor_empresa && DADOS.demanda) cartao(
  "normalizado", "Reclamações por 100 mil passageiros",
  "A única métrica que permite comparar empresas e modais. Ano sem denominador de passageiros fica de fora — não vira zero.",
  "demanda",
  () => {
    const modal = F.segmento === "Transporte Aereo" ? "Aereo" : "Rodoviario";
    const reg = DADOS.consumidor_empresa.registros.filter(r => filtraAno(r) && filtraSeg(r));
    const anos = [...new Set(reg.map(r => Number(r.ano)))].sort((a, b) => a - b);
    const pontos = [];
    for (const a of anos) {
      const den = soma(DADOS.demanda.registros.filter(
        r => Number(r.ano) === a && r.modal === modal), "passageiros");
      if (!den) continue;   // sem denominador: fora, nunca zero
      pontos.push({ano: a, taxa: soma(reg.filter(r => Number(r.ano) === a), "reclamacoes") / den * 1e5});
    }
    if (!pontos.length) return null;
    const lay = layoutBase();
    lay.hovermode = "closest";
    lay.yaxis = Object.assign(lay.yaxis, {title: {text: "por 100 mil passageiros"}});
    return {traces: [{type: "bar", x: pontos.map(p => p.ano), y: pontos.map(p => p.taxa),
        marker: {color: paleta()[0], line: {width: 2, color: css("--surface")}},
        hovertemplate: "%{x}: %{y:.2f} por 100 mil<extra></extra>"}], layout: lay};
  },
  ["ano", "modal", "passageiros"]
);

if (DADOS.orgaos) cartao(
  "concentracao", "Sinal indireto: concentração por órgão julgador",
  "HHI de 0 (disperso) a 1 (tudo num órgão só). Sinal, não prova: o DataJud não expõe partes nem peças, então repetição e similaridade não são mensuráveis.",
  "orgaos",
  () => {
    const reg = DADOS.orgaos.registros.filter(r => filtraAno(r) && filtraUf(r));
    if (!reg.length) return null;
    const anos = [...new Set(reg.map(r => Number(r.ano)))].sort((a, b) => a - b);
    const y = anos.map(a => {
      const g = agrupar(reg.filter(r => Number(r.ano) === a), ["orgao_julgador_nome"], "processos", "soma");
      const t = soma(g, "processos");
      if (!t) return null;
      return g.reduce((acc, d) => acc + Math.pow(d.processos / t, 2), 0);
    });
    const lay = layoutBase();
    lay.hovermode = "closest";
    lay.yaxis = Object.assign(lay.yaxis, {title: {text: "HHI"}, rangemode: "tozero"});
    return {traces: [{type: "scatter", mode: "lines+markers", x: anos, y,
        line: {width: 2, color: paleta()[0]},
        marker: {size: 9, color: paleta()[0], line: {width: 2, color: css("--surface")}},
        hovertemplate: "%{x}: HHI %{y:.3f}<extra></extra>"}], layout: lay};
  },
  ["uf", "ano", "orgao_julgador_nome", "processos"]
);

if (DADOS.ouvidoria) cartao(
  "ouvidoria", "Ouvidoria da ANTT: experiência do cliente × Passe Livre",
  "Categorias mutuamente exclusivas, mostradas lado a lado. Somá-las seria o erro: Passe Livre é acesso a política pública de gratuidade, não conflito de consumo comercial.",
  "ouvidoria",
  () => {
    const reg = DADOS.ouvidoria.registros.filter(filtraAno);
    if (!reg.length) return null;
    const cores = paleta();
    const anos = reg.map(r => r.ano);
    const cats = ["CX", "Passe Livre", "Outros"].filter(c => c in reg[0]);
    const lay = layoutBase();
    lay.barmode = "group"; lay.hovermode = "closest";
    return {traces: cats.map((c, i) => ({type: "bar", name: c, x: anos, y: reg.map(r => r[c]),
        marker: {color: cores[i % cores.length], line: {width: 2, color: css("--surface")}}})),
        layout: lay};
  },
  ["ano", "CX", "Passe Livre", "Outros"]
);

// ---- render -------------------------------------------------------------
function tabelaHTML(chave, colunas) {
  const reg = DADOS[chave].registros
    .filter(r => filtraAno(r) && filtraUf(r) && filtraSeg(r) && filtraEmp(r))
    .slice(0, 500);
  const cols = colunas.filter(c => reg.length && c in reg[0]);
  const cabecalho = cols.map(c => {
    const n = reg.length && typeof reg[0][c] === "number";
    return `<th class="${n ? "num" : ""}">${c}</th>`;
  }).join("");
  const linhas = reg.map(r => "<tr>" + cols.map(c => {
    const v = r[c];
    return typeof v === "number" ? `<td class="num">${num(v)}</td>` : `<td>${v ?? "—"}</td>`;
  }).join("") + "</tr>").join("");
  const aviso = DADOS[chave].registros.length > 500
    ? `<p class="rodape">Mostrando 500 de ${num(DADOS[chave].registros.length)} linhas filtradas.</p>` : "";
  return `<table><thead><tr>${cabecalho}</tr></thead><tbody>${linhas}</tbody></table>${aviso}`;
}

function montarEsqueleto() {
  const alvo = document.getElementById("cartoes");
  alvo.innerHTML = cartoes.map(c => `
    <section class="card" id="card-${c.id}">
      <h2>${c.titulo}</h2>
      <p class="desc">${c.desc}</p>
      <div class="grafico" id="g-${c.id}"></div>
      <div class="tabela oculto" id="t-${c.id}"></div>
      ${DADOS[c.fonteChave].ressalva ? `<p class="ressalva"><strong>Ressalva:</strong> ${DADOS[c.fonteChave].ressalva}</p>` : ""}
      <p class="rodape">${DADOS[c.fonteChave].proveniencia}</p>
    </section>`).join("");

  if (AUSENTES.length) {
    document.getElementById("faltando").innerHTML =
      `<div class="faltando"><strong>Dados ainda não coletados</strong> — estes cartões não aparecem
       porque a etapa correspondente não rodou. Nada foi estimado para preencher a lacuna.
       <ul>${AUSENTES.map(a => `<li>${a}</li>`).join("")}</ul></div>`;
  }
}

function render() {
  for (const c of cartoes) {
    const divG = document.getElementById("g-" + c.id);
    const divT = document.getElementById("t-" + c.id);
    divG.classList.toggle("oculto", F.tabela);
    divT.classList.toggle("oculto", !F.tabela);
    if (F.tabela) { divT.innerHTML = tabelaHTML(c.fonteChave, c.colunasTabela); continue; }
    const fig = c.construir();
    if (!fig) {
      divG.innerHTML = '<p class="vazio">Nenhum dado para os filtros selecionados.</p>';
      continue;
    }
    Plotly.react(divG, fig.traces, fig.layout,
                 {displayModeBar: false, responsive: true, locale: "pt-br"});
  }
}

function montarFiltros() {
  const anos = anosDisponiveis();
  const ini = document.getElementById("f-ano-ini"), fim = document.getElementById("f-ano-fim");
  anos.forEach(a => { ini.add(new Option(a, a)); fim.add(new Option(a, a)); });
  F.anoIni = anos[0]; F.anoFim = anos[anos.length - 1];
  ini.value = F.anoIni; fim.value = F.anoFim;

  const selUf = document.getElementById("f-uf");
  ufsDisponiveis().forEach(u => selUf.add(new Option(u, u)));

  const selSeg = document.getElementById("f-segmento");
  const segs = segmentosDisponiveis();
  segs.forEach(s => selSeg.add(new Option(s, s)));
  if (segs.length) { F.segmento = segs.includes("Transporte Terrestre") ? "Transporte Terrestre" : segs[0]; }
  selSeg.value = F.segmento;

  const selTopo = document.getElementById("f-topo");
  [5, 10, 15, 25, 50].forEach(n => selTopo.add(new Option(n, n)));
  selTopo.value = String(F.topo);

  ini.onchange = () => { F.anoIni = Number(ini.value); if (F.anoIni > F.anoFim) { F.anoFim = F.anoIni; fim.value = F.anoFim; } render(); };
  fim.onchange = () => { F.anoFim = Number(fim.value); if (F.anoFim < F.anoIni) { F.anoIni = F.anoFim; ini.value = F.anoIni; } render(); };
  selUf.onchange = () => { F.ufs = [...selUf.selectedOptions].map(o => o.value); render(); };
  selSeg.onchange = () => { F.segmento = selSeg.value; render(); };
  selTopo.onchange = () => { F.topo = Number(selTopo.value); render(); };
  document.getElementById("f-empresa").oninput = (e) => { F.empresa = e.target.value; render(); };

  document.getElementById("b-limpar").onclick = () => {
    F.anoIni = anos[0]; F.anoFim = anos[anos.length - 1]; F.ufs = []; F.empresa = "";
    F.topo = 15; F.segmento = selSeg.options.length ? selSeg.options[0].value : F.segmento;
    ini.value = F.anoIni; fim.value = F.anoFim; selTopo.value = "15";
    [...selUf.options].forEach(o => o.selected = false);
    document.getElementById("f-empresa").value = "";
    if (selSeg.options.length) selSeg.value = F.segmento;
    render();
  };
  document.getElementById("b-tabela").onclick = (e) => {
    F.tabela = !F.tabela;
    e.target.textContent = F.tabela ? "Ver como gráfico" : "Ver como tabela";
    render();
  };
  document.getElementById("b-tema").onclick = () => {
    document.documentElement.setAttribute("data-theme", escuro() ? "light" : "dark");
    render();
  };
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
}

montarEsqueleto();
montarFiltros();
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    try:
        print(executar())
    except ErroDeFonte as exc:
        log.error("%s", exc)
        sys.exit(1)
