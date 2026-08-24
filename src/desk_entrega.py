"""Taxa de entrega da informação: SAC ⇄ áreas internas (censo sobre `cf_area_pi`).

Pergunta que este módulo responde, por ticket: *a informação pedida à área
voltou?* Nenhum campo estruturado responde isso — `cf_solucao` é a OFERTA
(Diferença Tarifária, Devolução, "Sem Oferta"...) e `status` é estado de fluxo;
nenhum dos dois prova entrega. A resposta só existe no texto das conversas.

Estados (definição do estudo):
- `entregue_no_desk`      há retorno da área registrado no próprio ticket
                          (thread de e-mail de domínio interno ou comentário de
                          outro agente com o conteúdo). Resposta negativa
                          ("não localizado") CONTA como entregue.
- `entregue_fora_do_desk` o SAC repassou a informação ao cliente, mas não há
                          retorno da área no ticket (veio por telefone/
                          WhatsApp/e-mail avulso).
- `nao_entregue`          sem evidência de retorno: silêncio, ou só templates
                          de recebimento.
- `indeterminado`         entrega provável fora do Desk sem rastro que confirme
                          o conteúdo. É o PISO DE INCERTEZA do censo — reportar
                          separado, nunca diluir nos outros.

Classificação em duas passadas, como no desenho do estudo:
1. **Regras** (este módulo, baratas): domínio interno dos e-mails, marcador
   "PENDÊNCIA INTERNA" das macros, direção das threads, comentários entre
   agentes, exclusão de bounces e respostas automáticas.
2. **LLM só nos ambíguos** (`--llm`): quando é preciso ler o texto para saber
   se a resposta contém a informação pedida (ex.: "localizado" vs "seguimos
   verificando").

Calibrado contra casos reais (docs/desk_calibracao.md): #1491212 (retorno da
área no Desk + bounce ao cliente), #1128567 (resposta ao cliente sem retorno
interno), #1128254 (pendência marcada mas nunca disparada), #1352645 (retorno
da área via comentário privado).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ._common import (
    DATA_RAW,
    ErroDeFonte,
    carregar_parquet,
    configurar_log,
    rel,
    salvar_parquet,
)

log = configurar_log("desk_entrega")

RAW_CONVERSAS = DATA_RAW / "zoho_desk" / "conversas"
AMBIGUOS_JSONL = DATA_RAW / "zoho_desk" / "ambiguos.jsonl"

FONTE = "Zoho Desk (SAC Guanabara) — classificação de entrega da informação"

# Domínios das empresas do grupo: e-mail vindo deles é "área interna".
# Ampliável via DESK_DOMINIOS_INTERNOS (lista separada por vírgula).
DOMINIOS_INTERNOS = {
    "expressoguanabara.com.br",
    "viajeguanabara.com.br",
    "util.com.br",
    "realexpresso.com.br",
}
# Endereços do próprio Desk (o SAC): não são "área", são o remetente padrão.
DOMINIOS_DESK = {"zohodesk.com", "expressoguanabara.zohodesk.com"}

RESSALVA_PISO = (
    "PISO DE INCERTEZA: quando a entrega acontece fora do Desk e ninguém "
    "registra o que a área respondeu, nem o texto prova a entrega — esses "
    "casos ficam em `indeterminado` e são reportados separados. O número "
    "'exato' de entrega tem esse piso; declará-lo é parte do método."
)


def _dominios_internos() -> set[str]:
    extras = {
        d.strip().lower()
        for d in os.getenv("DESK_DOMINIOS_INTERNOS", "").split(",")
        if d.strip()
    }
    return DOMINIOS_INTERNOS | extras


# --------------------------------------------------------------------------
# Normalização de texto e e-mail
# --------------------------------------------------------------------------
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_RE_TAGS = re.compile(r"<[^>]+>")


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)
    )


def _norm(texto: str) -> str:
    """minúsculas, sem acento, espaços colapsados — base de todo marcador."""
    return re.sub(r"\s+", " ", sem_acento(texto or "").lower()).strip()


def _texto_plano(html: str) -> str:
    return re.sub(r"\s+", " ", _RE_TAGS.sub(" ", html or "")).strip()


def _emails(campo: str) -> tuple[str, ...]:
    return tuple(m.group(0).lower() for m in _RE_EMAIL.finditer(campo or ""))


def _dominio(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def eh_interno(email: str, dominios: set[str] | None = None) -> bool:
    d = _dominio(email)
    return any(d == dom or d.endswith("." + dom) for dom in (dominios or _dominios_internos()))


def eh_do_desk(email: str) -> bool:
    d = _dominio(email)
    return any(d == dom or d.endswith("." + dom) for dom in DOMINIOS_DESK)


def _tempo(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Modelo de evento (thread ou comentário, na mesma linha do tempo)
# --------------------------------------------------------------------------
@dataclass
class Evento:
    tipo: str  # "thread" | "comentario"
    tempo: datetime
    direcao: str  # "in" | "out" | "" (comentário)
    de: str  # e-mail do remetente/autor (minúsculo; pode ser vazio)
    para: tuple[str, ...] = ()
    autor_tipo: str = ""  # AGENT | END_USER | ""
    eh_descricao: bool = False
    texto: str = ""
    id: str = ""

    def chave_dedupe(self) -> tuple:
        # Threads de e-mail para vários destinatários aparecem duplicadas no
        # Desk (mesmo segundo, mesmo remetente, mesmo texto, ids diferentes) —
        # visto em produção no #1491212.
        return (self.tipo, self.direcao, self.de, self.tempo.replace(microsecond=0),
                _norm(self.texto)[:80])


def normalizar_conversas(itens: list[dict]) -> list[Evento]:
    """Converte o payload de /conversations em eventos ordenados e deduplicados."""
    eventos: list[Evento] = []
    for item in itens:
        if item.get("type") == "comment" or "commenter" in item:
            quem = item.get("commenter") or {}
            tempo = _tempo(item.get("commentedTime") or item.get("modifiedTime"))
            if not tempo:
                continue
            eventos.append(
                Evento(
                    tipo="comentario",
                    tempo=tempo,
                    direcao="",
                    de=(quem.get("email") or "").lower(),
                    autor_tipo=quem.get("type") or "",
                    texto=_texto_plano(item.get("content") or item.get("summary") or ""),
                    id=str(item.get("id", "")),
                )
            )
            continue
        tempo = _tempo(item.get("createdTime"))
        if not tempo:
            continue
        autor = item.get("author") or {}
        de = (autor.get("email") or "").lower()
        # Para thread `in` de remetente externo ao Desk, author.email vem nulo:
        # o campo confiável é fromEmailAddress (visto em produção).
        if not de:
            achados = _emails(item.get("fromEmailAddress", ""))
            de = achados[0] if achados else ""
        eventos.append(
            Evento(
                tipo="thread",
                tempo=tempo,
                direcao=item.get("direction") or "",
                de=de,
                para=_emails(item.get("to", "")) + _emails(item.get("cc", "")),
                autor_tipo=autor.get("type") or "",
                eh_descricao=bool(item.get("isDescriptionThread")),
                texto=_texto_plano(item.get("summary") or item.get("content") or ""),
                id=str(item.get("id", "")),
            )
        )
    vistos: set[tuple] = set()
    unicos = []
    for ev in sorted(eventos, key=lambda e: e.tempo):
        ch = ev.chave_dedupe()
        if ch not in vistos:
            vistos.add(ch)
            unicos.append(ev)
    return unicos


# --------------------------------------------------------------------------
# Marcadores (calibrados nos casos reais; ver docs/desk_calibracao.md)
# --------------------------------------------------------------------------
MARCA_PENDENCIA = "pendencia interna"

_MARCAS_BOUNCE = ("could not be delivered", "mail delivery", "delivery status notification",
                  "undelivered mail", "permanent error")
_REMETENTES_BOUNCE = ("mailer-daemon@", "postmaster@")

_MARCAS_AUTO = ("resposta automatica", "recebemos o seu contato, que gerou o protocolo")

# Pedido interno registrado como comentário entre agentes.
_MARCAS_PEDIDO = ("gentileza", "favor verificar", "por favor verificar", "segue para analise",
                  "solicito ", "poderiam verificar", "podem verificar")

# Conteúdo que carrega a informação pedida (inclui resposta negativa!).
_MARCAS_INFO = (
    "localizado", "localizada", "nao foi localizado", "nao foi localizada",
    "encontrado", "encontrada", "nao consta", "consta em", "identificamos",
    "confirmamos", "informamos que", "houve a sobra", "lancado pedido",
    "estorno ja foi", "sera processado", "foi necessaria", "massiva",
    "segue em anexo", "segue a foto", "segue anexo",
)

# Template de recebimento/espera: NÃO é informação.
_MARCAS_ACK = (
    "resposta automatica", "recebemos o seu contato", "retornaremos em breve",
    "em analise", "seguimos verificando", "estamos verificando",
    "aguarde o retorno", "assim que tivermos um retorno", "prazo de retorno",
    "sua solicitacao foi registrada", "encaminhamos sua solicitacao",
)


def eh_bounce(ev: Evento) -> bool:
    if any(ev.de.startswith(p) for p in _REMETENTES_BOUNCE):
        return True
    t = _norm(ev.texto)
    return any(m in t for m in _MARCAS_BOUNCE)


def eh_auto_resposta(ev: Evento) -> bool:
    t = _norm(ev.texto)
    return any(m in t for m in _MARCAS_AUTO)


def conteudo_informativo(texto: str) -> str:
    """Devolve 'info', 'ack' ou 'incerto' para o texto de uma resposta.

    'info' = contém o que foi pedido (vale resposta negativa: "não localizado").
    'ack'  = só template de recebimento/espera.
    'incerto' = precisa de leitura (fila do LLM).
    """
    t = _norm(texto)
    if not t:
        return "incerto"
    tem_info = any(m in t for m in _MARCAS_INFO)
    tem_ack = any(m in t for m in _MARCAS_ACK)
    if tem_info:
        return "info"
    if tem_ack:
        return "ack"
    return "incerto"


# --------------------------------------------------------------------------
# Classificação por ticket
# --------------------------------------------------------------------------
@dataclass
class Classificacao:
    estado: str
    disparo_no_desk: bool
    canal_da_resposta: str = ""  # "email_interno" | "comentario" | "cliente" | ""
    latencia_disparo_h: float | None = None
    latencia_area_h: float | None = None
    retorno_cliente_falhou: bool = False
    precisa_llm: bool = False
    evidencia: str = ""  # trecho que sustenta a classificação
    evidencia_id: str = ""
    pendencia_llm: dict | None = field(default=None, repr=False)


def _horas(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 2)


def _achar_disparo(eventos: list[Evento], dominios: set[str]) -> Evento | None:
    """Primeiro registro do pedido à área: e-mail interno da macro de pendência,
    e-mail só para endereços do grupo, ou comentário de agente com pedido."""
    for ev in eventos:
        if eh_auto_resposta(ev) or eh_bounce(ev) or ev.eh_descricao:
            continue
        if ev.tipo == "thread" and ev.direcao == "out":
            if MARCA_PENDENCIA in _norm(ev.texto):
                return ev
            if ev.para and all(eh_interno(p, dominios) or eh_do_desk(p) for p in ev.para):
                return ev
        if ev.tipo == "comentario" and ev.autor_tipo == "AGENT":
            if any(m in _norm(ev.texto) for m in _MARCAS_PEDIDO):
                return ev
    return None


def classificar(ticket: dict, eventos: list[Evento]) -> Classificacao:
    """Aplica as regras do estudo à linha do tempo de um ticket."""
    dominios = _dominios_internos()
    criado = _tempo(ticket.get("criado_em")) or (eventos[0].tempo if eventos else None)

    disparo = _achar_disparo(eventos, dominios)
    t0 = disparo.tempo if disparo else criado
    lat_disparo = _horas(criado, disparo.tempo) if (disparo and criado) else None

    resposta_area: Evento | None = None
    resposta_duvidosa: Evento | None = None
    resposta_cliente: Evento | None = None
    houve_bounce = False

    for ev in eventos:
        if ev.eh_descricao or (t0 and ev.tempo < t0) or (disparo and ev.id == disparo.id):
            continue
        if eh_bounce(ev):
            houve_bounce = True
            continue
        if eh_auto_resposta(ev):
            continue
        if ev.tipo == "thread" and ev.direcao == "in":
            if ev.autor_tipo != "END_USER" and eh_interno(ev.de, dominios):
                resposta_area = resposta_area or ev
        elif ev.tipo == "comentario" and ev.autor_tipo == "AGENT":
            if disparo and ev.de and ev.de == disparo.de:
                continue  # o próprio solicitante anotando não é retorno da área
            if any(m in _norm(ev.texto) for m in _MARCAS_PEDIDO):
                continue  # outro pedido, não resposta
            if conteudo_informativo(ev.texto) == "info":
                resposta_area = resposta_area or ev
            else:
                resposta_duvidosa = resposta_duvidosa or ev
        elif ev.tipo == "thread" and ev.direcao == "out":
            if ev.para and any(
                not (eh_interno(p, dominios) or eh_do_desk(p)) for p in ev.para
            ):
                resposta_cliente = resposta_cliente or ev

    if resposta_area is not None:
        return Classificacao(
            estado="entregue_no_desk",
            disparo_no_desk=disparo is not None,
            canal_da_resposta=(
                "email_interno" if resposta_area.tipo == "thread" else "comentario"
            ),
            latencia_disparo_h=lat_disparo,
            latencia_area_h=_horas(t0, resposta_area.tempo) if t0 else None,
            retorno_cliente_falhou=houve_bounce and resposta_cliente is not None,
            evidencia=resposta_area.texto[:280],
            evidencia_id=resposta_area.id,
        )

    if resposta_duvidosa is not None:
        return Classificacao(
            estado="indeterminado",
            disparo_no_desk=disparo is not None,
            canal_da_resposta="comentario",
            latencia_disparo_h=lat_disparo,
            precisa_llm=True,
            evidencia=resposta_duvidosa.texto[:280],
            evidencia_id=resposta_duvidosa.id,
            pendencia_llm={"tipo": "comentario", "texto": resposta_duvidosa.texto[:2000]},
        )

    if resposta_cliente is not None:
        veredito = conteudo_informativo(resposta_cliente.texto)
        if veredito == "info":
            return Classificacao(
                estado="entregue_fora_do_desk",
                disparo_no_desk=disparo is not None,
                canal_da_resposta="cliente",
                latencia_disparo_h=lat_disparo,
                latencia_area_h=_horas(t0, resposta_cliente.tempo) if t0 else None,
                retorno_cliente_falhou=houve_bounce,
                evidencia=resposta_cliente.texto[:280],
                evidencia_id=resposta_cliente.id,
            )
        if veredito == "incerto":
            return Classificacao(
                estado="indeterminado",
                disparo_no_desk=disparo is not None,
                canal_da_resposta="cliente",
                latencia_disparo_h=lat_disparo,
                precisa_llm=True,
                evidencia=resposta_cliente.texto[:280],
                evidencia_id=resposta_cliente.id,
                pendencia_llm={"tipo": "cliente", "texto": resposta_cliente.texto[:2000]},
            )
        # só template de recebimento: não é entrega
    return Classificacao(
        estado="nao_entregue",
        disparo_no_desk=disparo is not None,
        latencia_disparo_h=lat_disparo,
        retorno_cliente_falhou=houve_bounce,
    )


# --------------------------------------------------------------------------
# Passada 2 — LLM só nos ambíguos
# --------------------------------------------------------------------------
_PROMPT_LLM = """Você audita tickets de SAC de uma empresa de ônibus. O SAC pediu \
uma informação a uma área interna e você decide se um texto CONTÉM a informação \
pedida (resposta negativa como "não localizado" CONTA como informação entregue; \
template de recebimento/espera NÃO conta).

Pedido interno registrado no ticket:
{pedido}

Texto a avaliar ({origem}):
{texto}

Responda APENAS um JSON: {{"contem_informacao": "sim"|"nao"|"incerto"}}"""


def resolver_ambiguos_com_llm(pendencias: list[dict]) -> dict[str, str]:
    """Passa os casos ambíguos pelo Claude. Devolve {ticket_id: veredito}.

    Requer ANTHROPIC_API_KEY (ou perfil `ant auth login`). Modelo em
    DESK_LLM_MODEL (padrão claude-opus-5). Sem credencial, ErroDeFonte:
    os ambíguos ficam como `indeterminado`, nunca são chutados.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise ErroDeFonte(
            "Pacote `anthropic` ausente. `pip install anthropic` para usar --llm."
        ) from exc

    cliente = anthropic.Anthropic()
    modelo = os.getenv("DESK_LLM_MODEL", "claude-opus-5")
    vereditos: dict[str, str] = {}
    for i, p in enumerate(pendencias, 1):
        prompt = _PROMPT_LLM.format(
            pedido=p.get("pedido") or "(não registrado; use o assunto: %s)" % p.get("assunto"),
            origem="resposta enviada ao cliente" if p["tipo"] == "cliente"
            else "comentário interno entre agentes",
            texto=p["texto"],
        )
        try:
            resp = cliente.messages.create(
                model=modelo,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            log.warning("LLM falhou no ticket %s (%s); mantido indeterminado", p["ticket_id"], exc)
            continue
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        m = re.search(r'"contem_informacao"\s*:\s*"(sim|nao|não|incerto)"', texto)
        vereditos[p["ticket_id"]] = (m.group(1).replace("não", "nao") if m else "incerto")
        if i % 50 == 0:
            log.info("LLM: %s/%s ambíguos avaliados", i, len(pendencias))
    return vereditos


def _aplicar_veredito(estado_atual: dict, veredito: str) -> str:
    if veredito == "sim":
        return "entregue_no_desk" if estado_atual["canal_da_resposta"] == "comentario" \
            else "entregue_fora_do_desk"
    if veredito == "nao":
        return "nao_entregue"
    return "indeterminado"


# --------------------------------------------------------------------------
# Etapa
# --------------------------------------------------------------------------
def executar(refresh: bool = False, usar_llm: bool = False):
    """Classifica o censo e grava `desk_entrega_classificada` (uma linha/ticket)."""
    import pandas as pd

    tickets, meta_tickets = carregar_parquet("desk_pi_tickets")
    linhas, sem_conversa, fila_llm = [], 0, []

    for t in tickets.to_dict("records"):
        arq = RAW_CONVERSAS / f"{t['ticket_id']}.json"
        if not arq.exists():
            sem_conversa += 1
            continue
        eventos = normalizar_conversas(json.loads(arq.read_text(encoding="utf-8")))
        c = classificar(t, eventos)
        linha = {
            "ticket_id": t["ticket_id"],
            "ticket_numero": t["ticket_numero"],
            "criado_em": t["criado_em"],
            "area": t.get("cf_area_pi") or "(sem área)",
            "assunto": t.get("assunto") or "(sem assunto)",
            "solucao": t.get("cf_solucao"),
            "status": t.get("status"),
            "status_tipo": t.get("status_tipo"),
            "canal": t.get("canal"),
            "estado": c.estado,
            "disparo_no_desk": c.disparo_no_desk,
            "canal_da_resposta": c.canal_da_resposta,
            "latencia_disparo_h": c.latencia_disparo_h,
            "latencia_area_h": c.latencia_area_h,
            "retorno_cliente_falhou": c.retorno_cliente_falhou,
            "precisa_llm": c.precisa_llm,
            "evidencia": c.evidencia,
            "evidencia_id": c.evidencia_id,
        }
        if c.pendencia_llm:
            fila_llm.append(
                {
                    "ticket_id": t["ticket_id"],
                    "pedido": t.get("cf_descricao_area_pi_n2"),
                    "assunto": linha["assunto"],
                    **c.pendencia_llm,
                }
            )
        linhas.append(linha)

    if not linhas:
        raise ErroDeFonte(
            "Nenhum ticket com conversas no cache. Rode a etapa `desk_ingestao` "
            "até completar (ela é resumível)."
        )
    if sem_conversa:
        log.warning(
            "%s tickets do universo ainda sem conversas no cache — fora desta "
            "rodada, NÃO contados como nao_entregue. Complete a ingestão.",
            sem_conversa,
        )

    AMBIGUOS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    AMBIGUOS_JSONL.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in fila_llm), encoding="utf-8"
    )
    log.info("Fila de ambíguos p/ LLM: %s casos (%s)", len(fila_llm), rel(AMBIGUOS_JSONL))

    if usar_llm and fila_llm:
        vereditos = resolver_ambiguos_com_llm(fila_llm)
        for linha in linhas:
            v = vereditos.get(linha["ticket_id"])
            if v:
                linha["estado"] = _aplicar_veredito(linha, v)
                linha["precisa_llm"] = False

    df = pd.DataFrame(linhas)
    obs = RESSALVA_PISO
    if sem_conversa:
        obs += f" ATENÇÃO: parcial — {sem_conversa} tickets do universo sem conversas baixadas."
    salvar_parquet(
        df,
        "desk_entrega_classificada",
        fonte=FONTE,
        url=meta_tickets.url if meta_tickets else "",
        ano_base=meta_tickets.ano_base if meta_tickets else "",
        observacao=obs,
        derivado_de=["desk_pi_tickets"],
    )

    resumo = df["estado"].value_counts(normalize=True).mul(100).round(1)
    log.info("Censo classificado: %s tickets | %s", len(df),
             " · ".join(f"{k} {v}%" for k, v in resumo.items()))
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true",
                    help="resolve os ambíguos com o Claude (requer ANTHROPIC_API_KEY)")
    args = ap.parse_args()
    try:
        executar(usar_llm=args.llm)
    except ErroDeFonte as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
