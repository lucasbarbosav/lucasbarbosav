"""Fonte 6 — Zoho Desk (SAC Guanabara): tickets com pendência interna e suas conversas.

Censo, não amostra: baixa TODOS os tickets com `cf_area_pi` preenchido no
período e, para cada um, a lista de conversas (threads + comentários). É a
matéria-prima do estudo de *taxa de entrega da informação* (`desk_entrega.py`).

Duas vias de ingestão:

1. **API do Desk** (padrão): requer OAuth (self client) no `.env` —
   `ZOHO_DESK_CLIENT_ID/SECRET/REFRESH_TOKEN` — ou um `ZOHO_DESK_ACCESS_TOKEN`
   de curta duração. ~42 mil tickets ⇒ ~42 mil chamadas de conversas: o job
   leva horas e por isso é **resumível** — cada ticket baixado vira um JSON em
   `data/raw/zoho_desk/conversas/<ticketId>.json` e não é rebaixado.
2. **Export (Data Backup)**: `--export-dir <dir>` lê um diretório com
   `tickets/*.json` (listas de tickets) e `conversas/<ticketId>.json`.
   Veja `docs/desk_como_obter_acesso.md` para converter o backup do Zoho
   para esse layout.

Limites conhecidos da API (validados em produção):
- `searchTickets` devolve `count` = total de matches e pagina até ~10 mil
  resultados por consulta ⇒ o período é fatiado em janelas mensais, e uma
  janela com mais de 9.500 matches é dividida ao meio recursivamente.
- Busca de campo custom é wildcard/substring; `${notempty}` filtra preenchidos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import requests

from ._common import (
    DATA_RAW,
    ErroDeFonte,
    Limitador,
    Proveniencia,
    agora_iso,
    configurar_log,
    registrar,
    rel,
    salvar_parquet,
)

log = configurar_log("zoho_desk")

RAW_DESK = DATA_RAW / "zoho_desk"
RAW_TICKETS = RAW_DESK / "tickets"
RAW_CONVERSAS = RAW_DESK / "conversas"

ORG_ID_PADRAO = "855775513"  # portal viajeguanabara (produção)
DEPARTAMENTO_SAC = "1003707000000006907"  # SAC principal ("expressoguanabara")

FONTE = "Zoho Desk (SAC Guanabara, portal viajeguanabara)"

# Campos que interessam ao estudo; o resto do payload (enorme) é descartado.
_CF_UTEIS = (
    "cf_area_pi",
    "cf_motivo",
    "cf_submotivo",
    "cf_detalhe_do_motivo",
    "cf_solucao",
    "cf_descricao_area_pi_n2",
    "cf_filial",
)


# --------------------------------------------------------------------------
# Cliente HTTP
# --------------------------------------------------------------------------
class ClienteDesk:
    """Cliente mínimo da API v1 do Zoho Desk: auth, rate limit e retry.

    O token OAuth é renovado sozinho quando expira (self client com refresh
    token). 429 respeita `Retry-After`; 5xx recua exponencialmente.
    """

    def __init__(self) -> None:
        self.base = os.getenv("ZOHO_DESK_BASE_URL", "https://desk.zoho.com/api/v1")
        self.accounts = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
        self.org_id = os.getenv("ZOHO_DESK_ORG_ID", ORG_ID_PADRAO)
        self._client_id = os.getenv("ZOHO_DESK_CLIENT_ID", "")
        self._client_secret = os.getenv("ZOHO_DESK_CLIENT_SECRET", "")
        self._refresh_token = os.getenv("ZOHO_DESK_REFRESH_TOKEN", "")
        self._token = os.getenv("ZOHO_DESK_ACCESS_TOKEN", "")
        if not self._token and not (
            self._client_id and self._client_secret and self._refresh_token
        ):
            raise ErroDeFonte(
                "Sem credencial do Zoho Desk. Preencha no .env ou "
                "ZOHO_DESK_ACCESS_TOKEN (curta duração) ou o trio "
                "ZOHO_DESK_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN (self client). "
                "Passo a passo em docs/desk_como_obter_acesso.md. "
                "Alternativa sem API: exporte o Data Backup e use --export-dir."
            )
        self.sess = requests.Session()
        self.limitador = Limitador(float(os.getenv("ZOHO_DESK_SLEEP_S", "0.75")))

    def _renovar_token(self) -> None:
        if not self._refresh_token:
            raise ErroDeFonte(
                "Access token expirou e não há refresh token para renovar. "
                "Gere outro token ou configure o self client (docs/desk_como_obter_acesso.md)."
            )
        r = self.sess.post(
            f"{self.accounts}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
            },
            timeout=60,
        )
        corpo = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in corpo:
            raise ErroDeFonte(f"Falha ao renovar token OAuth do Zoho ({r.status_code}): {corpo}")
        self._token = corpo["access_token"]
        log.info("Token OAuth renovado (expira em %ss)", corpo.get("expires_in"))

    def get(self, caminho: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET com rate limit, renovação de token e backoff. 204 vira {}."""
        if not self._token:
            self._renovar_token()
        url = f"{self.base}{caminho}"
        tentativas = 0
        while True:
            self.limitador.espera()
            r = self.sess.get(
                url,
                params=params or {},
                headers={"Authorization": f"Zoho-oauthtoken {self._token}", "orgId": self.org_id},
                timeout=120,
            )
            if r.status_code == 204:
                return {}
            if r.status_code == 401 and tentativas == 0:
                tentativas += 1
                self._renovar_token()
                continue
            if r.status_code == 429:
                espera = int(r.headers.get("Retry-After", "60"))
                log.warning("Rate limit (429): aguardando %ss", espera)
                time.sleep(espera)
                continue
            if r.status_code >= 500 and tentativas < 5:
                tentativas += 1
                espera = min(2**tentativas, 60)
                log.warning("HTTP %s em %s: retry em %ss", r.status_code, caminho, espera)
                time.sleep(espera)
                continue
            if r.status_code != 200:
                raise ErroDeFonte(
                    f"Zoho Desk devolveu HTTP {r.status_code} em {caminho}: {r.text[:300]}"
                )
            return r.json()


# --------------------------------------------------------------------------
# Janela temporal fatiada (limite de ~10k resultados por busca)
# --------------------------------------------------------------------------
def _range_iso(ini: date, fim: date) -> str:
    return f"{ini.isoformat()}T00:00:00.000Z,{fim.isoformat()}T23:59:59.999Z"


def _janelas_mensais(ini: date, fim: date) -> Iterator[tuple[date, date]]:
    cursor = ini
    while cursor <= fim:
        prox = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cursor, min(fim, prox - timedelta(days=1))
        cursor = prox


def _contar(cli: ClienteDesk, departamento: str, ini: date, fim: date) -> int:
    resp = cli.get(
        "/tickets/search",
        {
            "departmentId": departamento,
            "customField1": "cf_area_pi:${notempty}",
            "createdTimeRange": _range_iso(ini, fim),
            "limit": 1,
        },
    )
    return int(resp.get("count", 0))


def _paginas_da_janela(
    cli: ClienteDesk, departamento: str, ini: date, fim: date
) -> Iterator[list[dict]]:
    """Pagina uma janela; se estourar o teto da busca, divide ao meio."""
    total = _contar(cli, departamento, ini, fim)
    if total == 0:
        return
    if total > 9500 and fim > ini:
        meio = ini + (fim - ini) / 2
        log.info("Janela %s..%s tem %s tickets: dividindo", ini, fim, total)
        yield from _paginas_da_janela(cli, departamento, ini, meio)
        yield from _paginas_da_janela(cli, departamento, meio + timedelta(days=1), fim)
        return
    if total > 9500:
        raise ErroDeFonte(
            f"Um único dia ({ini}) tem {total} tickets com pendência — acima do teto "
            "da busca do Desk. Use o export (Data Backup) para esse período."
        )
    log.info("Janela %s..%s: %s tickets", ini, fim, total)
    de = 0
    while de < total:
        resp = cli.get(
            "/tickets/search",
            {
                "departmentId": departamento,
                "customField1": "cf_area_pi:${notempty}",
                "createdTimeRange": _range_iso(ini, fim),
                "from": de,
                "limit": 100,
                "sortBy": "createdTime",
            },
        )
        pagina = resp.get("data", [])
        if not pagina:
            return
        yield pagina
        de += len(pagina)


# --------------------------------------------------------------------------
# Normalização do ticket (payload da busca é enorme; guardamos o que importa)
# --------------------------------------------------------------------------
def _resumir_ticket(t: dict) -> dict:
    cf = t.get("cf") or {}
    linha = {
        "ticket_id": str(t.get("id", "")),
        "ticket_numero": str(t.get("ticketNumber", "")),
        "criado_em": t.get("createdTime"),
        "fechado_em": t.get("closedTime"),
        "status": t.get("status"),
        "status_tipo": t.get("statusType"),
        "canal": t.get("channel"),
        "departamento_id": str(t.get("departmentId", "")),
        "n_threads": int(t.get("threadCount") or 0),
        "n_comentarios": int(t.get("commentCount") or 0),
        "arquivado": bool(t.get("isArchived", False)),
    }
    for campo in _CF_UTEIS:
        linha[campo] = cf.get(campo)
    return linha


def assunto_do_ticket(linha: dict) -> str:
    """Assunto no nível em que a série reporta: detalhe do motivo, senão motivo.

    Os contadores fechados do estudo misturam níveis ("Achados e Perdidos" é
    `cf_motivo`; "Categoria inferior" é `cf_detalhe_do_motivo`), e é o detalhe
    que carrega o pedido típico quando existe.
    """
    # NaN do pandas é truthy: só valem strings não vazias.
    for campo in ("cf_detalhe_do_motivo", "cf_motivo"):
        v = linha.get(campo)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "(sem assunto)"


# --------------------------------------------------------------------------
# Ingestão via API
# --------------------------------------------------------------------------
def baixar_tickets(
    cli: ClienteDesk, departamento: str, ini: date, fim: date, *, refresh: bool = False
) -> list[dict]:
    """Baixa (ou lê do cache) as páginas de tickets com `cf_area_pi` preenchido."""
    RAW_TICKETS.mkdir(parents=True, exist_ok=True)
    linhas: list[dict] = []
    vistos: set[str] = set()
    for j_ini, j_fim in _janelas_mensais(ini, fim):
        destino = RAW_TICKETS / f"{j_ini.isoformat()}_{j_fim.isoformat()}.json"
        if destino.exists() and not refresh:
            paginas = json.loads(destino.read_text(encoding="utf-8"))
            log.info("Cache: %s (%s tickets)", rel(destino), sum(len(p) for p in paginas))
        else:
            paginas = list(_paginas_da_janela(cli, departamento, j_ini, j_fim))
            destino.write_text(
                json.dumps(paginas, ensure_ascii=False), encoding="utf-8"
            )
        for pagina in paginas:
            for t in pagina:
                linha = _resumir_ticket(t)
                if linha["ticket_id"] and linha["ticket_id"] not in vistos:
                    vistos.add(linha["ticket_id"])
                    linhas.append(linha)
    return linhas


def baixar_conversas(cli: ClienteDesk, ticket_ids: list[str], *, refresh: bool = False) -> int:
    """Baixa as conversas de cada ticket para o cache em disco. Resumível.

    Devolve quantos tickets foram baixados **nesta rodada** (os já em cache não
    contam). Interrompeu no meio? Rode de novo: só busca o que falta.
    """
    RAW_CONVERSAS.mkdir(parents=True, exist_ok=True)
    pendentes = [t for t in ticket_ids if refresh or not (RAW_CONVERSAS / f"{t}.json").exists()]
    log.info(
        "Conversas: %s tickets no total, %s a baixar (%s em cache)",
        len(ticket_ids), len(pendentes), len(ticket_ids) - len(pendentes),
    )
    baixados = 0
    for i, tid in enumerate(pendentes, 1):
        itens: list[dict] = []
        de = 0
        while True:
            resp = cli.get(f"/tickets/{tid}/conversations", {"from": de, "limit": 100})
            pagina = resp.get("data", [])
            itens.extend(pagina)
            if len(pagina) < 100:
                break
            de += len(pagina)
        (RAW_CONVERSAS / f"{tid}.json").write_text(
            json.dumps(itens, ensure_ascii=False), encoding="utf-8"
        )
        baixados += 1
        if i % 200 == 0:
            log.info("Conversas: %s/%s desta rodada", i, len(pendentes))
    return baixados


# --------------------------------------------------------------------------
# Ingestão via export (Data Backup convertido)
# --------------------------------------------------------------------------
def carregar_export(export_dir: Path) -> list[dict]:
    """Lê `tickets/*.json` de um export convertido (docs/desk_como_obter_acesso.md).

    As conversas do export devem estar em `<export-dir>/conversas/<ticketId>.json`
    e são copiadas para o cache padrão, de onde a classificação as lê.
    """
    dir_tickets = export_dir / "tickets"
    if not dir_tickets.is_dir():
        raise ErroDeFonte(
            f"`{export_dir}` não tem o subdiretório `tickets/`. O export precisa do "
            "layout descrito em docs/desk_como_obter_acesso.md (o Data Backup cru do "
            "Zoho muda de formato entre versões; converta antes)."
        )
    linhas, vistos = [], set()
    for arq in sorted(dir_tickets.glob("*.json")):
        for t in json.loads(arq.read_text(encoding="utf-8")):
            linha = _resumir_ticket(t)
            if linha["ticket_id"] and linha["ticket_id"] not in vistos:
                vistos.add(linha["ticket_id"])
                linhas.append(linha)
    origem = export_dir / "conversas"
    if origem.is_dir():
        RAW_CONVERSAS.mkdir(parents=True, exist_ok=True)
        copiados = 0
        for arq in origem.glob("*.json"):
            destino = RAW_CONVERSAS / arq.name
            if not destino.exists():
                destino.write_bytes(arq.read_bytes())
                copiados += 1
        log.info("Export: %s conversas copiadas para o cache", copiados)
    return linhas


# --------------------------------------------------------------------------
# Etapa
# --------------------------------------------------------------------------
def executar(refresh: bool = False, export_dir: str | None = None):
    """Produz `desk_pi_tickets` (metadados) e povoa o cache de conversas."""
    ini = date.fromisoformat(os.getenv("DESK_JANELA_INICIO", "2026-01-01"))
    fim = date.fromisoformat(os.getenv("DESK_JANELA_FIM", "2026-08-21"))
    departamento = os.getenv("ZOHO_DESK_DEPARTMENT_ID", DEPARTAMENTO_SAC)

    if export_dir:
        linhas = carregar_export(Path(export_dir))
        url = f"export local: {export_dir}"
        origem = "export"
    else:
        cli = ClienteDesk()
        linhas = baixar_tickets(cli, departamento, ini, fim, refresh=refresh)
        n_novas = baixar_conversas(cli, [ln["ticket_id"] for ln in linhas], refresh=refresh)
        url = f"{cli.base}/tickets/search (departmentId={departamento}, cf_area_pi not empty)"
        origem = "rede"
        registrar(
            Proveniencia(
                fonte=FONTE,
                url=f"{cli.base}/tickets/{{id}}/conversations",
                data_extracao=agora_iso(),
                n_registros=n_novas,
                arquivo=rel(RAW_CONVERSAS),
                origem=origem,
                ano_base=f"{ini}..{fim}",
                observacao="conversas baixadas nesta rodada (cache resumível por ticketId)",
            )
        )

    if not linhas:
        raise ErroDeFonte(
            "Nenhum ticket com cf_area_pi no período — confira credencial, "
            "departamento e janela (DESK_JANELA_INICIO/FIM)."
        )

    import pandas as pd

    df = pd.DataFrame(linhas)
    df["assunto"] = df.apply(lambda r: assunto_do_ticket(r.to_dict()), axis=1)
    salvar_parquet(
        df,
        "desk_pi_tickets",
        fonte=FONTE,
        url=url,
        ano_base=f"{ini}..{fim}",
        observacao=(
            "Universo do censo: tickets com cf_area_pi preenchido no departamento "
            f"{departamento}. `cf_solucao` é a OFERTA dada, não prova de entrega "
            "de informação; status/statusType idem."
        ),
    )
    faltam = [
        t for t in df["ticket_id"] if not (RAW_CONVERSAS / f"{t}.json").exists()
    ]
    if faltam:
        log.warning(
            "%s tickets ainda sem conversas no cache — rode de novo para completar "
            "antes da classificação (ela pula e reporta os ausentes).",
            len(faltam),
        )
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="ignora o cache e rebaixa")
    ap.add_argument("--export-dir", help="lê de um export convertido em vez da API")
    args = ap.parse_args()
    try:
        executar(refresh=args.refresh, export_dir=args.export_dir)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
