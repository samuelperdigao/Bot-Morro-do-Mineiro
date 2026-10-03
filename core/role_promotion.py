"""Role promotion helpers."""

from __future__ import annotations

from dataclasses import dataclass

import discord


@dataclass(frozen=True)
class RolePromotionResult:
    promoted: bool
    reason: str


async def promote_role(
    member: discord.Member,
    source_role: discord.Role,
    target_role: discord.Role,
    *,
    reason: str,
) -> RolePromotionResult:
    """Replace source_role with target_role while preserving all other roles."""

    if source_role not in member.roles:
        return RolePromotionResult(False, "source_role_missing")

    bot_member = member.guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return RolePromotionResult(False, "bot_missing_manage_roles")
    if bot_member.top_role <= source_role or bot_member.top_role <= target_role:
        return RolePromotionResult(False, "bot_role_too_low")

    roles = [
        role
        for role in member.roles
        if not role.is_default() and role.id != source_role.id
    ]
    if target_role not in roles:
        roles.append(target_role)

    await member.edit(roles=roles, reason=reason)
    return RolePromotionResult(True, "promoted")
