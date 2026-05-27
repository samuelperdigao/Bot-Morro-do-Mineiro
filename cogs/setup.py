"""
cogs/setup.py - Comandos de configuração por guild.

/setup_bot     → configura sistema de Set (canais, categoria, cargos)
/setup_farm    → configura módulo Farm (cargos, canais de aviso/notificação)
/setup_ausencia → configura módulo de Ausências (canal)

Todos exigem permissão manage_guild.
Na primeira execução de /setup_bot, migra automaticamente dados de JSON legado.
"""

import re

import discord
from discord import app_commands
from discord.ext import commands

from core.config import CHANNEL_MAP_FILE, AUSENCIAS_FILE
from core.logger import get_logger
from services.db_service import (
    db_set_guild_config,
    db_get_guild_config,
    db_migrate_from_json,
)

log = get_logger("setup", "setup.log")


def _parse_ids(text: str) -> list[int]:
    """Extrai IDs de Discord (17-20 dígitos) de uma string com IDs ou menções."""
    return [int(m) for m in re.findall(r"\d{17,20}", text)]


def _ids_para_str(ids: list[int]) -> str:
    return ",".join(str(i) for i in ids)


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup_bot ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="setup_bot",
        description="Configura o sistema de Set: canais, categoria privada e cargos.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal_aprovacao="Canal onde as solicitações de set serão enviadas para análise",
        canal_log="Canal de log do sistema (registros de aprovação/reprovação)",
        categoria_privada="Categoria onde os canais privados dos membros serão criados",
        cargo_membro="Cargo atribuído automaticamente ao membro com set aprovado",
        cargos_aprovadores="IDs ou menções dos cargos que podem aprovar sets (separados por vírgula)",
    )
    async def setup_bot(
        self,
        interaction: discord.Interaction,
        canal_aprovacao: discord.TextChannel,
        canal_log: discord.TextChannel,
        categoria_privada: discord.CategoryChannel,
        cargo_membro: discord.Role,
        cargos_aprovadores: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        aprovadores_ids = _parse_ids(cargos_aprovadores) if cargos_aprovadores else []

        db_set_guild_config(
            guild_id,
            approval_channel_id=str(canal_aprovacao.id),
            log_channel_id=str(canal_log.id),
            private_category_id=str(categoria_privada.id),
            member_role_id=str(cargo_membro.id),
            approver_role_ids=_ids_para_str(aprovadores_ids),
        )
        log.info(f"setup_bot executado para guild {guild_id} por {interaction.user}")

        # Migração automática de dados legados (não-destrutiva)
        migrados_cm, migrados_au = db_migrate_from_json(guild_id, CHANNEL_MAP_FILE, AUSENCIAS_FILE)

        aprovadores_txt = (
            " ".join(f"<@&{i}>" for i in aprovadores_ids) if aprovadores_ids else "*(nenhum definido)*"
        )

        embed = discord.Embed(
            title="✅ Setup do Bot Concluído",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📨 Canal de Aprovação", value=canal_aprovacao.mention, inline=True)
        embed.add_field(name="📋 Canal de Log",        value=canal_log.mention,       inline=True)
        embed.add_field(name="📁 Categoria Privada",   value=categoria_privada.mention, inline=True)
        embed.add_field(name="🎖️ Cargo Membro",        value=cargo_membro.mention,    inline=True)
        embed.add_field(name="✅ Cargos Aprovadores",  value=aprovadores_txt,         inline=False)

        if migrados_cm or migrados_au:
            embed.add_field(
                name="📦 Migração de dados legados",
                value=f"`{migrados_cm}` entradas de channel_map | `{migrados_au}` ausências",
                inline=False,
            )

        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_bot.error
    async def setup_bot_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_bot: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    # ── /setup_farm ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="setup_farm",
        description="Configura o módulo Farm: cargos e canais de aviso/notificação.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        cargos_lideranca="IDs ou menções dos cargos de liderança do farm (separados por vírgula)",
        cargos_permitidos="IDs ou menções dos cargos que podem usar /farm (separados por vírgula)",
        canal_avisos="Canal de avisos gerais do farm (ranking, aprovações)",
        canal_notificacao="Canal onde a notificação de meta concluída é enviada (opcional, usa canal_avisos se omitido)",
    )
    async def setup_farm(
        self,
        interaction: discord.Interaction,
        cargos_lideranca: str,
        cargos_permitidos: str,
        canal_avisos: discord.TextChannel,
        canal_notificacao: discord.TextChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        lideranca_ids  = _parse_ids(cargos_lideranca)
        permitidos_ids = _parse_ids(cargos_permitidos)

        if not lideranca_ids:
            await interaction.followup.send("❌ Informe ao menos um cargo de liderança.", ephemeral=True)
            return
        if not permitidos_ids:
            await interaction.followup.send("❌ Informe ao menos um cargo permitido no farm.", ephemeral=True)
            return

        canal_notif_id = str(canal_notificacao.id) if canal_notificacao else str(canal_avisos.id)

        db_set_guild_config(
            guild_id,
            cargos_lideranca_farm=_ids_para_str(lideranca_ids),
            cargos_permitidos_farm=_ids_para_str(permitidos_ids),
            canal_avisos_farm=str(canal_avisos.id),
            canal_notificacao_farm=canal_notif_id,
        )
        log.info(f"setup_farm executado para guild {guild_id} por {interaction.user}")

        lideranca_txt  = " ".join(f"<@&{i}>" for i in lideranca_ids)
        permitidos_txt = " ".join(f"<@&{i}>" for i in permitidos_ids)
        notif_mention  = canal_notificacao.mention if canal_notificacao else f"{canal_avisos.mention} *(mesmo canal de avisos)*"

        embed = discord.Embed(
            title="✅ Setup do Farm Concluído",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="👑 Cargos Liderança",    value=lideranca_txt,     inline=False)
        embed.add_field(name="🌿 Cargos Permitidos",   value=permitidos_txt,    inline=False)
        embed.add_field(name="📢 Canal de Avisos",     value=canal_avisos.mention, inline=True)
        embed.add_field(name="🔔 Canal de Notificação", value=notif_mention,    inline=True)
        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_farm.error
    async def setup_farm_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_farm: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    # ── /setup_ausencia ───────────────────────────────────────────────────────

    @app_commands.command(
        name="setup_ausencia",
        description="Configura o módulo de Ausências: define o canal onde os registros são postados.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal onde as ausências registradas serão publicadas",
    )
    async def setup_ausencia(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        db_set_guild_config(guild_id, canal_ausencias_id=str(canal.id))
        log.info(f"setup_ausencia executado para guild {guild_id} por {interaction.user}")

        embed = discord.Embed(
            title="✅ Setup de Ausências Concluído",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="🏖️ Canal de Ausências", value=canal.mention, inline=False)
        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_ausencia.error
    async def setup_ausencia_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_ausencia: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    # ── /setup_encomenda ──────────────────────────────────────────────────────

    @app_commands.command(
        name="setup_encomenda",
        description="Configura o módulo de Encomendas: define o canal onde os registros são postados.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        canal="Canal onde as encomendas registradas serão publicadas",
    )
    async def setup_encomenda(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        db_set_guild_config(guild_id, canal_encomendas_id=str(canal.id))
        log.info(f"setup_encomenda executado para guild {guild_id} por {interaction.user}")

        embed = discord.Embed(
            title="✅ Setup de Encomendas Concluído",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📦 Canal de Encomendas", value=canal.mention, inline=False)
        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_encomenda.error
    async def setup_encomenda_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Apenas administradores podem usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_encomenda: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    # ── /setup_log_saida ──────────────────────────────────────────────────────

    @app_commands.command(
        name="setup_log_saida",
        description="Configura o canal onde os logs de saída de membros serão postados.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal onde os embeds de saída de membros serão publicados",
    )
    async def setup_log_saida(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        db_set_guild_config(guild_id, canal_log_saida_id=str(canal.id))
        log.info(f"setup_log_saida executado para guild {guild_id} por {interaction.user}")

        embed = discord.Embed(
            title="✅ Setup de Log de Saída Concluído",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📤 Canal de Log de Saída", value=canal.mention, inline=False)
        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_log_saida.error
    async def setup_log_saida_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_log_saida: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    # ── /config_ver ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="config_ver",
        description="Exibe a configuração atual do bot neste servidor.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_ver(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cfg = db_get_guild_config(guild_id)

        embed = discord.Embed(
            title="⚙️ Configuração do Servidor",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        def _ch(val):
            return f"<#{val}>" if val else "❌ Não configurado"

        def _role(val):
            return f"<@&{val}>" if val else "❌ Não configurado"

        def _roles(val):
            if not val:
                return "❌ Não configurado"
            return " ".join(f"<@&{i}>" for i in val.split(",") if i.strip())

        if not cfg:
            embed.description = "❌ Este servidor ainda não foi configurado.\nUse `/setup_bot` para começar."
        else:
            embed.add_field(name="**— Sistema de Set —**", value="\u200b", inline=False)
            embed.add_field(name="Canal de Aprovação",  value=_ch(cfg["approval_channel_id"]),    inline=True)
            embed.add_field(name="Canal de Log",        value=_ch(cfg["log_channel_id"]),          inline=True)
            embed.add_field(name="Categoria Privada",   value=_ch(cfg["private_category_id"]),     inline=True)
            embed.add_field(name="Cargo Membro",        value=_role(cfg["member_role_id"]),        inline=True)
            embed.add_field(name="Cargos Aprovadores",  value=_roles(cfg["approver_role_ids"]),    inline=False)

            embed.add_field(name="**— Farm —**", value="\u200b", inline=False)
            embed.add_field(name="Cargos Liderança",    value=_roles(cfg["cargos_lideranca_farm"]),  inline=False)
            embed.add_field(name="Cargos Permitidos",   value=_roles(cfg["cargos_permitidos_farm"]), inline=False)
            embed.add_field(name="Canal de Avisos",     value=_ch(cfg["canal_avisos_farm"]),          inline=True)
            embed.add_field(name="Canal Notificação",   value=_ch(cfg["canal_notificacao_farm"]),     inline=True)

            embed.add_field(name="**— Ausências —**", value="\u200b", inline=False)
            embed.add_field(name="Canal de Ausências",  value=_ch(cfg["canal_ausencias_id"]),       inline=True)

            embed.add_field(name="**— Encomendas —**", value="\u200b", inline=False)
            embed.add_field(name="Canal de Encomendas", value=_ch(cfg["canal_encomendas_id"]),      inline=True)

            embed.add_field(name="**— Log de Saída —**", value="\u200b", inline=False)
            embed.add_field(name="Canal de Log de Saída", value=_ch(cfg["canal_log_saida_id"]),     inline=True)

        embed.set_footer(text=f"Guild ID: {guild_id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_ver.error
    async def config_ver_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
    log.info("SetupCog carregado.")
