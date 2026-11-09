"""
core/money.py - Leitura de valores em reais (padrao brasileiro).

Usado pelo Farm (modais e tickets) para que um mesmo valor digitado seja
interpretado do mesmo jeito em todo o bot.
"""

from __future__ import annotations

import math
import re

MAX_VALOR_DINHEIRO = 1_000_000_000_000  # teto de sanidade: R$ 1 trilhao


def parse_money_br(raw: str | None) -> float:
    """Converte texto em valor monetario no padrao brasileiro.

    Aceita "50000", "50.000", "50.000,50", "R$ 1.500", "1500,5".
    O ponto e separador de milhar; a virgula e separador decimal.
    Um unico ponto seguido de 1 ou 2 digitos (ex.: "50000.0", "1500.50")
    e tratado como decimal, para nao multiplicar valores pre-preenchidos.
    Rejeita inf/nan, notacao cientifica, sinais e valores acima do teto
    com ValueError. Texto vazio vale 0.
    """
    texto = (raw or "").strip().replace("R$", "").replace(" ", "").strip()
    if not texto:
        return 0.0
    if not re.fullmatch(r"[0-9.,]+", texto):
        raise ValueError(f"valor monetario invalido: {raw!r}")
    if "," in texto:
        if texto.count(",") > 1:
            raise ValueError(f"valor monetario invalido: {raw!r}")
        inteiro, decimal = texto.split(",")
        if "." in decimal or len(decimal) > 2:
            raise ValueError(f"valor monetario invalido: {raw!r}")
        normalizado = f"{inteiro.replace('.', '') or '0'}.{decimal or '0'}"
    elif texto.count(".") == 1 and re.fullmatch(r"\d+\.\d{1,2}", texto):
        normalizado = texto
    else:
        normalizado = texto.replace(".", "")
    if not normalizado.strip("."):
        raise ValueError(f"valor monetario invalido: {raw!r}")
    valor = float(normalizado)
    if not math.isfinite(valor) or valor > MAX_VALOR_DINHEIRO:
        raise ValueError(f"valor monetario fora do limite: {raw!r}")
    return valor


def fmt_input_valor(valor) -> str:
    """Formata um valor para pre-preencher um TextInput sem perder escala."""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)
