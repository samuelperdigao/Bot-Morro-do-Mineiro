"""
cogs/radio.py - Sistema de Rádio.

RadioPainelView     → painel fixo com botão "📻 Definir Nova Rádio"
RadioModal          → modal para definir o número da rádio
/setup_radio_painel → posta o painel no canal fixo de rádio

Ao confirmar:
  1. Renomeia o canal para "radio-{numero}"
  2. Envia @everyone no canal com o novo número
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("radio", "bot.log")

CANAL_RADIO_ID = 1474869321863008296


def pode_alterar_radio(member: discord.Member) -> bool:
    """Permite a alteracao apenas para administradores e cargos de gerente."""
    if member.guild_permissions.administrator:
        return True
    return any("gerente" in role.name.casefold() for role in member.roles)


async def configurar_permissoes_radio(canal: discord.TextChannel) -> None:
    """Impede mensagens de membros sem bloquear o uso dos componentes do painel."""
    everyone = canal.guild.default_role
    bot_member = canal.guild.me
    overwrites = canal.overwrites
    overwrites.setdefault(everyone, canal.overwrites_for(everyone))

    for target, overwrite in overwrites.items():
        if bot_member is not None and target.id == bot_member.id:
            continue
        overwrite.send_messages = False
        overwrite.send_messages_in_threads = False
        overwrite.create_public_threads = False
        overwrite.create_private_threads = False

    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, canal.overwrites_for(bot_member))
        bot_overwrite.view_channel = True
        bot_overwrite.send_messages = True
        bot_overwrite.embed_links = True
        bot_overwrite.mention_everyone = True
        overwrites[bot_member] = bot_overwrite

    await canal.edit(
        overwrites=overwrites,
        reason="Canal da radio reservado ao painel interativo",
    )


# ── Modal ─────────────────────────────────────────────────────────────────────

class RadioModal(discord.ui.Modal, title="📻 Definir Nova Rádio"):
    numero = discord.ui.TextInput(
        label="Número da Rádio",
        placeholder="Ex: 1221",
        max_length=20,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not pode_alterar_radio(interaction.user):
            await interaction.response.send_message(
                "❌ Apenas gerentes e administradores podem alterar a rádio.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        numero = self.numero.value.strip()
        guild  = interaction.guild

        # Busca o canal de rádio
        canal = guild.get_channel(CANAL_RADIO_ID)
        if canal is None:
            try:
                canal = await guild.fetch_channel(CANAL_RADIO_ID)
            except Exception:
                await interaction.followup.send(
                    "❌ Canal de rádio não encontrado.", ephemeral=True
                )
                return

        # Renomeia o canal para "radio-{numero}"
        novo_nome = f"┃📻-radio-{numero}!"
        try:
            await canal.edit(name=novo_nome, reason=f"Rádio alterada por {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Sem permissão para renomear o canal.", ephemeral=True
            )
            return
        except Exception as e:
            log.error("Erro ao renomear canal de rádio: %s", e, exc_info=True)
            await interaction.followup.send(
                f"❌ Erro ao renomear o canal: {e}", ephemeral=True
            )
            return

        # Envia anúncio @everyone no canal
        embed = discord.Embed(
            title="📻 Nova Rádio Definida",
            description=(
                f"A rádio do servidor foi alterada!\n\n"
                f"**Sintonize:** `{numero}`"
            ),
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Definido por {interaction.user.display_name} • Morro do Mineiro")

        try:
            await canal.send(content="@everyone", embed=embed)
        except discord.Forbidden:
            log.warning("Sem permissão para enviar @everyone no canal de rádio.")

        await interaction.followup.send(
            f"✅ Rádio alterada para **{numero}**!\n"
            f"Canal renomeado para `┃📻-radio-{numero}!` e membros notificados.",
            ephemeral=True,
        )
        log.info("Rádio alterada para '%s' por %s (guild %s)", numero, interaction.user, guild.id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no RadioModal: %s", error, exc_info=True)
        msg = "❌ Ocorreu um erro ao alterar a rádio."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


# ── View (painel fixo) ────────────────────────────────────────────────────────

class RadioPainelView(discord.ui.View):
    """View persistente do painel de rádio."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📻 Definir Nova Rádio",
        style=discord.ButtonStyle.primary,
        custom_id="radio_painel:definir",
    )
    async def definir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not pode_alterar_radio(interaction.user):
            await interaction.response.send_message(
                "❌ Apenas gerentes e administradores podem alterar a rádio.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RadioModal())


# ── Cog ───────────────────────────────────────────────────────────────────────

class RadioCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._permissoes_configuradas = False
        bot.add_view(RadioPainelView())

    @commands.Cog.listener()
    async def on_ready(self):
        if self._permissoes_configuradas:
            return
        canal = self.bot.get_channel(CANAL_RADIO_ID)
        if not isinstance(canal, discord.TextChannel):
            log.warning("Canal de radio nao encontrado ao configurar permissoes.")
            return
        try:
            await configurar_permissoes_radio(canal)
        except discord.HTTPException as error:
            log.error("Erro ao configurar permissoes do canal de radio: %s", error)
            return
        self._permissoes_configuradas = True

    @app_commands.command(
        name="setup_radio_painel",
        description="Posta o painel de definição de rádio no canal de rádio.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_radio_painel(self, interaction: discord.Interaction):
        canal = self.bot.get_channel(CANAL_RADIO_ID)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(CANAL_RADIO_ID)
            except Exception:
                await interaction.response.send_message(
                    f"❌ Canal de rádio (`{CANAL_RADIO_ID}`) não encontrado.", ephemeral=True
                )
                return

        try:
            await configurar_permissoes_radio(canal)
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Não consegui bloquear o envio de mensagens no canal. "
                "Verifique a permissão **Gerenciar Canais** do bot.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📻 Rádio do Servidor",
            description=(
                "Clique no botão abaixo para definir o número da rádio.\n\n"
                "Ao confirmar, o canal será renomeado e todos os membros serão notificados."
            ),
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Morro do Mineiro — Sistema de Rádio")

        await canal.send(embed=embed, view=RadioPainelView())
        await interaction.response.send_message(
            f"✅ Painel de rádio postado em {canal.mention}!", ephemeral=True
        )
        log.info("Painel de rádio postado por %s (guild %s)", interaction.user, interaction.guild_id)

    @setup_radio_painel.error
    async def setup_radio_painel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_radio_painel: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RadioCog(bot))
    log.info("RadioCog carregado.")
