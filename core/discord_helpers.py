"""Pequenos helpers compartilhados para interacoes com o Discord."""

from __future__ import annotations

import logging

import discord

log = logging.getLogger("bot")


async def fetch_channel_safe(
    owner: discord.Client | discord.Guild,
    channel_id: int | str | None,
) -> discord.abc.GuildChannel | discord.Thread | discord.abc.PrivateChannel | None:
    """Busca canal por cache e depois via API, retornando None em falha."""
    if not channel_id:
        return None

    try:
        channel_id_int = int(channel_id)
    except (TypeError, ValueError):
        return None

    channel = owner.get_channel(channel_id_int)
    if channel is not None:
        return channel

    try:
        return await owner.fetch_channel(channel_id_int)
    except (discord.NotFound, discord.Forbidden):
        return None
    except Exception as exc:
        log.warning("Falha ao buscar canal %s: %s", channel_id_int, exc)
        return None


async def respond_ephemeral(interaction: discord.Interaction, content: str, **kwargs) -> None:
    """Responde uma interaction sem quebrar quando ela ja foi respondida."""
    kwargs.setdefault("ephemeral", True)
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)
