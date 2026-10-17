"""Comando para postar o painel de solicitacao de set."""

import discord
from discord import app_commands
from discord.ext import commands

from ui.views.set import SET_CONTAINER_TEST_CUSTOM_ID, SetContainerPanelView
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

        await interaction.channel.send(
            view=SetContainerPanelView(
                title="Sistema de Set",
                description=(
                    "Clique no botao abaixo para solicitar seu set.\n"
                    "Preencha o **ID do Jogo** e o **nome** do membro.\n\n"
                    "Sua solicitacao sera enviada para aprovacao da lideranca."
                ),
                footer=(
                    "Use o botao abaixo para iniciar\n"
                    f"<t:{int(discord.utils.utcnow().timestamp())}:F>"
                ),
                accent_color=discord.Color.blue(),
            )
        )
        await interaction.response.send_message("Painel postado!", ephemeral=True)

    @app_commands.command(
        name="setup_set_container_teste",
        description="Posta o painel Container de Set em canal de teste.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_set_container_teste(self, interaction: discord.Interaction):
        if not db_is_bot_configured(str(interaction.guild_id)):
            await interaction.response.send_message(
                "Configure o bot primeiro com `/setup_bot`.",
                ephemeral=True,
            )
            return

        await interaction.channel.send(
            view=SetContainerPanelView(custom_id=SET_CONTAINER_TEST_CUSTOM_ID)
        )
        await interaction.response.send_message(
            "Painel Container de teste postado!",
            ephemeral=True,
        )

    @setup_set.error
    async def setup_set_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Sem permissao para usar este comando.", ephemeral=True)
            return

        log.error("Erro em /setup_set: %s", error, exc_info=True)
        await interaction.response.send_message("Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupSetCog(bot))
