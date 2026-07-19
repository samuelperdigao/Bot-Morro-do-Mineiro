"""
cogs/encomenda.py - Sistema de Encomendas.

EncomendaPainelView    → painel fixo com botão "📦 Registrar Encomenda"
/setup_encomenda_painel → posta o painel no canal_interacao_id (configurado pelo dashboard)
/encomenda              → abre o modal diretamente (legado)
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from services.log_service import send_log
from services.db_service import (
    db_get_guild_config,
    db_is_encomenda_configured,
    db_get_system_config,
)

log = get_logger("encomenda", "encomenda.log")

COR_ENCOMENDA = discord.Color.from_rgb(230, 126, 34)


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_encomenda_channel(guild: discord.Guild, guild_id: str) -> discord.TextChannel | None:
    """Retorna canal de encomendas: prioriza system_config, depois guild_config."""
    row = db_get_system_config(guild_id, "encomenda")
    if row and row["canal_interacao_id"]:
        ch = guild.get_channel(int(row["canal_interacao_id"]))
        if ch:
            return ch
        try:
            return await guild.fetch_channel(int(row["canal_interacao_id"]))
        except Exception:
            pass

    cfg = db_get_guild_config(guild_id)
    if cfg and cfg["canal_encomendas_id"]:
        ch = guild.get_channel(int(cfg["canal_encomendas_id"]))
        if ch:
            return ch
        try:
            return await guild.fetch_channel(int(cfg["canal_encomendas_id"]))
        except Exception:
            pass

    return None


# ── Modal ─────────────────────────────────────────────────────────────────────

class EncomendaModal(discord.ui.Modal, title="📦 Registrar Encomenda"):
    familia = discord.ui.TextInput(
        label="Família",
        placeholder="Ex: Família Silva",
        max_length=100,
    )
    quantidade = discord.ui.TextInput(
        label="Quantidade",
        placeholder="Ex: 50",
        max_length=20,
    )
    valor = discord.ui.TextInput(
        label="Valor (R$)",
        placeholder="Ex: 1.500,00",
        max_length=30,
    )
    data = discord.ui.TextInput(
        label="Data da Encomenda",
        placeholder=f"Ex: {DATE_BR_EXAMPLE}",
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data_val = normalize_date_br(self.data.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        canal = await _get_encomenda_channel(interaction.guild, guild_id)

        if canal is None:
            await interaction.followup.send(
                "❌ Canal de encomendas não configurado ou não encontrado.\n"
                "Configure pelo **dashboard** ou use `/setup_encomenda`.",
                ephemeral=True,
            )
            return

        registrado_por = interaction.user
        agora = discord.utils.utcnow()

        embed = discord.Embed(
            title="📦 Nova Encomenda Registrada",
            color=COR_ENCOMENDA,
            timestamp=agora,
        )
        embed.set_author(
            name=interaction.guild.name,
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.add_field(name="👨‍👩‍👧‍👦 Família",   value=f"```{self.familia.value}```", inline=False)
        embed.add_field(name="📊 Quantidade",  value=f"`{self.quantidade.value}`",       inline=True)
        embed.add_field(name="💰 Valor",       value=f"`R$ {self.valor.value}`",         inline=True)
        embed.add_field(name="📅 Data",        value=f"`{data_val}`",                    inline=True)
        embed.set_footer(
            text=f"Registrado por {registrado_por.display_name}",
            icon_url=registrado_por.display_avatar.url,
        )

        try:
            await canal.send(embed=embed)
            await interaction.followup.send(
                f"✅ Encomenda registrada com sucesso em {canal.mention}!", ephemeral=True
            )
            log.info(
                "Encomenda registrada por %s (%s) no canal %s — guild %s",
                registrado_por, registrado_por.id, canal.id, interaction.guild_id,
            )

            log_embed = discord.Embed(
                title="📦 Encomenda Registrada",
                color=0xFFD700,
                timestamp=agora,
            )
            log_embed.add_field(name="👤 Membro",      value=f"{registrado_por.mention}\n`{registrado_por.id}`", inline=True)
            log_embed.add_field(name="👨‍👩‍👧‍👦 Família",   value=self.familia.value,   inline=True)
            log_embed.add_field(name="📊 Quantidade",  value=f"`{self.quantidade.value}`", inline=True)
            log_embed.add_field(name="💰 Valor",       value=f"`R$ {self.valor.value}`",   inline=True)
            log_embed.add_field(name="📅 Data",        value=f"`{data_val}`",              inline=True)
            log_embed.set_footer(text="Morro do Mineiro — Sistema de Encomenda")
            await send_log(interaction.client, interaction.guild, "encomenda", log_embed)

        except discord.Forbidden:
            log.warning("Sem permissão para postar no canal %s", canal.id)
            await interaction.followup.send(
                "❌ Sem permissão para postar no canal configurado.", ephemeral=True
            )
        except Exception as e:
            log.error("Erro ao postar encomenda: %s", e, exc_info=True)
            await interaction.followup.send("❌ Erro inesperado ao registrar a encomenda.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no EncomendaModal: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
        except Exception:
            pass


# ── View (painel fixo) ────────────────────────────────────────────────────────

class EncomendaPainelView(discord.ui.View):
    """View persistente do painel de encomendas."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📦 Registrar Encomenda",
        style=discord.ButtonStyle.primary,
        custom_id="encomenda_painel:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EncomendaModal())


# ── Cog ───────────────────────────────────────────────────────────────────────

class EncomendaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(EncomendaPainelView())
        log.info("EncomendaCog inicializado.")

    @app_commands.command(
        name="setup_encomenda_painel",
        description="Posta o painel de encomendas no canal configurado pelo dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_encomenda_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        row = db_get_system_config(guild_id, "encomenda")

        if not row or not row["canal_interacao_id"]:
            await interaction.response.send_message(
                "❌ Canal de encomendas não configurado.\n"
                "Configure o sistema **encomenda** pelo **dashboard** ou use `/setup_encomenda` primeiro.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        canal = interaction.guild.get_channel(int(row["canal_interacao_id"]))
        if canal is None:
            try:
                canal = await interaction.guild.fetch_channel(int(row["canal_interacao_id"]))
            except Exception:
                await interaction.followup.send(
                    "❌ Canal configurado não encontrado. Reconfigure pelo dashboard.", ephemeral=True
                )
                return

        embed = discord.Embed(
            title="📦 Painel de Encomendas",
            description=(
                "Clique no botão abaixo para registrar uma nova encomenda.\n\n"
                "Preencha os dados da família, quantidade, valor e data."
            ),
            color=COR_ENCOMENDA,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Morro do Mineiro — Sistema de Encomendas")
        await canal.send(embed=embed, view=EncomendaPainelView())
        await interaction.followup.send(
            f"✅ Painel de encomendas postado em {canal.mention}!", ephemeral=True
        )
        log.info("Painel de encomendas postado em #%s (guild %s) por %s", canal.name, guild_id, interaction.user)

    @setup_encomenda_painel.error
    async def setup_encomenda_painel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_encomenda_painel: %s", error, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ocorreu um erro.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)

    @app_commands.command(
        name="encomenda",
        description="Registra uma nova encomenda no canal configurado.",
    )
    async def cmd_encomenda(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)

        row = db_get_system_config(guild_id, "encomenda")
        has_system = row and row["canal_interacao_id"]
        has_legacy = db_is_encomenda_configured(guild_id)

        if not has_system and not has_legacy:
            await interaction.response.send_message(
                "❌ O módulo de Encomendas não está configurado.\n"
                "Configure pelo **dashboard** ou use `/setup_encomenda`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(EncomendaModal())

    @cmd_encomenda.error
    async def cmd_encomenda_error(self, interaction: discord.Interaction, error):
        log.error("Erro em /encomenda: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EncomendaCog(bot))
    log.info("EncomendaCog adicionado ao bot.")
