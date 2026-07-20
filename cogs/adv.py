"""
cogs/adv.py - Sistema de Advertências.

AdvPainelView       → painel fixo com botão "⚠️ Aplicar Advertência"
AdvMemberSelectView → UserSelect ephemeral para escolher o membro
AdvModal            → modal com descrição e dias
/setup_adv_painel   → posta o painel no canal_interacao_id (configurado pelo dashboard)
/adv @membro        → abre AdvModal diretamente (legado)
/setup-adv          → configura canal via parâmetro (legado)
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import (
    db_get_guild_config,
    db_set_guild_config,
    db_get_system_config,
)
from services.log_service import send_log

log = get_logger(__name__)

COR_ADV = 0xFF4444


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_adv_channel(guild: discord.Guild, guild_id: str) -> discord.TextChannel | None:
    """Retorna canal de advertências: prioriza system_config, depois guild_config."""
    row = db_get_system_config(guild_id, "adv")
    if row and row["canal_interacao_id"]:
        ch = guild.get_channel(int(row["canal_interacao_id"]))
        if ch:
            return ch
        try:
            return await guild.fetch_channel(int(row["canal_interacao_id"]))
        except Exception:
            pass

    cfg = db_get_guild_config(guild_id)
    if cfg and cfg["canal_adv_id"]:
        ch = guild.get_channel(int(cfg["canal_adv_id"]))
        if ch:
            return ch
        try:
            return await guild.fetch_channel(int(cfg["canal_adv_id"]))
        except Exception:
            pass

    return None


# ── Modal ─────────────────────────────────────────────────────────────────────

class AdvModal(discord.ui.Modal, title="📋 Registrar Advertência"):
    descricao = discord.ui.TextInput(
        label="Descrição da Advertência",
        placeholder="Descreva o motivo da advertência...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )
    dias = discord.ui.TextInput(
        label="Dias de Advertência",
        placeholder="Ex: 7",
        max_length=3,
        required=True,
    )

    def __init__(self, membro: discord.Member):
        super().__init__()
        self.membro = membro

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            dias_val = int(self.dias.value.strip())
            if dias_val <= 0:
                raise ValueError()
        except ValueError:
            await interaction.followup.send(
                "❌ O campo **Dias** deve ser um número inteiro positivo.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        canal = await _get_adv_channel(interaction.guild, guild_id)
        if not canal:
            await interaction.followup.send(
                "❌ Canal de advertências não configurado.\n"
                "Configure pelo **dashboard** ou use `/setup-adv`.",
                ephemeral=True,
            )
            return

        membro = self.membro
        embed = discord.Embed(
            title="⚠️ ADVERTÊNCIA",
            color=COR_ADV,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📋 Descrição", value=self.descricao.value, inline=False)
        embed.add_field(
            name="👤 Membro Advertido",
            value=f"{membro.mention}\n`{membro.display_name}`",
            inline=True,
        )
        embed.add_field(name="📅 Duração", value=f"**{dias_val}** dia(s)", inline=True)
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.set_footer(text=f"Advertido por {interaction.user.display_name}")

        await canal.send(embed=embed)
        await interaction.followup.send("✅ Advertência registrada com sucesso!", ephemeral=True)

        log_embed = discord.Embed(
            title="⚠️ Advertência Registrada",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(name="👤 Membro", value=f"{membro.mention}\n`{membro.id}`", inline=True)
        log_embed.add_field(name="⚖️ Aplicada por", value=f"{interaction.user.mention}", inline=True)
        log_embed.add_field(name="📅 Duração", value=f"{dias_val} dia(s)", inline=True)
        log_embed.add_field(name="📋 Descrição", value=self.descricao.value[:1000], inline=False)
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Advertência")
        await send_log(interaction.client, interaction.guild, "adv", log_embed)

        log.info(
            "Advertência aplicada a %s (%s) por %s em guild %s — %s dia(s)",
            membro, membro.id, interaction.user, interaction.guild_id, dias_val,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no AdvModal: %s", error, exc_info=True)
        msg = "❌ Ocorreu um erro ao registrar a advertência."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


# ── Views ─────────────────────────────────────────────────────────────────────

class AdvMemberSelectView(discord.ui.View):
    """View efêmera para selecionar o membro a ser advertido."""

    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Selecione o membro a advertir...",
        min_values=1,
        max_values=1,
    )
    async def selecionar_membro(
        self, interaction: discord.Interaction, select: discord.ui.UserSelect
    ):
        membro = select.values[0]
        if not isinstance(membro, discord.Member):
            await interaction.response.send_message(
                "❌ Membro não encontrado no servidor.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AdvModal(membro))


class AdvPainelView(discord.ui.View):
    """View persistente do painel de advertências."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="⚠️ Aplicar Advertência",
        style=discord.ButtonStyle.danger,
        custom_id="adv_painel:aplicar",
    )
    async def aplicar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor** para aplicar advertências.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "👤 Selecione o membro a ser advertido:",
            view=AdvMemberSelectView(),
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Adv(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AdvPainelView())

    @app_commands.command(
        name="setup_adv_painel",
        description="Posta o painel de advertências no canal configurado pelo dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_adv_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        row = db_get_system_config(guild_id, "adv")

        if not row or not row["canal_interacao_id"]:
            await interaction.response.send_message(
                "❌ Canal de advertências não configurado.\n"
                "Configure o sistema **adv** pelo **dashboard** ou use `/setup-adv` primeiro.",
                ephemeral=True,
            )
            return

        canal = interaction.guild.get_channel(int(row["canal_interacao_id"]))
        if canal is None:
            try:
                canal = await interaction.guild.fetch_channel(int(row["canal_interacao_id"]))
            except Exception:
                await interaction.response.send_message(
                    "❌ Canal configurado não encontrado. Reconfigure pelo dashboard.", ephemeral=True
                )
                return

        embed = discord.Embed(
            title="⚠️ Painel de Advertências",
            description=(
                "Clique no botão abaixo para aplicar uma advertência a um membro.\n\n"
                "Apenas membros com permissão **Gerenciar Servidor** podem aplicar advertências."
            ),
            color=COR_ADV,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Morro do Mineiro — Sistema de Advertências")
        await canal.send(embed=embed, view=AdvPainelView())
        await interaction.response.send_message(
            f"✅ Painel de advertências postado em {canal.mention}!", ephemeral=True
        )
        log.info("Painel de adv postado em #%s (guild %s) por %s", canal.name, guild_id, interaction.user)

    @setup_adv_painel.error
    async def setup_adv_painel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_adv_painel: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)

    @app_commands.command(
        name="setup-adv",
        description="Configura o canal onde as advertências serão postadas (legado — use o dashboard).",
    )
    @app_commands.describe(canal="Canal de texto para receber os embeds de advertência")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_adv(self, interaction: discord.Interaction, canal: discord.TextChannel):
        guild_id = str(interaction.guild_id)
        db_set_guild_config(guild_id, canal_adv_id=str(canal.id))

        embed = discord.Embed(
            title="✅ Advertências Configuradas",
            description=f"Canal de advertências definido para {canal.mention}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Configurado por {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Canal de adv definido para %s em guild %s por %s", canal.id, guild_id, interaction.user)

    @setup_adv.error
    async def setup_adv_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa ser **Administrador** para usar este comando.", ephemeral=True
            )
        else:
            log.error("Erro no /setup-adv: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)

    @app_commands.command(
        name="adv",
        description="Aplica uma advertência a um membro do servidor.",
    )
    @app_commands.describe(membro="Membro a ser advertido (@ para buscar o nickname)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def adv(self, interaction: discord.Interaction, membro: discord.Member):
        await interaction.response.send_modal(AdvModal(membro))

    @adv.error
    async def adv_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando.", ephemeral=True
            )
        else:
            log.error("Erro no /adv: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Adv(bot))
    log.info("AdvCog carregado.")
