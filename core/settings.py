"""Leitura centralizada de configurações por servidor.

Esta camada é deliberadamente compatível com as fontes atuais. Ela prioriza
`system_config`/`guild_config` e mantém os fallbacks legados disponíveis sem
obrigar uma migração de todos os cogs de uma vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from core.config import CANAL_LOG_ENTRADA_ID, CANAL_LOG_PD_ID
from services.db_service import db_get_all_system_configs, db_get_guild_config


LEGACY_FIXED_IDS = MappingProxyType(
    {
        "set_pedir_role": 1474869320659107853,
        "member_folder_manager_role": 1474869320684146841,
        "bau_channel": 1474869322387292357,
        "bau_log_channel": 1499589255784173678,
        "bau_managers_channel": 1502107652027715705,
        "broadcast_category": 1474869322387292362,
        "radio_channel": 1474869321863008296,
        "ranking_category": 1504287738298372216,
        "farm_meta_notice_channel": 1474869321506488447,
        "dashboard_channel": 1494692392052461588,
        "colete_log_channel": 1506880362633236630,
        "leadership_panel_channel": 1506885629181689886,
        "hierarchy_owner_role": 1474869320684146847,
        "hierarchy_vice_role": 1474869320684146846,
        "hierarchy_manager_role": 1490821840191619322,
    }
)

LEGACY_CHANNELS = MappingProxyType(
    {
        "entry_log": CANAL_LOG_ENTRADA_ID,
        "pd_log": CANAL_LOG_PD_ID,
    }
)

_SYSTEM_GUILD_FALLBACKS = MappingProxyType(
    {
        "set": ("approval_channel_id", None),
        "farm": ("canal_avisos_farm", "canal_notificacao_farm"),
        "ausencia": ("canal_ausencias_id", None),
        "encomenda": ("canal_encomendas_id", None),
        "adv": ("canal_adv_id", None),
        "anuncio": ("canal_anuncio_id", None),
        "lideranca": ("painel_lideranca_channel_id", None),
    }
)

_PANEL_FIELDS = MappingProxyType(
    {
        "operacoes": ("painel_operacoes_channel_id", "painel_operacoes_message_id"),
        "set": ("painel_set_channel_id", "painel_set_message_id"),
        "colete": ("painel_colete_channel_id", "painel_colete_message_id"),
        "dashboard": ("dashboard_channel_id", "dashboard_message_id"),
        "ranking": ("painel_ranking_channel_id", "painel_ranking_message_id"),
        "lideranca": ("painel_lideranca_channel_id", "painel_lideranca_message_id"),
        "farm_advertencias": (
            "farm_adv_panel_channel_id",
            "farm_adv_panel_message_id",
        ),
    }
)


def _as_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _split_ids(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    return tuple(int(part.strip()) for part in str(value).split(",") if part.strip())


@dataclass(frozen=True)
class GuildSettings:
    guild_id: str
    guild_config: dict[str, Any]
    systems: dict[str, dict[str, Any]]

    @classmethod
    def from_guild(cls, guild_id: str) -> "GuildSettings":
        systems = {
            str(row["sistema"]): _as_dict(row)
            for row in db_get_all_system_configs(guild_id)
        }
        return cls(guild_id, _as_dict(db_get_guild_config(guild_id)), systems)

    def value(self, field: str, default: Any = None) -> Any:
        return self.guild_config.get(field, default)

    def channel_id(self, system: str, kind: str = "interaction") -> str | None:
        row = self.systems.get(system, {})
        if kind == "log":
            value = row.get("canal_log_id")
        else:
            value = row.get("canal_interacao_id")
        if value:
            return str(value)

        fallback_fields = _SYSTEM_GUILD_FALLBACKS.get(system)
        if fallback_fields:
            field = fallback_fields[1] if kind == "log" else fallback_fields[0]
            if field:
                value = self.guild_config.get(field)
                if value:
                    return str(value)
        return None

    def role_ids(self, field: str) -> tuple[int, ...]:
        return _split_ids(self.guild_config.get(field))

    def panel_reference(self, panel: str) -> tuple[str | None, str | None]:
        fields = _PANEL_FIELDS.get(panel)
        if not fields:
            raise KeyError(f"Painel não configurado: {panel}")
        return tuple(str(self.guild_config[field]) if self.guild_config.get(field) else None for field in fields)

    def fixed_id(self, name: str) -> int | None:
        value = LEGACY_FIXED_IDS.get(name)
        return int(value) if value is not None else None


def get_guild_settings(guild_id: str | int) -> GuildSettings:
    return GuildSettings.from_guild(str(guild_id))


def get_legacy_channel_id(name: str) -> int | None:
    value = LEGACY_CHANNELS.get(name)
    return int(value) if value is not None else None
