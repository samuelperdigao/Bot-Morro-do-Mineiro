"""
cogs/radio.py - Sistema de Rádio.

RadioContainerPanelView → painel fixo em Components V2 com botão
RadioPainelView         → view legada, mantida para painéis já publicados
RadioModal              → modal para definir o número da rádio
/setup_radio_painel     → publica o painel Container no canal fixo de rádio

Ao confirmar:
  1. Renomeia o canal para "radio-{numero}"
  2. Remove o aviso anterior da rádio
  3. Envia @everyone no canal com o novo número
"""

from collections.abc import AsyncIterator, Iterable
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("radio", "bot.log")

CANAL_RADIO_ID = 1474869321863008296
RADIO_CONTAINER_CUSTOM_ID = "radio_container:definir"
RADIO_CONTAINER_TEST_CUSTOM_ID = "radio_container_test:definir"
RADIO_PANEL_TITLE = "📻 Central de Rádio"
RADIO_NOTICE_TITLE = "📻 Nova Rádio Definida"
RADIO_COLOR = 0xFFD700


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


def criar_embed_painel_radio() -> discord.Embed:
    """Monta o painel fixo da radio com instrucoes curtas e bem separadas."""
    embed = discord.Embed(
        title=RADIO_PANEL_TITLE,
        description=(
            "Atualize a frequência oficial da organização usando o botão abaixo."
        ),
        color=RADIO_COLOR,
    )
    embed.add_field(
        name="📡 Como alterar",
        value=(
            "`1.` Clique em **Alterar rádio**\n"
            "`2.` Informe o número da nova frequência\n"
            "`3.` Confirme para avisar todos os membros"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 Acesso restrito",
        value="Somente **gerentes** e **administradores** podem fazer alterações.",
        inline=False,
    )
    embed.set_footer(text="Morro do Mineiro • Sistema de Rádio")
    return embed


def _component_custom_ids(components: Iterable[object]) -> Iterable[str]:
    """Percorre IDs de componentes comuns e componentes V2 aninhados."""
    for component in components or ():
        custom_id = getattr(component, "custom_id", "") or ""
        if custom_id:
            yield custom_id
        yield from _component_custom_ids(getattr(component, "children", ()) or ())


def _component_texts(components: Iterable[object]) -> Iterable[str]:
    """Percorre o texto de TextDisplays, inclusive dentro de Containers."""
    for component in components or ():
        content = getattr(component, "content", None)
        if content:
            yield content
        yield from _component_texts(getattr(component, "children", ()) or ())


def _is_radio_panel_message(message: discord.Message, bot_user_id: int | None = None) -> bool:
    """Reconhece painéis antigos (embed) e novos (Container)."""
    if bot_user_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_user_id:
        return False

    if any(
        (embed.title or "").strip() == RADIO_PANEL_TITLE
        for embed in getattr(message, "embeds", ())
    ):
        return True

    return any(
        custom_id.startswith(("radio_painel:", "radio_container:", "radio_container_test:"))
        for custom_id in _component_custom_ids(getattr(message, "components", ()))
    )


def _is_radio_notice_message(message: discord.Message, bot_user_id: int | None = None) -> bool:
    """Reconhece avisos de frequência antigos e avisos publicados em Container."""
    if bot_user_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_user_id:
        return False

    if any(
        (embed.title or "").strip() == RADIO_NOTICE_TITLE
        for embed in getattr(message, "embeds", ())
    ):
        return True

    texts = "\n".join(_component_texts(getattr(message, "components", ())))
    return RADIO_NOTICE_TITLE in texts and "Sintonize:" in texts


async def _remover_mensagens_radio(
    canal: discord.TextChannel,
    predicate,
    *,
    bot_user_id: int | None = None,
) -> int:
    """Remove mensagens do bot que correspondem ao predicado informado."""
    removidas = 0
    try:
        history: AsyncIterator[discord.Message] = canal.history(limit=None)
        async for message in history:
            if not predicate(message, bot_user_id):
                continue
            try:
                await message.delete()
                removidas += 1
            except discord.NotFound:
                # A mensagem pode ter sido removida entre o history e o delete.
                continue
            except discord.Forbidden:
                log.warning("Sem permissão para apagar mensagem antiga da rádio (%s).", message.id)
            except discord.HTTPException as error:
                log.warning("Erro ao apagar mensagem antiga da rádio (%s): %s", message.id, error)
    except discord.Forbidden:
        log.warning("Sem permissão para ler o histórico do canal de rádio.")
    except discord.HTTPException as error:
        log.warning("Erro ao ler o histórico do canal de rádio: %s", error)
    return removidas


async def remover_avisos_radio_antigos(
    canal: discord.TextChannel,
    *,
    bot_user_id: int | None = None,
) -> int:
    """Mantém apenas o próximo aviso de rádio no canal."""
    return await _remover_mensagens_radio(
        canal,
        _is_radio_notice_message,
        bot_user_id=bot_user_id,
    )


async def remover_paineis_radio_antigos(
    canal: discord.TextChannel,
    *,
    bot_user_id: int | None = None,
) -> int:
    """Remove painéis duplicados quando o setup migra embed para Container."""
    return await _remover_mensagens_radio(
        canal,
        _is_radio_panel_message,
        bot_user_id=bot_user_id,
    )


class RadioContainerPanelView(discord.ui.LayoutView):
    """Painel fixo da rádio usando Components V2, com o mesmo fluxo legado."""

    def __init__(self, *, custom_id: str = RADIO_CONTAINER_CUSTOM_ID):
        super().__init__(timeout=None)

        embed = criar_embed_painel_radio()
        button = discord.ui.Button(
            label="Alterar rádio",
            emoji="📻",
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        )
        button.callback = self._definir

        content = [
            discord.ui.TextDisplay(f"# {embed.title}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(embed.description or ""),
        ]
        for field in embed.fields:
            content.extend(
                (
                    discord.ui.Separator(),
                    discord.ui.TextDisplay(f"**{field.name}**\n{field.value}"),
                )
            )
        content.extend(
            (
                discord.ui.Separator(),
                discord.ui.ActionRow(button),
                discord.ui.TextDisplay(embed.footer.text if embed.footer else ""),
            )
        )

        self.add_item(
            discord.ui.Container(
                *content,
                accent_color=embed.color,
            )
        )

    async def _definir(self, interaction: discord.Interaction):
        await _abrir_modal_radio(interaction)


class RadioAvisoContainerView(discord.ui.LayoutView):
    """Aviso da nova frequência em Container, incluindo data e horário."""

    def __init__(
        self,
        *,
        numero: str,
        responsavel: str,
        momento: datetime,
    ):
        super().__init__(timeout=None)
        timestamp = int(momento.timestamp())

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("@everyone"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(f"# {RADIO_NOTICE_TITLE}"),
                discord.ui.TextDisplay("A rádio do servidor foi alterada!"),
                discord.ui.TextDisplay(f"**Sintonize:** `{numero}`"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    f"**Definido por:** {responsavel}\n"
                    f"**Data e horário:** <t:{timestamp}:F>\n\n"
                    "Morro do Mineiro • Sistema de Rádio"
                ),
                accent_color=RADIO_COLOR,
            )
        )


# ── Modal ─────────────────────────────────────────────────────────────────────

async def _abrir_modal_radio(interaction: discord.Interaction):
    """Valida a permissão e abre o modal para views legadas e Container."""
    if not pode_alterar_radio(interaction.user):
        await interaction.response.send_message(
            "❌ Apenas gerentes e administradores podem alterar a rádio.",
            ephemeral=True,
        )
        return
    await interaction.response.send_modal(RadioModal())

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

        # Remove o aviso anterior antes de publicar o novo, mantendo o canal limpo.
        bot_user_id = getattr(getattr(guild, "me", None), "id", None)
        if bot_user_id is None:
            bot_user_id = getattr(getattr(interaction.client, "user", None), "id", None)
        await remover_avisos_radio_antigos(canal, bot_user_id=bot_user_id)

        momento = discord.utils.utcnow()

        try:
            await canal.send(
                view=RadioAvisoContainerView(
                    numero=numero,
                    responsavel=interaction.user.display_name,
                    momento=momento,
                ),
                allowed_mentions=discord.AllowedMentions(
                    everyone=True,
                    users=False,
                    roles=False,
                    replied_user=False,
                ),
            )
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
        label="Alterar rádio",
        emoji="📻",
        style=discord.ButtonStyle.primary,
        custom_id="radio_painel:definir",
    )
    async def definir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _abrir_modal_radio(interaction)


# ── Cog ───────────────────────────────────────────────────────────────────────

class RadioCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._permissoes_configuradas = False
        bot.add_view(RadioPainelView())
        bot.add_view(RadioContainerPanelView())
        bot.add_view(RadioContainerPanelView(custom_id=RADIO_CONTAINER_TEST_CUSTOM_ID))

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

        bot_user_id = getattr(getattr(canal.guild, "me", None), "id", None)
        await remover_paineis_radio_antigos(canal, bot_user_id=bot_user_id)

        await canal.send(view=RadioContainerPanelView())
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
