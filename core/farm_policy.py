"""Politicas compartilhadas do fluxo de lancamento de farm."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from core.date_utils import BRAZIL_TZ

FarmWeekMembership = Literal["obrigado", "isento_entrada", "fora_da_semana"]

FARM_TICKET_ONLY_MESSAGE = """⚠️ **Sistema atualizado**

O modo antigo de lançamento de farm foi desativado.

A partir de agora, todos os lançamentos devem ser feitos exclusivamente pelo seu ticket individual de farm.

📌 Abra seu ticket no painel de farm e envie seus lançamentos por lá."""


def member_joined_date(member) -> date | None:
    """Retorna a entrada no servidor na data local usada pelo Farm."""
    joined_at = getattr(member, "joined_at", None)
    if not isinstance(joined_at, datetime):
        return None
    if joined_at.tzinfo is not None:
        joined_at = joined_at.astimezone(BRAZIL_TZ)
    return joined_at.date()


def farm_week_membership(member, week_id: str) -> FarmWeekMembership:
    """Classifica se o membro devia participar da semana informada.

    Quem entrou entre segunda e domingo fica isento. Quem entrou depois do fim
    da semana sequer fazia parte dela e tambem nao pode entrar na contagem.
    Quando o Discord nao fornece ``joined_at``, preservamos a obrigacao para
    nao criar uma isencao sem evidencia.
    """
    week_start = date.fromisoformat(week_id)
    week_end = week_start + timedelta(days=6)
    joined_date = member_joined_date(member)
    if joined_date is None or joined_date < week_start:
        return "obrigado"
    if joined_date <= week_end:
        return "isento_entrada"
    return "fora_da_semana"


def member_is_exempt_from_farm(member, week_id: str) -> bool:
    """Indica se a entrada do membro ocorreu dentro da semana de Farm."""
    return farm_week_membership(member, week_id) == "isento_entrada"


def previous_farm_week_id(week_id: str) -> str:
    """Retorna a semana imediatamente encerrada antes da semana informada."""
    return (date.fromisoformat(week_id) - timedelta(days=7)).isoformat()
