"""Varredura de PII em texto livre antes de persistir (LGPD, Seção 9 do plano).

Aplicada a TODO texto que entra nas tabelas analíticas (evidencia, oferta_texto,
json_bruto). Regra: na dúvida, redigir. O dado bruto continua no Zoho; aqui só
persiste o que sustenta a análise.
"""
from __future__ import annotations

import re

_PADROES: list[tuple[re.Pattern[str], str]] = [
    # CPF: 000.000.000-00 ou 11 dígitos corridos
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF redigido]"),
    # e-mail
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[e-mail redigido]"),
    # telefone BR: (00) 90000-0000 e variantes com 10-11 dígitos
    (re.compile(r"(?<!\d)(?:\(?\d{2}\)?\s?)?9?\d{4}[- ]?\d{4}(?!\d)"), "[telefone redigido]"),
    # conta/cartao/agencia: sequencias longas de dígitos (8+) possivelmente com separadores
    (re.compile(r"\b\d[\d .-]{7,}\d\b"), "[número redigido]"),
]


def redigir_pii(texto: str | None) -> str | None:
    if not texto:
        return texto
    for padrao, marca in _PADROES:
        texto = padrao.sub(marca, texto)
    return texto
