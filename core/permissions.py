"""
core/permissions.py - Funções de verificação de permissão unificadas.

As funções recebem as listas de cargos como parâmetro (buscadas do banco
pelo chamador via db_get_*_role_ids), sem mais dependência de config estático.
"""

import discord


def has_approver_permission(member: discord.Member, approver_role_ids: list[int]) -> bool:
    """Verifica se o membro pode aprovar/reprovar sets."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    return bool({r.id for r in member.roles} & set(approver_role_ids))


def is_lideranca(member: discord.Member, cargos_lideranca: list[int]) -> bool:
    """Verifica se o membro tem cargo de liderança do farm."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    return bool({r.id for r in member.roles} & set(cargos_lideranca))


def is_permitido_farm(member: discord.Member, cargos_permitidos: list[int]) -> bool:
    """Verifica se o membro pode usar o sistema de farm."""
    if member.guild_permissions.administrator:
        return True
    return bool({r.id for r in member.roles} & set(cargos_permitidos))
