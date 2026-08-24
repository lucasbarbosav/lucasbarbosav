"""Orquestrador do pipeline. Idempotente por padrao.

Cada etapa so roda se o dado tratado que ela produz ainda nao existe. Use
`--refresh` para rebaixar os brutos e recalcular tudo, ou `--recalcular` para
refazer o tratamento a partir dos brutos ja em cache.

    python run_all.py                      # roda o que falta
    python run_all.py --etapas consumidor  # so uma etapa
    python run_all.py --refresh            # rebaixa tudo da rede
    python run_all.py --listar             # mostra as etapas e seu estado
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable

from src._common import ErroDeFonte, configurar_log, existe_limpo

log = configurar_log("run_all")


@dataclass
class Etapa:
    nome: str
    descricao: str
    produz: tuple[str, ...]  # parquets em data/clean/ (sem extensao)
    executar: Callable[..., object]
    requisitos: tuple[str, ...] = ()  # o que precisa existir antes de rodar


def _consumidor(refresh: bool):
    from src.consumidor_gov import executar

    return executar(refresh=refresh)


def _datajud(refresh: bool):
    from src.datajud import executar

    return executar(refresh=refresh)


ETAPAS: list[Etapa] = [
    Etapa(
        nome="consumidor",
        descricao="Fonte 2 — consumidor.gov.br: recorte B2C por empresa (terrestre + aereo)",
        produz=(
            "consumidor_gov_transporte",
            "consumidor_gov_empresa_ano",
            "consumidor_gov_problema_ano",
            "consumidor_gov_total_segmentos",
        ),
        executar=_consumidor,
    ),
    Etapa(
        nome="datajud",
        descricao="Fonte 1 — DataJud/CNJ: volume judicial por assunto, classe e tribunal",
        produz=(
            "datajud_b2c",
            "datajud_regulatorio",
            "datajud_b2c_serie_mensal",
            "datajud_b2c_por_assunto",
            "datajud_b2c_por_orgao",
        ),
        executar=_datajud,
        requisitos=(
            "docs/tpu_dicionario.csv (gere com `python -m src.tpu`; veja docs/tpu_como_obter.md)",
            "DATAJUD_API_KEY no .env (chave publica divulgada pelo CNJ)",
        ),
    ),
]

# Etapas ainda nao implementadas, listadas para nao dar a impressao de que o
# pipeline esta completo. Serao adicionadas a ETAPAS conforme forem entregues.
PENDENTES = {
    "demanda": "Fonte 5 — ANTT/ANAC: passageiros transportados (denominador por 100 mil)",
    "antt_ouvidoria": "Fonte 3 — ANTT Ouvidoria: manifestacoes (CX separado de Passe Livre)",
    "grandes_litigantes": "Fonte 4 — CNJ: checagem de concentracao entre grandes reus",
    "graficos": "Graficos em output/charts/ com rodape de proveniencia",
    "dashboard": "Dashboard estatico em output/dashboard/index.html",
}


def _completa(etapa: Etapa) -> bool:
    return all(existe_limpo(p) for p in etapa.produz)


def listar() -> None:
    print("\nEtapas implementadas:")
    for e in ETAPAS:
        print(f"  [{'x' if _completa(e) else ' '}] {e.nome:20} {e.descricao}")
        for req in e.requisitos:
            print(f"      requer: {req}")
    print("\nEtapas pendentes (ainda nao implementadas):")
    for nome, desc in PENDENTES.items():
        print(f"  [ ] {nome:20} {desc}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapas", nargs="*", help="nomes das etapas a rodar (padrao: todas)")
    ap.add_argument("--refresh", action="store_true", help="rebaixa os brutos, ignorando o cache")
    ap.add_argument("--recalcular", action="store_true", help="refaz o tratamento mesmo se o parquet existir")
    ap.add_argument("--listar", action="store_true", help="mostra as etapas e sai")
    args = ap.parse_args()

    if args.listar:
        listar()
        return 0

    selecionadas = ETAPAS
    if args.etapas:
        desconhecidas = set(args.etapas) - {e.nome for e in ETAPAS}
        if desconhecidas:
            pend = desconhecidas & PENDENTES.keys()
            if pend:
                log.error("Etapa(s) ainda nao implementada(s): %s", ", ".join(sorted(pend)))
            outras = desconhecidas - PENDENTES.keys()
            if outras:
                log.error("Etapa(s) inexistente(s): %s", ", ".join(sorted(outras)))
            return 2
        selecionadas = [e for e in ETAPAS if e.nome in args.etapas]

    falhas = 0
    for etapa in selecionadas:
        if _completa(etapa) and not (args.refresh or args.recalcular):
            log.info("PULANDO %s — ja tratado (use --recalcular ou --refresh)", etapa.nome)
            continue
        log.info("==> %s: %s", etapa.nome, etapa.descricao)
        try:
            etapa.executar(refresh=args.refresh)
        except ErroDeFonte as exc:
            falhas += 1
            log.error("FONTE INDISPONIVEL em '%s': %s", etapa.nome, exc)
            log.error(
                "O pipeline NAO substitui fonte indisponivel por estimativa. "
                "Resolva o acesso e rode de novo."
            )
        except Exception:  # noqa: BLE001
            falhas += 1
            log.exception("Erro inesperado na etapa '%s'", etapa.nome)

    if falhas:
        log.error("%d etapa(s) falharam.", falhas)
        return 1
    log.info("Concluido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
