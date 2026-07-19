"""
cogs/ausencia.py - Sistema de ausências (multi-server).

Ausências migradas de ausencias.json para a tabela 'ausencias' no SQLite.
Canal de ausências lido da tabela guild_config por guild.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta

from core.logger import get_logger
from core.command_config import is_enabled as _cmd_enabled, get_cog_config as _cog_cfg
from services.log_service import send_log
from services.db_service import (
    db_get_guild_config,
    db_is_ausencia_configured,
    db_ausencia_set,
    db_ausencias_ativos,
    db_ausencias_todos,
    db_ausencia_marcar_avisado,
    db_ausencia_atualizar_message_id,
    db_all_configured_guilds,
)

log = get_logger("ausencia", "ausencia.log")
COR_EMBED = 0xF0A500


class AusenciaModal(discord.ui.Modal, title="📋 Registrar Ausência"):
    dias   = discord.ui.TextInput(
        label="Quantos dias ficará fora?",
        placeholder="Ex: 5  (máximo 7 dias)",
        min_length=1, max_length=1, required=True,
    )
    motivo = discord.ui.TextInput(
        label="Motivo da ausência",
        placeholder="Ex: Viagem, trabalho...",
        style=discord.TextStyle.paragraph,
        max_length=300, required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)

        if not db_is_ausencia_configured(guild_id):
            await interaction.followup.send(
                "❌ O módulo de Ausências não está configurado. Um administrador deve usar `/setup_ausencia`.",
                ephemeral=True,
            )
            return

        if not self.dias.value.strip().isdigit():
            await interaction.followup.send("❌ Digite apenas o número de dias.", ephemeral=True)
            return

        dias_int = int(self.dias.value.strip())
        if dias_int < 1:
            await interaction.followup.send("❌ O número de dias precisa ser pelo menos 1.", ephemeral=True)
            return
        max_dias = _cog_cfg("ausencia").get("max_days", 7)
        if dias_int > max_dias:
            await interaction.followup.send(
                f"❌ Ausências acima de **{max_dias} dias** resultam em **PD automático**.\nEntre em contato com a administração.",
                ephemeral=True,
            )
            return

        motivo_texto = self.motivo.value.strip() or "Não informado"
        alerta_pd    = dias_int > 3
        inicio       = datetime.utcnow()
        fim          = inicio + timedelta(days=dias_int)
        user_id      = str(interaction.user.id)

        dados = {
            "nome":   interaction.user.display_name,
            "dias":   dias_int,
            "motivo": motivo_texto,
            "inicio": inicio.isoformat(),
            "fim":    fim.isoformat(),
            "avisado":    False,
            "message_id": None,
        }
        db_ausencia_set(guild_id, user_id, dados)

        aviso_pd = (
            "\n\n⚠️ **Atenção:** você está no limite. Se ultrapassar **7 dias sem novo aviso**, receberá **PD automático**."
            if alerta_pd else ""
        )

        cfg = db_get_guild_config(guild_id)
        canal_id = int(cfg["canal_ausencias_id"]) if cfg and cfg["canal_ausencias_id"] else None
        canal    = interaction.guild.get_channel(canal_id) if canal_id else None
        if canal is None:
            await interaction.followup.send("❌ Canal de ausências não encontrado. Avise um admin.", ephemeral=True)
            return

        embed = discord.Embed(title="🏖️ Registro de Ausência", color=COR_EMBED, timestamp=inicio)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.description = (
            f"**{interaction.user.display_name}** estará ausente do RP por **{dias_int} dia(s)**." + aviso_pd
        )
        embed.add_field(name="👤 Jogador",   value=interaction.user.mention,        inline=True)
        embed.add_field(name="📅 Dias fora", value=f"`{dias_int} dia(s)`",          inline=True)
        embed.add_field(name="🔙 Retorno",   value=f"`{fim.strftime('%d/%m/%Y')}`", inline=True)
        embed.add_field(name="📝 Motivo",    value=motivo_texto,                    inline=False)
        embed.set_footer(text="Sistema de Ausências • Cidade")

        msg = await canal.send(embed=embed)
        db_ausencia_atualizar_message_id(guild_id, user_id, str(msg.id))
        await interaction.followup.send(f"✅ Ausência registrada! Confira em {canal.mention}.", ephemeral=True)

        log_embed = discord.Embed(
            title="🏖️ Ausência Registrada",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(name="👤 Membro", value=f"{interaction.user.mention}\n`{user_id}`", inline=True)
        log_embed.add_field(name="📅 Dias", value=f"`{dias_int}`", inline=True)
        log_embed.add_field(name="🔙 Retorno", value=f"`{fim.strftime('%d/%m/%Y')}`", inline=True)
        log_embed.add_field(name="📝 Motivo", value=motivo_texto, inline=False)
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Ausência")
        await send_log(interaction.client, interaction.guild, "ausencia", log_embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
        except Exception:
            pass


class AusenciaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 Registrar Ausência",
        style=discord.ButtonStyle.primary,
        custom_id="ausencia_panel:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AusenciaModal())


class Ausencia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.verificar_ausencias.start()

    async def cog_load(self):
        self.bot.add_view(AusenciaPanelView())

    def cog_unload(self):
        self.verificar_ausencias.cancel()

    @app_commands.command(
        name="painel_ausencia",
        description="Posta o painel de registro de ausência. (Apenas admins)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_ausencia_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not db_is_ausencia_configured(guild_id):
            await interaction.response.send_message(
                "❌ Configure o canal de ausências primeiro com `/setup_ausencia`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🏖️ Sistema de Ausência",
            description=(
                "Vai ficar fora da cidade por um tempo?\n\n"
                "Clique no botão abaixo para registrar sua ausência.\n\n"
                "📌 **Regras:**\n"
                "• Ausências de até **3 dias** — registre e fique tranquilo\n"
                "• Ausências de **3 a 7 dias** — registre com atenção ao prazo\n"
                "• **Mais de 7 dias sem aviso** — PD automático aplicado\n\n"
                "Sempre renove seu aviso se precisar de mais tempo."
            ),
            color=COR_EMBED,
        )
        embed.set_footer(text="Sistema de Ausências • Cidade")
        await interaction.channel.send(embed=embed, view=AusenciaPanelView())
        await interaction.followup.send("✅ Painel de ausências postado!", ephemeral=True)

    @setup_ausencia_painel.error
    async def setup_ausencia_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
            return
        log.error("Erro em /painel_ausencia: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    @app_commands.command(name="ausencias", description="Lista todos os jogadores atualmente ausentes.")
    async def listar_ausencias(self, interaction: discord.Interaction):
        if not _cmd_enabled("ausencia"):
            await interaction.response.send_message("❌ Este comando está desativado pela administração.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        if not db_is_ausencia_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo de Ausências não está configurado. Um administrador deve usar `/setup_ausencia`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=False)
        ativos = db_ausencias_ativos(guild_id)
        agora  = datetime.utcnow()
        if not ativos:
            await interaction.followup.send("✅ Nenhum jogador ausente no momento.")
            return
        embed = discord.Embed(title="📋 Jogadores em Ausência", color=COR_EMBED, timestamp=agora)
        embed.set_footer(text="Sistema de Ausências • Cidade")
        for row in ativos:
            fim_dt = datetime.fromisoformat(row["fim"])
            restam = max((fim_dt - agora).days + 1, 0)
            embed.add_field(
                name=f"👤 {row['nome']}",
                value=f"Retorno: `{fim_dt.strftime('%d/%m/%Y')}`\nDias restantes: `{restam}`\nMotivo: {row['motivo']}",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @tasks.loop(hours=1)
    async def verificar_ausencias(self):
        agora = datetime.utcnow()
        for guild_id_str in db_all_configured_guilds():
            if not db_is_ausencia_configured(guild_id_str):
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            todos = db_ausencias_todos(guild_id_str)
            for row in todos:
                if row["avisado"]:
                    continue
                fim_dt = datetime.fromisoformat(row["fim"])
                if agora >= fim_dt:
                    membro = guild.get_member(int(row["user_id"]))
                    if membro:
                        try:
                            await membro.send(
                                f"⏰ **Sua ausência venceu hoje ({fim_dt.strftime('%d/%m/%Y')}).**\n"
                                f"Se precisar de mais tempo, registre uma nova ausência pelo painel.\n"
                                f"Lembre-se: mais de **7 dias sem aviso** resulta em **PD automático**."
                            )
                        except discord.Forbidden:
                            pass
                    db_ausencia_marcar_avisado(guild_id_str, row["user_id"])

    @verificar_ausencias.before_loop
    async def _before_verificar(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Ausencia(bot))
