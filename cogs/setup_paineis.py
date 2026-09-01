"""
Comandos para postar os painéis nos canais.
"""

import discord
from discord.ext import commands
from discord import app_commands
from services.db_service import db_is_bot_configured, db_set_guild_config
from services.paineis_service import (
    PainelOperacoesView,
    PainelSetView,
    criar_embed_painel_operacoes,
    criar_embed_painel_set,
    painel_set_logo_file,
)
import logging

log = logging.getLogger("setup_paineis")


class SetupPaineisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_painel_operacoes",
        description="Posta o painel de operações neste canal.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_painel_operacoes(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)

        configurado = db_is_bot_configured(guild_id)

        if not configurado:
            await interaction.response.send_message(
                "❌ Configure o bot primeiro com `/setup_bot`.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            msg_ops = await interaction.channel.send(
                embed=criar_embed_painel_operacoes(),
                view=PainelOperacoesView(),
            )

            db_set_guild_config(
                guild_id,
                painel_operacoes_channel_id=str(interaction.channel_id),
                painel_operacoes_message_id=str(msg_ops.id),
            )

            log.info("Painel de operações postado no canal %s (guild %s)", interaction.channel_id, guild_id)
            await interaction.followup.send("✅ Painel de operações postado com sucesso!", ephemeral=True)

        except Exception as e:
            log.error("Erro em setup_painel_operacoes: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Erro: {type(e).__name__}: {e}", ephemeral=True)

    @setup_painel_operacoes.error
    async def _erro_setup_ops(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro em /setup_painel_operacoes: %s", error, exc_info=True)
            await interaction.response.send_message(f"❌ Erro inesperado: {error}", ephemeral=True)

    @app_commands.command(
        name="setup_painel_set",
        description="Posta apenas o painel de set neste canal.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_painel_set(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)

        configurado = db_is_bot_configured(guild_id)

        if not configurado:
            await interaction.response.send_message(
                "❌ Configure o bot primeiro com `/setup_bot`.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            logo = painel_set_logo_file()
            msg = await interaction.channel.send(
                embed=criar_embed_painel_set(),
                view=PainelSetView(),
                **({"file": logo} if logo else {}),
            )

            db_set_guild_config(
                guild_id,
                painel_set_channel_id=str(interaction.channel_id),
                painel_set_message_id=str(msg.id),
            )

            log.info("Painel de set postado no canal %s (guild %s)", interaction.channel_id, guild_id)
            await interaction.followup.send("✅ Painel de set postado com sucesso!", ephemeral=True)

        except Exception as e:
            log.error("Erro em setup_painel_set: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Erro: {type(e).__name__}: {e}", ephemeral=True)

    @setup_painel_set.error
    async def _erro_setup_set(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro em /setup_painel_set: %s", error, exc_info=True)
            await interaction.response.send_message(f"❌ Erro inesperado: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupPaineisCog(bot))
