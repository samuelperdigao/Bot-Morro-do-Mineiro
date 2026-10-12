"""
cogs/acao_painel.py - Painel fixo de ação (embed estático com botão de início).

Embed fixo no canal configurado (sistema "acao" via dashboard).
Ao clicar, abre modal para horário e tipo (fuga/tiro), depois posta
o seletor de ação no canal configurado com essas informações.
Mantém cogs/acao.py intacto.
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from core.permissions import is_lideranca
from services.db_service import db_get_lideranca_role_ids, db_get_system_config

log = get_logger("acao_painel", "acao.log")

COR_ACAO = 0xFFD700
FOOTER_ACAO = "Morro do Mineiro — Sistema de Ação"


# ── Modal de configuração da ação (horário + tipo) ────────────────────────────

class PreAcaoModal(discord.ui.Modal, title="⚡ Configurar Ação"):
    data = discord.ui.TextInput(
        label="Data da ação",
        placeholder=f"Ex: {DATE_BR_EXAMPLE}",
        max_length=10,
        required=True,
    )
    horario = discord.ui.TextInput(
        label="Horário da ação",
        placeholder="Ex: 21:00",
        max_length=10,
        required=True,
    )
    tipo_acao = discord.ui.TextInput(
        label="Tipo da ação",
        placeholder="Digite: fuga  ou  tiro",
        max_length=10,
        required=True,
    )

    def __init__(self, canal_id: str | None):
        super().__init__()
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data_val = normalize_date_br(self.data.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        horario_val = self.horario.value.strip()
        tipo_val    = self.tipo_acao.value.strip().lower()

        if tipo_val not in ("fuga", "tiro"):
            await interaction.response.send_message(
                "❌ Tipo inválido. Digite **fuga** ou **tiro**.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        from cogs.acao import AcaoSelectView

        tipo_display = "🏃 Fuga" if tipo_val == "fuga" else "🔫 No Tiro"
        acao_embed = discord.Embed(
            title="⚡ Selecione a Ação",
            description="Escolha a ação que deseja realizar no menu abaixo.",
            color=COR_ACAO,
        )
        acao_embed.add_field(name="📅 Data",    value=data_val,    inline=True)
        acao_embed.add_field(name="🕐 Horário", value=horario_val, inline=True)
        acao_embed.add_field(name="⚔️ Tipo",    value=tipo_display, inline=True)
        acao_embed.set_footer(text=FOOTER_ACAO)

        canal = None
        if self.canal_id:
            canal = interaction.guild.get_channel(int(self.canal_id))
            if canal is None:
                try:
                    canal = await interaction.guild.fetch_channel(int(self.canal_id))
                except Exception:
                    canal = None

        if canal:
            await canal.send(
                embed=acao_embed,
                view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val, criador_id=str(interaction.user.id)),
            )
            await interaction.followup.send(
                f"✅ Seletor de ação aberto em {canal.mention}!",
                ephemeral=True,
            )
        else:
            # Fallback: posta no canal atual se o canal não estiver configurado
            await interaction.followup.send(
                embed=acao_embed,
                view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val, criador_id=str(interaction.user.id)),
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em PreAcaoModal.on_submit: %s", error, exc_info=True)
        try:
            await interaction.followup.send("❌ Erro ao iniciar ação. Tente novamente.", ephemeral=True)
        except Exception:
            pass


# ── View do painel (persistente) ──────────────────────────────────────────────

class AcaoPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="⚡ Iniciar Ação",
        style=discord.ButtonStyle.primary,
        custom_id="acao_painel:iniciar",
    )
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message(
                "❌ Apenas liderança pode iniciar ação.",
                ephemeral=True,
            )
            return
        row      = db_get_system_config(guild_id, "acao")
        canal_id = row["canal_interacao_id"] if row else None
        from cogs.acao import AcaoTipoView

        await interaction.response.send_message(
            "Escolha o tipo da ação:",
            view=AcaoTipoView(canal_id=canal_id),
            ephemeral=True,
        )


# ── Embed fixo do painel ──────────────────────────────────────────────────────

def _build_painel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Painel de Ação — Morro do Mineiro",
        description=(
            "Inicie uma ação clicando no botão abaixo.\n\n"
            "Você irá definir o **horário** e o **tipo** (fuga ou tiro) "
            "antes de escolher a missão."
        ),
        color=COR_ACAO,
    )
    embed.set_footer(text=FOOTER_ACAO)
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class AcaoPainelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AcaoPainelView())

    @app_commands.command(
        name="setup_acao_painel",
        description="Posta o painel fixo de ação no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_acao_painel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        row = db_get_system_config(guild_id, "acao")
        if not row or not row["canal_interacao_id"]:
            await interaction.followup.send(
                "❌ Configure o canal do sistema de Ação no dashboard primeiro.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(row["canal_interacao_id"]))
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(int(row["canal_interacao_id"]))
            except Exception:
                await interaction.followup.send(
                    "❌ Canal configurado não encontrado.", ephemeral=True
                )
                return

        await channel.send(embed=_build_painel_embed(), view=AcaoPainelView())
        await interaction.followup.send(
            f"✅ Painel de ação postado em {channel.mention}!", ephemeral=True
        )
        log.info("Painel acao postado (guild %s, canal %s)", guild_id, channel.id)

    @setup_acao_painel.error
    async def _setup_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
        else:
            log.error("Erro em /setup_acao_painel: %s", error, exc_info=True)
            try:
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AcaoPainelCog(bot))
    log.info("AcaoPainelCog carregado com sucesso.")
