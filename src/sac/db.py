"""Banco SQLite da extração de atributos do SAC (Zoho Desk).

Quatro tabelas analíticas + livro-razão de retomada:

- atributos      uma linha por ticket, schema achatado (sem PII)
- extracao_raw   JSON bruto devolvido pela extração + evidência (pós-varredura de PII)
- erros          ticket_id, etapa, mensagem — um ticket que falha nunca derruba o run
- processados    livro-razão: quem já foi processado, por tema, com timestamp
- chave          ticket_id -> hash salgado do contato (fica FORA da tabela analítica;
                 arquivo local, nunca versionado)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

CAMINHO_DB = Path(__file__).resolve().parents[2] / "data" / "raw" / "sac" / "sac.db"

DDL = """
CREATE TABLE IF NOT EXISTS atributos (
    ticket_id TEXT PRIMARY KEY,
    ticket_number TEXT,
    tema TEXT NOT NULL,
    -- contexto (estruturado, nao-PII)
    empresa TEXT,
    motivo TEXT, submotivo TEXT, detalhe_motivo TEXT,
    canal TEXT,
    created_time TEXT, mes TEXT,
    status TEXT, status_type TEXT, classification TEXT,
    thread_count INTEGER, comment_count INTEGER,
    -- impacto ao passageiro (extraido do texto)
    categoria_comprada TEXT, categoria_viajada TEXT,
    trecho_origem_destino TEXT,
    duracao_interrupcao_faixa TEXT,
    troca_de_veiculo TEXT, retido_rodovia_terminal TEXT,
    perda_de_conexao TEXT, viagem_concluida TEXT,
    atraso_chegada_horas REAL,
    gasto_comprovado TEXT, hospedagem_necessaria TEXT,
    -- controlavel pelo SAC
    qualidade_informacao_ocorrencia TEXT,
    tempo_ate_primeira_resposta_h REAL,
    passou_por_pendencia_interna TEXT,
    area_destino TEXT,
    houve_retorno_da_area TEXT,
    -- oferta: os dois lados
    oferta_campo TEXT,
    oferta_texto TEXT,
    oferta_valor_texto TEXT,
    divergencia_campo_texto INTEGER,
    -- sinais expressos no atendimento (pre-desfecho, permitidos)
    mencionou_advogado TEXT, mencionou_procon TEXT,
    mencionou_processo_ou_danos_morais TEXT,
    mencionou_reclame_aqui_ou_consumidorgov TEXT,
    tom_ameaca_juridica TEXT,
    -- reincidencia (computada do historico, conhecivel na hora)
    cliente_reincidente_janela INTEGER,
    -- proveniencia e qualidade
    extracao_confianca TEXT,
    campos_ausentes TEXT,          -- JSON: lista dos campos nao_informado
    leak_mention INTEGER DEFAULT 0 -- so para excluir texto; NUNCA feature
);

CREATE TABLE IF NOT EXISTS extracao_raw (
    ticket_id TEXT PRIMARY KEY,
    json_bruto TEXT NOT NULL,      -- saida integral da extracao, pos-scrub de PII
    evidencia TEXT                 -- JSON: {campo: trecho <=15 palavras}, pos-scrub
);

CREATE TABLE IF NOT EXISTS erros (
    ticket_id TEXT,
    etapa TEXT,
    mensagem TEXT,
    quando TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processados (
    ticket_id TEXT PRIMARY KEY,
    tema TEXT,
    quando TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chave (
    ticket_id TEXT PRIMARY KEY,
    contato_hash TEXT              -- sha256(salt + contactId/cpf/email); local, nao versionado
);
"""


def conectar(caminho: Path | str = CAMINHO_DB) -> sqlite3.Connection:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.executescript(DDL)
    return con


def ja_processados(con: sqlite3.Connection, tema: str) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT ticket_id FROM processados WHERE tema = ?", (tema,))}


def registrar_erro(con: sqlite3.Connection, ticket_id: str, etapa: str, msg: str) -> None:
    con.execute("INSERT INTO erros (ticket_id, etapa, mensagem) VALUES (?,?,?)",
                (ticket_id, etapa, msg[:2000]))
