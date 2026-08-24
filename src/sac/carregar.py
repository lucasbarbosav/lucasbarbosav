"""Carga: JSONs brutos (ticket+timeline) + JSONs extraídos -> SQLite.

Uso:
    python -m src.sac.carregar --tema "Categoria inferior" \
        --brutos data/raw/sac/brutos_categoria_inferior \
        --extraidos data/raw/sac/extraidos_categoria_inferior

Idempotente: ticket já no livro-razão `processados` é pulado. Um ticket inválido
vira linha em `erros` e o run segue.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .db import conectar, ja_processados, registrar_erro
from .scrub import redigir_pii

TRI = {"sim", "nao", "nao_informado"}
ENUMS = {
    "duracao_interrupcao_faixa": {"<1h", "1-3h", "3-6h", ">6h", "nao_informado"},
    "troca_de_veiculo": TRI, "retido_rodovia_terminal": TRI, "perda_de_conexao": TRI,
    "viagem_concluida": TRI, "gasto_comprovado": TRI, "hospedagem_necessaria": TRI,
    "qualidade_informacao_ocorrencia": {"boa", "parcial", "ausente", "nao_informado"},
    "passou_por_pendencia_interna": {"sim", "nao"},
    "houve_retorno_da_area": {"sim", "nao", "nao_aplicavel"},
    "mencionou_advogado": {"sim", "nao"}, "mencionou_procon": {"sim", "nao"},
    "mencionou_processo_ou_danos_morais": {"sim", "nao"},
    "mencionou_reclame_aqui_ou_consumidorgov": {"sim", "nao"},
    "tom_ameaca_juridica": {"nenhum", "leve", "explicito"},
    "extracao_confianca": {"alta", "media", "baixa"},
    "oferta_executada_no_ticket": TRI,
    "oferta_escolhida_pelo_cliente": {
        "reembolso_diferenca", "cupom_50", "cortesia", "estorno_cartao",
        "reembolso_integral", "outra", "recusou", "sem_resposta", "nao_informado"},
}
TEXTO_LIVRE = ["categoria_comprada", "categoria_viajada", "trecho_origem_destino",
               "area_destino", "oferta_texto"]
SEM_OFERTA = {"nao_informado", "nada ofertado", "nada", "nenhuma", "nenhum"}


def _valida(ext: dict, erros: list[str]) -> dict:
    """Normaliza a saída da extração; valores fora do enum viram nao_informado + erro."""
    out = dict(ext)
    for campo, permitidos in ENUMS.items():
        v = out.get(campo)
        if v not in permitidos:
            erros.append(f"{campo}: valor invalido {v!r}")
            out[campo] = "nao_informado" if "nao_informado" in permitidos else None
    for campo in ("atraso_chegada_horas", "oferta_valor_texto"):
        v = out.get(campo)
        if v is not None:
            try:
                out[campo] = float(str(v).replace("R$", "").replace(",", "."))
            except ValueError:
                erros.append(f"{campo}: nao numerico {v!r}")
                out[campo] = None
    return out


def _horas_desde_criacao(meta: dict, quando: str | None) -> float | None:
    if not quando:
        return None
    try:
        criado = datetime.fromisoformat(meta["createdTime"].replace("Z", "+00:00"))
        s = str(quando).strip().replace(" UTC", "").replace("Z", "+00:00")
        t = datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=criado.tzinfo)
        return round((t - criado).total_seconds() / 3600, 2)
    except (KeyError, ValueError, TypeError):
        return None


def _primeira_resposta_h(meta: dict, timeline: list[dict]) -> float | None:
    for item in timeline:
        if item.get("tipo") == "thread" and item.get("direcao") == "out":
            return _horas_desde_criacao(meta, item.get("quando"))
    return None


def carregar(tema: str, dir_brutos: Path, dir_extraidos: Path, caminho_db=None) -> dict:
    con = conectar(caminho_db) if caminho_db else conectar()
    feitos = ja_processados(con, tema)
    n_ok = n_erro = n_pulado = 0

    for arq in sorted(dir_extraidos.glob("*.json")):
        chave = arq.stem
        bruto_arq = dir_brutos / arq.name
        try:
            ext = json.loads(arq.read_text(encoding="utf-8"))
            bruto = json.loads(bruto_arq.read_text(encoding="utf-8"))
            meta = bruto["meta"]
            ticket_id = str(meta["id"])
            if ticket_id in feitos:
                n_pulado += 1
                continue

            problemas: list[str] = []
            ext = _valida(ext, problemas)
            for p in problemas:
                registrar_erro(con, ticket_id, "validacao", p)

            oferta_campo = meta.get("solucao")
            oferta_texto = (ext.get("oferta_texto") or "nao_informado").strip()
            houve_oferta_no_texto = bool(ext.get("oferta_opcoes")) or \
                oferta_texto.lower() not in SEM_OFERTA
            divergencia = int(not oferta_campo and houve_oferta_no_texto)

            created = meta.get("createdTime", "")
            linha = {
                "ticket_id": ticket_id,
                "ticket_number": str(meta.get("ticketNumber", chave)),
                "tema": tema,
                "empresa": meta.get("filial"),
                "motivo": meta.get("motivo"), "submotivo": meta.get("submotivo"),
                "detalhe_motivo": meta.get("detalhe_motivo"),
                "canal": meta.get("channel"),
                "created_time": created, "mes": created[:7],
                "status": meta.get("status"), "status_type": meta.get("statusType"),
                "classification": meta.get("classification"),
                "thread_count": int(meta.get("threadCount") or 0),
                "comment_count": int(meta.get("commentCount") or 0),
                "oferta_campo": oferta_campo,
                "oferta_texto": redigir_pii(oferta_texto),
                "oferta_valor_texto": ext.get("oferta_valor_texto"),
                "oferta_opcoes": json.dumps(ext.get("oferta_opcoes") or [], ensure_ascii=False),
                "divergencia_campo_texto": divergencia,
                "tempo_ate_primeira_resposta_h": _primeira_resposta_h(meta, bruto.get("timeline", [])),
                "tempo_primeira_resposta_substantiva_h": _horas_desde_criacao(
                    meta, ext.get("quando_primeira_resposta_substantiva")),
                "cliente_reincidente_janela": None,
                "leak_mention": int(bool(ext.get("leak_mention"))),
                "campos_ausentes": json.dumps(ext.get("campos_ausentes") or [], ensure_ascii=False),
                "extracao_confianca": ext.get("extracao_confianca"),
                "atraso_chegada_horas": ext.get("atraso_chegada_horas"),
            }
            for campo in ENUMS:
                if campo not in ("extracao_confianca",):
                    linha[campo] = ext.get(campo)
            for campo in TEXTO_LIVRE:
                if campo != "oferta_texto":
                    linha[campo] = redigir_pii(ext.get(campo))
            linha["area_destino"] = linha.get("area_destino") or meta.get("area_pi") or "nao_informado"

            cols = ", ".join(linha)
            marks = ", ".join("?" for _ in linha)
            con.execute(f"INSERT OR REPLACE INTO atributos ({cols}) VALUES ({marks})",
                        list(linha.values()))

            evid = {k: redigir_pii(str(v)) for k, v in (ext.get("evidencia") or {}).items()}
            con.execute("INSERT OR REPLACE INTO extracao_raw (ticket_id, json_bruto, evidencia) VALUES (?,?,?)",
                        (ticket_id, redigir_pii(json.dumps(ext, ensure_ascii=False)),
                         json.dumps(evid, ensure_ascii=False)))
            con.execute("INSERT OR REPLACE INTO processados (ticket_id, tema) VALUES (?,?)",
                        (ticket_id, tema))
            n_ok += 1
            if n_ok % 50 == 0:
                con.commit()
        except Exception as e:  # noqa: BLE001 — um ticket nunca derruba o run
            registrar_erro(con, chave, "carga", f"{type(e).__name__}: {e}")
            n_erro += 1
    con.commit()
    con.close()
    return {"ok": n_ok, "erros": n_erro, "pulados": n_pulado}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--brutos", required=True, type=Path)
    ap.add_argument("--extraidos", required=True, type=Path)
    args = ap.parse_args()
    print(carregar(args.tema, args.brutos, args.extraidos))
