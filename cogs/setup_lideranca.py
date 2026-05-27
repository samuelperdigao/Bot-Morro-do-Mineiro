"""Comando para postar o painel de lideranca."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.db_service import db_set_guild_config, db_set_system_config
from services.lideranca_service import (
    DEFAULT_LIDERANCA_PANEL_CHANNEL_ID,
    LiderancaPanelView,
    criar_embed_painel_lideranca,
)

log = logging.getLogger("setup_lideranca")


class SetupLiderancaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_lideranca",
        description="Posta o painel de lideranca no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_lideranca(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        target_channel = canal
        if target_channel is None:
            target_channel = interaction.guild.get_channel(DEFAULT_LIDERANCA_PANEL_CHANNEL_ID)
            if target_channel is None:
                try:
                    fetched = await interaction.guild.fetch_channel(DEFAULT_LIDERANCA_PANEL_CHANNEL_ID)
                    if isinstance(fetched, discord.TextChannel):
                        target_channel = fetched
                except Exception:
                    target_channel = None

        if target_channel is None:
            await interaction.followup.send(
                f"Canal do painel nao encontrado: `{DEFAULT_LIDERANCA_PANEL_CHANNEL_ID}`.",
                ephemeral=True,
            )
            return

        msg = await target_channel.send(
            embed=criar_embed_painel_lideranca(),
            view=LiderancaPanelView(),
        )

        db_set_guild_config(
            guild_id,
            painel_lideranca_channel_id=str(target_channel.id),
            painel_lideranca_message_id=str(msg.id),
        )
        db_set_system_config(guild_id, "lideranca", str(target_channel.id), None)

        await interaction.followup.send(
            f"Painel de lideranca postado em {target_channel.mention}.",
            ephemeral=True,
        )
        log.info("Painel lideranca postado em %s (guild %s, msg %s)", target_channel.id, guild_id, msg.id)

    @setup_lideranca.error
    async def _setup_lideranca_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Voce precisa da permissao Gerenciar Servidor.",
                ephemeral=True,
            )
            return

        log.error("Erro no /setup_lideranca: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send("Erro ao postar painel de lideranca.", ephemeral=True)
        else:
            await interaction.response.send_message("Erro ao postar painel de lideranca.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupLiderancaCog(bot))
