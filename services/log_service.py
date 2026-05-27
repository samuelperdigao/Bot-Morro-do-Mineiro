"""
services/log_service.py - Funcao central de envio de logs para canais configurados.
"""

import logging

import discord

log = logging.getLogger("bot")


async def send_log(
    bot,
    guild: discord.Guild,
    sistema: str,
    embed: discord.Embed,
    files: list[discord.File] | None = None,
    fallback_channel_id: int | str | None = None,
) -> bool:
    """Envia embed de log no canal configurado para o sistema."""
    from services.db_service import db_get_system_config

    channel_ids = []
    row = db_get_system_config(str(guild.id), sistema)
    if row and row["canal_log_id"]:
        channel_ids.append(int(row["canal_log_id"]))
    if fallback_channel_id and int(fallback_channel_id) not in channel_ids:
        channel_ids.append(int(fallback_channel_id))

    if not channel_ids:
        log.info("send_log [%s] sem canal configurado (guild %s)", sistema, guild.id)
        return False

    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except Exception as e:
                log.warning("Canal de log %s nao encontrado (sistema=%s): %s", channel_id, sistema, e)
                continue

        try:
            await channel.send(embed=embed, files=files or [])
            return True
        except Exception as e:
            log.error("Erro ao enviar log (sistema=%s, canal=%s): %s", sistema, channel_id, e)

    return False
