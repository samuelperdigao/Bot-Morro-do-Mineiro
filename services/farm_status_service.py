"""Fonte única de status semanal para relatório e fechamento de Farm."""

from __future__ import annotations

from core.farm_policy import (
    farm_week_membership,
    is_farm_manager,
    is_farm_warning_eligible,
    member_joined_date,
)
from services.db_service import (
    db_farm_advertencias_usuario,
    db_farm_ausencia_user_ids,
    db_get_permitidos_role_ids,
    db_ranking_semana,
)


def next_warning_level(guild_id: str, user_id: str) -> int | None:
    """Retorna o próximo nível ou ``None`` quando o membro já está em PD."""
    active_levels = {
        int(row["nivel"])
        for row in db_farm_advertencias_usuario(guild_id, user_id)
        if row["status"] == "ativa"
    }
    if 3 in active_levels:
        return None
    if 2 in active_levels:
        return 3
    if 1 in active_levels:
        return 2
    return 1


def _base_member(member, row: dict | None = None) -> dict:
    row = row or {}
    return {
        "user_id": str(member.id),
        "display_name": member.display_name,
        "classificacao": row.get("classificacao", "zero"),
        "pct": row.get("pct", 0),
    }


def _manager_status(base: dict, absence: bool) -> dict:
    if absence:
        return {**base, "status": "ausente"}
    if base["classificacao"] in {"elite", "meta_batida"}:
        return {**base, "status": "entregou"}
    if base["classificacao"] == "parcial":
        return {**base, "status": "parcial"}
    level = next_warning_level(base["guild_id"], base["user_id"])
    return {**base, "status": "pendente", "nivel": level}


def build_farm_week_snapshot(guild, guild_id: str, week_id: str) -> dict:
    """Classifica os membros vivos da semana com as regras do fechamento.

    Gerentes são retornados em ``gerentes`` e nunca em ``pendentes``. Membros
    que não estão mais no servidor simplesmente não entram no snapshot.
    """
    permitted_role_ids = db_get_permitidos_role_ids(guild_id)
    eligible_members = sorted(
        (
            member
            for member in guild.members
            if is_farm_warning_eligible(member, permitted_role_ids)
        ),
        key=lambda member: member.display_name.casefold(),
    )
    members = []
    isentos: list[dict] = []
    gerentes: list[dict] = []
    for member in eligible_members:
        membership = farm_week_membership(member, week_id)
        if membership == "fora_da_semana":
            continue
        if membership == "isento_entrada":
            joined_date = member_joined_date(member)
            item = {
                "user_id": str(member.id),
                "display_name": member.display_name,
                "joined_date": joined_date.isoformat() if joined_date else "",
                "motivo": "Entrou no servidor durante a semana",
            }
            if is_farm_manager(member):
                gerentes.append({**item, "status": "isento_entrada"})
            else:
                isentos.append(item)
            continue
        members.append(member)

    ranking = {
        str(row["user_id"]): row
        for row in db_ranking_semana(
            guild_id,
            week_id,
            [str(member.id) for member in members],
        )
    }
    absence_ids = db_farm_ausencia_user_ids(guild_id, week_id)
    entregaram: list[dict] = []
    parciais: list[dict] = []
    ausentes: list[dict] = []
    pendentes: list[dict] = []
    obrigados: list[dict] = []

    for member in members:
        user_id = str(member.id)
        base = _base_member(member, ranking.get(user_id))
        if is_farm_manager(member):
            gerentes.append(
                _manager_status(
                    {**base, "guild_id": guild_id},
                    user_id in absence_ids,
                )
            )
            continue

        obrigados.append(base)
        if base["classificacao"] in {"elite", "meta_batida"}:
            entregaram.append(base)
        elif user_id in absence_ids:
            ausentes.append(base)
        elif base["classificacao"] == "parcial":
            parciais.append(base)
        else:
            pendentes.append(
                {
                    **base,
                    "nivel": next_warning_level(guild_id, user_id),
                    "status": "advertir",
                }
            )

    for item in gerentes:
        item.pop("guild_id", None)

    return {
        "guild_id": guild_id,
        "week_id": week_id,
        "obrigados": obrigados,
        "entregaram": entregaram,
        "parciais": parciais,
        "ausentes": ausentes,
        "isentos": isentos,
        "pendentes": pendentes,
        "gerentes": gerentes,
    }
