"""Concordância entre duas passadas de extração independentes (Seção 10, item 3).

Uso:
    python -m src.sac.concordancia \
        --a data/raw/sac/extraidos_categoria_inferior \
        --b data/raw/sac/extraidos_verificacao
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

CAMPOS_ENUM = [
    "duracao_interrupcao_faixa", "troca_de_veiculo", "retido_rodovia_terminal",
    "perda_de_conexao", "viagem_concluida", "gasto_comprovado", "hospedagem_necessaria",
    "qualidade_informacao_ocorrencia", "passou_por_pendencia_interna",
    "houve_retorno_da_area", "mencionou_advogado", "mencionou_procon",
    "mencionou_processo_ou_danos_morais", "mencionou_reclame_aqui_ou_consumidorgov",
    "tom_ameaca_juridica", "oferta_escolhida_pelo_cliente", "oferta_executada_no_ticket",
]
CAMPOS_NUM = ["oferta_valor_texto", "atraso_chegada_horas"]


def comparar(dir_a: Path, dir_b: Path) -> dict:
    comuns = sorted({p.name for p in dir_a.glob("*.json")} & {p.name for p in dir_b.glob("*.json")})
    acordo = defaultdict(int)
    divergentes = defaultdict(list)
    for nome in comuns:
        a = json.loads((dir_a / nome).read_text(encoding="utf-8"))
        b = json.loads((dir_b / nome).read_text(encoding="utf-8"))
        for c in CAMPOS_ENUM:
            if a.get(c) == b.get(c):
                acordo[c] += 1
            else:
                divergentes[c].append(f"{nome[:-5]}: {a.get(c)!r} x {b.get(c)!r}")
        for c in CAMPOS_NUM:
            va, vb = a.get(c), b.get(c)
            try:
                ok = (va is None and vb is None) or abs(float(va) - float(vb)) < 0.51
            except (TypeError, ValueError):
                ok = va == vb
            if ok:
                acordo[c] += 1
            else:
                divergentes[c].append(f"{nome[:-5]}: {va!r} x {vb!r}")
    n = len(comuns)
    pct = {c: round(100 * acordo[c] / n, 1) for c in CAMPOS_ENUM + CAMPOS_NUM} if n else {}
    return {
        "n_tickets": n,
        "concordancia_pct_por_campo": dict(sorted(pct.items(), key=lambda kv: kv[1])),
        "concordancia_media_pct": round(sum(pct.values()) / len(pct), 1) if pct else None,
        "divergencias": {c: v for c, v in divergentes.items()},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, type=Path)
    ap.add_argument("--b", required=True, type=Path)
    args = ap.parse_args()
    r = comparar(args.a, args.b)
    print(json.dumps(r, ensure_ascii=False, indent=2))
