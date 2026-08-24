"""Exportação e métricas de calibração (Seções 10-11 do plano).

Uso:
    python -m src.sac.exportar --tema "Categoria inferior" --csv data/raw/sac/calibracao.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from .carregar import ENUMS
from .db import conectar


def exportar_csv(tema: str, destino: Path, caminho_db=None) -> int:
    con = conectar(caminho_db) if caminho_db else conectar()
    con.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    linhas = con.execute(
        "SELECT a.*, r.evidencia FROM atributos a "
        "LEFT JOIN extracao_raw r ON r.ticket_id = a.ticket_id "
        "WHERE a.tema = ? ORDER BY a.created_time", (tema,)).fetchall()
    con.close()
    if not linhas:
        return 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    return len(linhas)


def metricas(tema: str, caminho_db=None) -> dict:
    """% nao_informado por campo, distribuições e divergência campo×texto por canal."""
    con = conectar(caminho_db) if caminho_db else conectar()
    con.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    linhas = con.execute("SELECT * FROM atributos WHERE tema = ?", (tema,)).fetchall()
    con.close()
    n = len(linhas)
    if n == 0:
        return {"n": 0}

    campos = [c for c in ENUMS if c != "extracao_confianca"]
    pct_nao_informado = {}
    distribuicoes = {}
    for campo in campos + ["extracao_confianca"]:
        vals = Counter(str(l.get(campo)) for l in linhas)
        distribuicoes[campo] = dict(vals.most_common())
        pct_nao_informado[campo] = round(100 * vals.get("nao_informado", 0) / n, 1)

    div_por_canal = {}
    for canal in sorted({l["canal"] or "?" for l in linhas}):
        do_canal = [l for l in linhas if (l["canal"] or "?") == canal]
        com_div = sum(1 for l in do_canal if l["divergencia_campo_texto"])
        div_por_canal[canal] = {"n": len(do_canal),
                                "divergencia_pct": round(100 * com_div / len(do_canal), 1)}

    return {
        "n": n,
        "pct_nao_informado_por_campo": dict(sorted(
            pct_nao_informado.items(), key=lambda kv: -kv[1])),
        "distribuicoes": distribuicoes,
        "divergencia_por_canal": div_por_canal,
        "leak_mention_n": sum(1 for l in linhas if l["leak_mention"]),
        "campos_95pct_nao_informado": [c for c, p in pct_nao_informado.items() if p >= 95],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args()
    if args.csv:
        print(f"{exportar_csv(args.tema, args.csv)} linhas -> {args.csv}")
    print(json.dumps(metricas(args.tema), ensure_ascii=False, indent=2))
