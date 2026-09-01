"""Helpers for synchronizing Discord role permissions."""

from __future__ import annotations

from dataclasses import dataclass, field

import discord


@dataclass
class RoleSyncResult:
    copied_overwrites: int = 0
    removed_overwrites: int = 0
    unchanged_channels: int = 0
    failed_channels: list[str] = field(default_factory=list)
    moved: bool = False


def find_role_by_names(
    guild: discord.Guild,
    names: tuple[str, ...],
) -> discord.Role | None:
    """Find a role ignoring case, whitespace, and an optional leading pipe."""

    expected = {normalize_role_name(name) for name in names}
    return next(
        (role for role in guild.roles if normalize_role_name(role.name) in expected),
        None,
    )


def normalize_role_name(name: str) -> str:
    normalized = name.strip()
    while normalized and not normalized[0].isalnum():
        normalized = normalized[1:].lstrip()
    return normalized.casefold()


def _overwrite_for_role(
    channel: discord.abc.GuildChannel,
    role: discord.Role,
) -> discord.PermissionOverwrite | None:
    for target, overwrite in channel.overwrites.items():
        if getattr(target, "id", None) == role.id:
            return overwrite
    return None


def _position_immediately_below(source: discord.Role, target: discord.Role) -> int | None:
    if target.position == source.position - 1:
        return None
    if target.position > source.position:
        return source.position
    return source.position - 1


async def sync_role_permissions(
    guild: discord.Guild,
    source: discord.Role,
    target: discord.Role,
    *,
    reason: str,
    disable_invites: bool = False,
) -> RoleSyncResult:
    """Copy guild permissions, channel overwrites, and role position."""

    result = RoleSyncResult()
    permissions = discord.Permissions(source.permissions.value)
    if disable_invites:
        permissions.create_instant_invite = False
        await source.edit(permissions=permissions, reason=reason)

    await target.edit(
        permissions=permissions,
        reason=reason,
    )

    for channel in guild.channels:
        source_overwrite = _overwrite_for_role(channel, source)
        target_overwrite = _overwrite_for_role(channel, target)

        try:
            if disable_invites:
                source_overwrite = source_overwrite or discord.PermissionOverwrite()
                source_overwrite.create_instant_invite = False
                await channel.set_permissions(
                    source,
                    overwrite=source_overwrite,
                    reason=reason,
                )

            if source_overwrite is not None:
                allow, deny = source_overwrite.pair()
                overwrite_copy = discord.PermissionOverwrite.from_pair(allow, deny)
                await channel.set_permissions(target, overwrite=overwrite_copy, reason=reason)
                result.copied_overwrites += 1
            elif target_overwrite is not None:
                await channel.set_permissions(target, overwrite=None, reason=reason)
                result.removed_overwrites += 1
            else:
                result.unchanged_channels += 1
        except (discord.Forbidden, discord.HTTPException) as exc:
            result.failed_channels.append(f"{channel.name}: {exc}")

    new_position = _position_immediately_below(source, target)
    if new_position is not None:
        await guild.edit_role_positions(
            positions={target: new_position},
            reason=reason,
        )
        result.moved = True

    return result
