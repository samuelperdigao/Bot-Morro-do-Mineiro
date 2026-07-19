"""Comando para postar o painel de solicitacao de set."""

import discord
from discord import app_commands
from discord.ext import commands

from cogs.set_views import SetPanelView
from core.logger import get_logger
from services.db_service import db_is_bot_configured

log = get_logger("bot", "bot.log")


class SetupSetCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup_set", description="Posta o painel de solicitacao de set.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_set(self, interaction: discord.Interaction):
        if not db_is_bot_configured(str(interaction.guild_id)):
            await interaction.response.send_message(
                "Configure o bot primeiro com `/setup_bot`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="Sistema de Set",
            description=(
                "Clique no botao abaixo para solicitar seu set.\n"
                "Preencha o **ID do Jogo** e o **nome** do membro.\n\n"
                "Sua solicitacao sera enviada para aprovacao da lideranca."
            ),
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Use o botao abaixo para iniciar")
        await interaction.channel.send(embed=embed, view=SetPanelView())
        await interaction.followup.send("Painel postado!", ephemeral=True)

    @setup_set.error
    async def setup_set_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Sem permissao para usar este comando.", ephemeral=True)
            return

        log.error("Erro em /setup_set: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send("Erro inesperado.", ephemeral=True)
        else:
            await interaction.response.send_message("Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupSetCog(bot))
