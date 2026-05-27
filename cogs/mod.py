"""
cogs/mod.py - Comandos de moderação.

/clear → apaga mensagens do canal atual (requer manage_messages)
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("mod", "mod.log")


class ModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="clear", description="Apaga mensagens do canal atual.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(quantidade="Número de mensagens a apagar (1–100)")
    async def clear(
        self,
        interaction: discord.Interaction,
        quantidade: app_commands.Range[int, 1, 100],
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            deletadas = await interaction.channel.purge(limit=quantidade)
            await interaction.followup.send(
                f"✅ {len(deletadas)} mensagem(ns) apagada(s).", ephemeral=True
            )
            log.info(
                f"/clear: {len(deletadas)} msgs apagadas em #{interaction.channel} "
                f"por {interaction.user} (guild {interaction.guild_id})"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Sem permissão para apagar mensagens neste canal.", ephemeral=True
            )
        except Exception as e:
            log.error(f"Erro em /clear: {e}", exc_info=True)
            await interaction.followup.send("❌ Erro ao apagar mensagens.", ephemeral=True)

    @clear.error
    async def clear_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Mensagens** para usar este comando.",
                ephemeral=True,
            )
        else:
            log.error(f"Erro em /clear: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCog(bot))
    log.info("ModCog carregado.")
