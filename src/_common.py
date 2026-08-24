"""Infraestrutura comum do pipeline.

Regra de ouro deste projeto: *nenhum numero sem proveniencia*. Todo dado que
entra em `data/clean/` carrega um arquivo `.meta.json` ao lado, e toda extracao
(de rede ou de cache) vira uma linha em `docs/log_extracoes.csv` e um paragrafo
em `docs/fontes.md`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
DATA_RAW = RAIZ / "data" / "raw"
DATA_CLEAN = RAIZ / "data" / "clean"
DOCS = RAIZ / "docs"
CHARTS = RAIZ / "output" / "charts"
DASHBOARD = RAIZ / "output" / "dashboard"

LOG_EXTRACOES = DOCS / "log_extracoes.csv"
FONTES_MD = DOCS / "fontes.md"

for _p in (DATA_RAW, DATA_CLEAN, DOCS, CHARTS, DASHBOARD):
    _p.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "pesquisa-judicializacao-consumo/1.0 "
    "(pipeline academico de dados abertos; contato via repositorio)"
)

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def configurar_log(nome: str) -> logging.Logger:
    """Logger padronizado, um por script de fonte."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(nome)


log = configurar_log("_common")


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def hoje() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------
# Proveniencia
# --------------------------------------------------------------------------
@dataclass
class Proveniencia:
    """Cartao de identidade de um arquivo extraido ou tratado."""

    fonte: str  # nome legivel da fonte (ex.: "consumidor.gov.br (Senacon/MJ)")
    url: str  # URL exata de onde veio
    data_extracao: str  # ISO-8601 com fuso
    n_registros: int  # numero de registros
    arquivo: str  # caminho relativo a raiz do projeto
    origem: str = "rede"  # "rede" ou "cache"
    ano_base: str = ""  # periodo coberto pelos dados (ex.: "2020-2026")
    observacao: str = ""  # limitacoes, filtros aplicados, ressalvas
    sha256: str = ""
    derivado_de: list[str] = field(default_factory=list)

    def rodape(self) -> str:
        """Linha de rodape para gravar no grafico."""
        partes = [f"Fonte: {self.fonte}"]
        if self.ano_base:
            partes.append(f"Ano-base: {self.ano_base}")
        partes.append(f"Extraido em: {self.data_extracao[:10]}")
        return " | ".join(partes)


_LOCK = threading.Lock()

_COLUNAS_LOG = [
    "data_extracao",
    "fonte",
    "url",
    "arquivo",
    "n_registros",
    "origem",
    "ano_base",
    "sha256",
    "observacao",
]


def registrar(prov: Proveniencia) -> Proveniencia:
    """Grava a extracao no log CSV e no `docs/fontes.md`. Idempotente por linha."""
    with _LOCK:
        novo = not LOG_EXTRACOES.exists()
        with LOG_EXTRACOES.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_COLUNAS_LOG, extrasaction="ignore")
            if novo:
                w.writeheader()
            w.writerow({k: v for k, v in asdict(prov).items() if k in _COLUNAS_LOG})

        if not FONTES_MD.exists():
            FONTES_MD.write_text(
                "# Log de fontes\n\n"
                "Registro append-only de toda extracao feita pelo pipeline: fonte, "
                "URL, data de extracao, numero de registros e limitacoes conhecidas.\n"
                "Gerado automaticamente por `src/_common.py`; nao editar as entradas "
                "existentes a mao.\n\n"
                "---\n\n",
                encoding="utf-8",
            )
        with FONTES_MD.open("a", encoding="utf-8") as fh:
            fh.write(
                f"## {prov.fonte} — {prov.data_extracao}\n\n"
                f"- **URL**: {prov.url}\n"
                f"- **Arquivo**: `{prov.arquivo}`\n"
                f"- **Registros**: {prov.n_registros:,}\n".replace(",", ".")
            )
            fh.write(f"- **Origem**: {prov.origem}\n")
            if prov.ano_base:
                fh.write(f"- **Periodo coberto**: {prov.ano_base}\n")
            if prov.sha256:
                fh.write(f"- **SHA-256**: `{prov.sha256[:16]}...`\n")
            if prov.derivado_de:
                fh.write(f"- **Derivado de**: {', '.join(prov.derivado_de)}\n")
            if prov.observacao:
                fh.write(f"- **Observacao**: {prov.observacao}\n")
            fh.write("\n")

    log.info(
        "PROVENIENCIA | %s | %s | %s registros | %s",
        prov.fonte,
        prov.arquivo,
        f"{prov.n_registros:,}".replace(",", "."),
        prov.origem,
    )
    return prov


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def rel(caminho: Path) -> str:
    try:
        return str(caminho.relative_to(RAIZ))
    except ValueError:
        return str(caminho)


# --------------------------------------------------------------------------
# HTTP: sessao, rate limit e retry
# --------------------------------------------------------------------------
class Limitador:
    """Rate limit conservador: garante intervalo minimo entre chamadas."""

    def __init__(self, intervalo_s: float = 1.0) -> None:
        self.intervalo_s = intervalo_s
        self._ultimo = 0.0
        self._lock = threading.Lock()

    def espera(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._ultimo
            if delta < self.intervalo_s:
                time.sleep(self.intervalo_s - delta)
            self._ultimo = time.monotonic()


def sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


class ErroDeFonte(RuntimeError):
    """Falha ao acessar uma fonte. O pipeline para em vez de improvisar dados."""


_RETRY = dict(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((requests.RequestException,)),
    reraise=True,
)


@retry(**_RETRY)
def _get(sess: requests.Session, url: str, timeout: int = 120) -> requests.Response:
    r = sess.get(url, timeout=timeout, stream=True)
    r.raise_for_status()
    return r


@retry(**_RETRY)
def post_json(
    sess: requests.Session,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    r = sess.post(url, json=payload, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def baixar(
    url: str,
    destino: Path,
    fonte: str,
    *,
    refresh: bool = False,
    sess: requests.Session | None = None,
    limitador: Limitador | None = None,
    observacao: str = "",
    ano_base: str = "",
    timeout: int = 300,
) -> tuple[Path, Proveniencia]:
    """Baixa `url` para `destino`, com cache idempotente.

    Se o arquivo ja existe e `refresh` e False, nao rebaixa. Em ambos os casos
    devolve a proveniencia e registra a operacao.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    origem = "cache"

    if refresh or not destino.exists() or destino.stat().st_size == 0:
        if limitador:
            limitador.espera()
        sess = sess or sessao()
        log.info("Baixando %s -> %s", url, rel(destino))
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        try:
            resp = _get(sess, url, timeout=timeout)
            with parcial.open("wb") as fh:
                for bloco in resp.iter_content(chunk_size=1 << 20):
                    fh.write(bloco)
        except requests.RequestException as exc:
            parcial.unlink(missing_ok=True)
            raise ErroDeFonte(
                f"Falha ao baixar {url} ({exc}). "
                "Nao ha substituto sintetico: corrija o acesso e rode de novo."
            ) from exc
        parcial.replace(destino)
        origem = "rede"
    else:
        log.info("Cache: %s (use --refresh para rebaixar)", rel(destino))

    prov = Proveniencia(
        fonte=fonte,
        url=url,
        data_extracao=agora_iso(),
        n_registros=-1,  # contagem so faz sentido depois do parse
        arquivo=rel(destino),
        origem=origem,
        ano_base=ano_base,
        observacao=observacao,
        sha256=_sha256(destino),
    )
    registrar(prov)
    return destino, prov


# --------------------------------------------------------------------------
# Parquet + metadados
# --------------------------------------------------------------------------
def caminho_meta(parquet: Path) -> Path:
    return parquet.with_suffix(".meta.json")


def salvar_parquet(
    df,
    nome: str,
    *,
    fonte: str,
    url: str,
    ano_base: str = "",
    observacao: str = "",
    derivado_de: list[str] | None = None,
) -> tuple[Path, Proveniencia]:
    """Grava `data/clean/<nome>.parquet` + `.meta.json` e registra a proveniencia."""
    destino = DATA_CLEAN / f"{nome}.parquet"
    df.to_parquet(destino, index=False)
    prov = Proveniencia(
        fonte=fonte,
        url=url,
        data_extracao=agora_iso(),
        n_registros=int(len(df)),
        arquivo=rel(destino),
        origem="tratado",
        ano_base=ano_base,
        observacao=observacao,
        sha256=_sha256(destino),
        derivado_de=derivado_de or [],
    )
    caminho_meta(destino).write_text(
        json.dumps(asdict(prov), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    registrar(prov)
    return destino, prov


def carregar_parquet(nome: str):
    """Le um parquet tratado junto com sua proveniencia. Erro claro se faltar."""
    import pandas as pd

    caminho = DATA_CLEAN / f"{nome}.parquet"
    if not caminho.exists():
        raise ErroDeFonte(
            f"`{rel(caminho)}` nao existe. Rode a etapa que o produz "
            f"(`python run_all.py --etapas ...`) antes desta."
        )
    meta_path = caminho_meta(caminho)
    meta = (
        Proveniencia(**json.loads(meta_path.read_text(encoding="utf-8")))
        if meta_path.exists()
        else None
    )
    return pd.read_parquet(caminho), meta


def existe_limpo(nome: str) -> bool:
    return (DATA_CLEAN / f"{nome}.parquet").exists()
