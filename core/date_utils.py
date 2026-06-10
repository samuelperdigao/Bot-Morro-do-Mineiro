"""Utilitarios compartilhados para datas no padrao brasileiro."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import TZ_STR

DATE_BR_FORMAT = "%d/%m/%Y"
DATETIME_BR_FORMAT = "%d/%m/%Y %H:%M"
DATETIME_BR_SECONDS_FORMAT = "%d/%m/%Y %H:%M:%S"
DATE_BR_EXAMPLE = "08/06/2026"

BRAZIL_TZ = ZoneInfo(TZ_STR)

_DATE_BR_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def parse_date_br(value: str) -> date:
    """Valida e converte uma data obrigatoriamente em DD/MM/AAAA."""
    normalized = value.strip()
    if not _DATE_BR_RE.fullmatch(normalized):
        raise ValueError("Use o formato DD/MM/AAAA.")
    try:
        return datetime.strptime(normalized, DATE_BR_FORMAT).date()
    except ValueError as exc:
        raise ValueError("Informe uma data valida no formato DD/MM/AAAA.") from exc


def normalize_date_br(value: str) -> str:
    """Valida uma entrada brasileira e devolve sua representacao canonica."""
    return parse_date_br(value).strftime(DATE_BR_FORMAT)


def start_of_week(value: date | datetime) -> date:
    """Retorna a segunda-feira da semana que contem a data informada."""
    value_date = value.date() if isinstance(value, datetime) else value
    return value_date - timedelta(days=value_date.weekday())


def week_id_from_date_br(value: str) -> str:
    """Converte uma data DD/MM/AAAA no week_id ISO da segunda-feira."""
    return start_of_week(parse_date_br(value)).isoformat()


def format_week_range_br(week_id: str) -> str:
    """Formata um week_id como intervalo de segunda-feira a domingo."""
    week_start = date.fromisoformat(week_id)
    week_end = week_start + timedelta(days=6)
    return f"{week_start.strftime(DATE_BR_FORMAT)} a {week_end.strftime(DATE_BR_FORMAT)}"


def _parse_stored_date(value: str) -> date | datetime:
    normalized = value.strip()
    if _DATE_BR_RE.fullmatch(normalized):
        return parse_date_br(normalized)
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return date.fromisoformat(normalized)


def format_date_br(value: date | datetime | str | None, fallback: str = "-") -> str:
    """Formata datas internas ISO ou objetos de data como DD/MM/AAAA."""
    if value is None or value == "":
        return fallback
    parsed = _parse_stored_date(value) if isinstance(value, str) else value
    return parsed.strftime(DATE_BR_FORMAT)


def format_datetime_br(
    value: datetime | str | None,
    *,
    seconds: bool = False,
    fallback: str = "-",
) -> str:
    """Formata data e hora no fuso do bot como DD/MM/AAAA HH:MM[:SS]."""
    if value is None or value == "":
        return fallback
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(BRAZIL_TZ)
    fmt = DATETIME_BR_SECONDS_FORMAT if seconds else DATETIME_BR_FORMAT
    return parsed.strftime(fmt)
