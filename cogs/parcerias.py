"""Sistema de registro de parcerias do Morro do Mineiro."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import format_datetime_br
from core.permissions import has_approver_permission, is_lideranca
from services.db_service import (
    db_get_approver_role_ids,
    db_get_editores_farm_role_ids,
    db_get_lideranca_role_ids,
    db_get_parcerias_config,
    db_parceria_atualizar_imagem,
    db_parceria_atualizar_texto,
    db_parceria_criar,
    db_parceria_desativar,
    db_parceria_get,
    db_parceria_nome_existe,
    db_parcerias_ativas,
    db_set_parcerias_config,
)

log = logging.getLogger("parcerias")

COLOR_GOLD = 0xFFD700
COLOR_DARK = 0x111111
UPLOAD_TIMEOUT_SECONDS = 300.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _is_image(attachment: discord.Attachment) -> bool:
    return (attachment.content_type or "").startswith("image/") or attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized[:60] or "familia"


def _extension(filename: str) -> str:
    name = filename.lower()
    for ext in IMAGE_EXTENSIONS:
        if name.endswith(ext):
            return ext
    return ".png"


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _row_value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _has_staff_permission(member: discord.Member, guild_id: str) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    if has_approver_permission(member, db_get_approver_role_ids(guild_id)):
        return True
    if is_lideranca(member, db_get_lideranca_role_ids(guild_id)):
        return True
    return bool({role.id for role in member.roles} & set(db_get_editores_farm_role_ids(guild_id)))


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Painel de Parcerias - Morro do Mineiro",
        description=(
            "Use os botoes abaixo para registrar, editar ou remover parcerias ativas.\n"
            "As imagens dos uniformes ficam salvas diretamente na lista publica."
        ),
        color=COLOR_DARK,
    )
    embed.add_field(name="Registro", value="Crie uma nova parceria com produto, contatos e uniforme.", inline=False)
    embed.add_field(name="Lista ativa", value="Cada familia ativa aparece em uma unica mensagem atualizada.", inline=False)
    embed.set_footer(text="Morro do Mineiro - Sistema de Parcerias")
    return embed


def build_partner_embed(parceria) -> discord.Embed:
    criado = format_datetime_br(parceria["criado_em"], fallback="-")
    embed = discord.Embed(
        title=parceria["nome_familia"],
        color=COLOR_GOLD,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="\U0001f6d2 Produto", value=parceria["produto"], inline=False)
    cor_carro = _row_value(parceria, "cor_carro")
    if cor_carro:
        embed.add_field(name="\U0001f697 Cor do carro", value=cor_carro, inline=True)
    if parceria["contato_01"]:
        embed.add_field(name="\U0001f4de Contato Principal", value=parceria["contato_01"], inline=True)
    if parceria["contato_02"]:
        embed.add_field(name="\U0001f4de Contato Secundario", value=parceria["contato_02"], inline=True)
    embed.set_image(url=f"attachment://{parceria['nome_arquivo_imagem']}")
    embed.set_footer(text=f"Parceria registrada em {criado} - Morro do Mineiro")
    return embed


class ParceriasPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Registrar Parceria",
        emoji="\U0001f91d",
        style=discord.ButtonStyle.success,
        custom_id="parcerias:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("ParceriasCog")
        if not isinstance(cog, ParceriasCog):
            await interaction.response.send_message("Sistema de parcerias indisponivel.", ephemeral=True)
            return
        if not cog.check_staff(interaction):
            await interaction.response.send_message("Sem permissao para registrar parcerias.", ephemeral=True)
            return
        await interaction.response.send_modal(RegistroParceriaModal(cog))

    @discord.ui.button(
        label="Editar Parceria",
        emoji="\u270f\ufe0f",
        style=discord.ButtonStyle.primary,
        custom_id="parcerias:editar",
    )
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("ParceriasCog")
        if not isinstance(cog, ParceriasCog):
            await interaction.response.send_message("Sistema de parcerias indisponivel.", ephemeral=True)
            return
        await cog.open_select(interaction, mode="editar")

    @discord.ui.button(
        label="Remover Parceria",
        emoji="\U0001f5d1\ufe0f",
        style=discord.ButtonStyle.danger,
        custom_id="parcerias:remover",
    )
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("ParceriasCog")
        if not isinstance(cog, ParceriasCog):
            await interaction.response.send_message("Sistema de parcerias indisponivel.", ephemeral=True)
            return
        await cog.open_select(interaction, mode="remover")


class RegistroParceriaModal(discord.ui.Modal, title="Registro de Parceria - Morro do Mineiro"):
    nome_familia = discord.ui.TextInput(
        label="Nome da Familia",
        placeholder="Ex: Morro do Mineiro",
        max_length=100,
    )
    produto = discord.ui.TextInput(
        label="Produto da Parceria",
        placeholder="Ex: Armamento, Municao, Veiculos",
        max_length=100,
    )
    cor_carro = discord.ui.TextInput(
        label="Cor do carro",
        placeholder="Ex: Preto com dourado",
        max_length=80,
    )
    contato_01 = discord.ui.TextInput(
        label="Contato Principal",
        placeholder="Ex: Joao: (31) 99999-9999",
        required=False,
        max_length=150,
    )
    contato_02 = discord.ui.TextInput(
        label="Contato Secundario",
        placeholder="Ex: Pedro: (31) 98888-8888",
        required=False,
        max_length=150,
    )

    def __init__(self, cog: "ParceriasCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        nome = self.nome_familia.value.strip()
        if db_parceria_nome_existe(guild_id, nome):
            await interaction.response.send_message(
                "Essa familia ja possui parceria registrada. Use o botao Editar Parceria.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Dados recebidos! Envie agora a imagem do uniforme da familia. Voce tem **5 minutos**.",
            ephemeral=True,
        )
        upload = await self.cog.collect_image(interaction, nome)
        if upload is None:
            return

        channel = await self.cog.get_ativas_channel(interaction.guild, guild_id)
        if channel is None:
            await interaction.followup.send("Canal de parcerias ativas nao configurado.", ephemeral=True)
            return

        image_bytes, filename = upload
        file = discord.File(io.BytesIO(image_bytes), filename=filename)
        provisional = {
            "nome_familia": nome,
            "produto": self.produto.value.strip(),
            "cor_carro": self.cor_carro.value.strip(),
            "contato_01": _clean(self.contato_01.value),
            "contato_02": _clean(self.contato_02.value),
            "nome_arquivo_imagem": filename,
            "criado_em": discord.utils.utcnow().isoformat(),
        }
        embed = build_partner_embed(provisional)
        try:
            message = await channel.send(embed=embed, file=file)
            try:
                db_parceria_criar(
                    guild_id=guild_id,
                    nome_familia=nome,
                    produto=self.produto.value,
                    cor_carro=self.cor_carro.value,
                    contato_01=_clean(self.contato_01.value),
                    contato_02=_clean(self.contato_02.value),
                    mensagem_lista_id=message.id,
                    nome_arquivo_imagem=filename,
                    registrado_por=interaction.user.id,
                )
            except Exception:
                try:
                    await message.delete()
                except Exception:
                    pass
                raise
        except Exception:
            log.exception("Falha ao registrar parceria")
            await interaction.followup.send("Nao foi possivel registrar a parceria.", ephemeral=True)
            return

        await interaction.followup.send("Parceria registrada com sucesso.", ephemeral=True)


class EdicaoParceriaModal(discord.ui.Modal):
    def __init__(self, cog: "ParceriasCog", parceria):
        super().__init__(title="Editar Parceria - Morro do Mineiro")
        self.cog = cog
        self.parceria_id = int(parceria["id"])
        self.nome_familia = discord.ui.TextInput(label="Nome da Familia", default=parceria["nome_familia"], max_length=100)
        self.produto = discord.ui.TextInput(label="Produto da Parceria", default=parceria["produto"], max_length=100)
        self.cor_carro = discord.ui.TextInput(
            label="Cor do carro",
            default=_row_value(parceria, "cor_carro") or "",
            max_length=80,
        )
        self.contato_01 = discord.ui.TextInput(
            label="Contato Principal",
            default=parceria["contato_01"] or "",
            required=False,
            max_length=150,
        )
        self.contato_02 = discord.ui.TextInput(
            label="Contato Secundario",
            default=parceria["contato_02"] or "",
            required=False,
            max_length=150,
        )
        for item in (self.nome_familia, self.produto, self.cor_carro, self.contato_01, self.contato_02):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        parceria = db_parceria_get(guild_id, self.parceria_id)
        if not parceria or not parceria["ativo"]:
            await interaction.response.send_message("Essa parceria nao esta mais ativa.", ephemeral=True)
            return

        nome = self.nome_familia.value.strip()
        if db_parceria_nome_existe(guild_id, nome, exclude_id=self.parceria_id):
            await interaction.response.send_message(
                "Ja existe outra parceria com esse nome. Use um nome diferente.",
                ephemeral=True,
            )
            return

        db_parceria_atualizar_texto(
            self.parceria_id,
            nome,
            self.produto.value,
            self.cor_carro.value,
            _clean(self.contato_01.value),
            _clean(self.contato_02.value),
        )
        parceria = db_parceria_get(guild_id, self.parceria_id)
        await self.cog.refresh_partner_message(interaction.guild, parceria)
        await interaction.response.send_message(
            "Deseja enviar uma nova imagem de uniforme?",
            view=TrocarImagemView(self.cog, self.parceria_id, interaction.user.id),
            ephemeral=True,
        )


class FamiliasSelect(discord.ui.Select):
    def __init__(self, cog: "ParceriasCog", rows, mode: str):
        self.cog = cog
        self.mode = mode
        options = [
            discord.SelectOption(
                label=row["nome_familia"][:100],
                description=(row["produto"] or "")[:100],
                value=str(row["id"]),
            )
            for row in rows
        ]
        super().__init__(
            placeholder="Selecione a familia...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        parceria_id = int(self.values[0])
        if self.mode == "editar":
            parceria = db_parceria_get(str(interaction.guild_id), parceria_id)
            if not parceria or not parceria["ativo"]:
                await interaction.response.send_message("Essa parceria nao esta mais ativa.", ephemeral=True)
                return
            await interaction.response.send_modal(EdicaoParceriaModal(self.cog, parceria))
            return
        await interaction.response.edit_message(
            content="Confirma a remocao dessa parceria?",
            view=ConfirmarRemocaoView(self.cog, parceria_id, interaction.user.id),
        )


class FamiliasSelectView(discord.ui.View):
    def __init__(self, cog: "ParceriasCog", rows, mode: str):
        super().__init__(timeout=120)
        self.add_item(FamiliasSelect(cog, rows, mode))


class TrocarImagemView(discord.ui.View):
    def __init__(self, cog: "ParceriasCog", parceria_id: int, user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.parceria_id = parceria_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Essa confirmacao pertence a outro usuario.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sim", style=discord.ButtonStyle.success)
    async def sim(self, interaction: discord.Interaction, button: discord.ui.Button):
        parceria = db_parceria_get(str(interaction.guild_id), self.parceria_id)
        if not parceria or not parceria["ativo"]:
            await interaction.response.edit_message(content="Essa parceria nao esta mais ativa.", view=None)
            return
        await interaction.response.edit_message(
            content="Envie a nova imagem do uniforme neste canal. Voce tem **5 minutos**.",
            view=None,
        )
        upload = await self.cog.collect_image(interaction, parceria["nome_familia"])
        if upload is None:
            return
        image_bytes, filename = upload
        db_parceria_atualizar_imagem(self.parceria_id, filename)
        parceria = db_parceria_get(str(interaction.guild_id), self.parceria_id)
        await self.cog.refresh_partner_message(
            interaction.guild,
            parceria,
            image_bytes=image_bytes,
            filename=filename,
        )
        await interaction.followup.send("Imagem da parceria atualizada.", ephemeral=True)

    @discord.ui.button(label="Nao", style=discord.ButtonStyle.secondary)
    async def nao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Parceria atualizada mantendo a imagem atual.", view=None)


class ConfirmarRemocaoView(discord.ui.View):
    def __init__(self, cog: "ParceriasCog", parceria_id: int, user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.parceria_id = parceria_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Essa confirmacao pertence a outro usuario.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        parceria = db_parceria_get(str(interaction.guild_id), self.parceria_id)
        if not parceria or not parceria["ativo"]:
            await interaction.response.edit_message(content="Essa parceria ja foi removida.", view=None)
            return
        channel = await self.cog.get_ativas_channel(interaction.guild, str(interaction.guild_id))
        if channel is not None:
            try:
                message = await channel.fetch_message(int(parceria["mensagem_lista_id"]))
                await message.delete()
            except discord.NotFound:
                pass
            except Exception:
                log.exception("Falha ao apagar mensagem da parceria %s", self.parceria_id)
        db_parceria_desativar(self.parceria_id)
        await interaction.response.edit_message(content="Parceria removida da lista ativa.", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Remocao cancelada.", view=None)


class ParceriasCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ParceriasPanelView())

    def check_staff(self, interaction: discord.Interaction) -> bool:
        return bool(
            interaction.guild_id
            and isinstance(interaction.user, discord.Member)
            and _has_staff_permission(interaction.user, str(interaction.guild_id))
        )

    async def get_registrar_channel(self, guild: discord.Guild, guild_id: str) -> discord.TextChannel | None:
        _, channel_id, _, _ = db_get_parcerias_config(guild_id)
        return await self._get_text_channel(guild, channel_id)

    async def get_ativas_channel(self, guild: discord.Guild, guild_id: str) -> discord.TextChannel | None:
        _, _, channel_id, _ = db_get_parcerias_config(guild_id)
        return await self._get_text_channel(guild, channel_id)

    async def get_category(self, guild: discord.Guild, guild_id: str) -> discord.CategoryChannel | None:
        category_id, _, _, _ = db_get_parcerias_config(guild_id)
        if not category_id:
            return None
        category = guild.get_channel(int(category_id))
        if category is None:
            try:
                category = await guild.fetch_channel(int(category_id))
            except Exception:
                return None
        return category if isinstance(category, discord.CategoryChannel) else None

    async def _get_text_channel(self, guild: discord.Guild, channel_id: str | None) -> discord.TextChannel | None:
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except Exception:
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def open_select(self, interaction: discord.Interaction, mode: str) -> None:
        if not self.check_staff(interaction):
            await interaction.response.send_message("Sem permissao para gerenciar parcerias.", ephemeral=True)
            return
        rows = db_parcerias_ativas(str(interaction.guild_id))
        if not rows:
            await interaction.response.send_message("Nao ha parcerias ativas cadastradas.", ephemeral=True)
            return
        action = "editar" if mode == "editar" else "remover"
        await interaction.response.send_message(
            f"Selecione a parceria que deseja {action}.",
            view=FamiliasSelectView(self, rows, mode),
            ephemeral=True,
        )

    async def apply_manager_permissions(self, guild: discord.Guild) -> None:
        guild_id = str(guild.id)
        targets = [
            await self.get_category(guild, guild_id),
            await self.get_registrar_channel(guild, guild_id),
            await self.get_ativas_channel(guild, guild_id),
        ]
        roles = [role for role in guild.roles if "gerente" in role.name.casefold()]
        overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        )
        for channel in targets:
            if channel is None:
                continue
            for role in roles:
                try:
                    await channel.set_permissions(
                        role,
                        overwrite=overwrite,
                        reason="Permissoes dos gerentes para sistema de parcerias",
                    )
                except Exception:
                    log.warning(
                        "Falha ao aplicar permissao de gerente em %s para %s",
                        channel.id,
                        role.id,
                        exc_info=True,
                    )

    async def collect_image(
        self,
        interaction: discord.Interaction,
        nome_familia: str,
    ) -> tuple[bytes, str] | None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Canal invalido para upload de imagem.", ephemeral=True)
            return None

        overwrite = channel.overwrites_for(interaction.user)
        overwrite.send_messages = True
        overwrite.attach_files = True
        overwrite.read_message_history = True
        end_at = time.monotonic() + UPLOAD_TIMEOUT_SECONDS
        invalid_attempts = 0

        try:
            await channel.set_permissions(
                interaction.user,
                overwrite=overwrite,
                reason="Upload temporario de uniforme de parceria",
            )

            while True:
                remaining = max(0.0, end_at - time.monotonic())
                if remaining <= 0:
                    await interaction.followup.send("Tempo esgotado, registro cancelado. Tente novamente.", ephemeral=True)
                    return None

                def check(message: discord.Message) -> bool:
                    return message.author.id == interaction.user.id and message.channel.id == channel.id

                try:
                    message = await self.bot.wait_for("message", check=check, timeout=remaining)
                except asyncio.TimeoutError:
                    await interaction.followup.send("Tempo esgotado, registro cancelado. Tente novamente.", ephemeral=True)
                    return None

                attachment = next((item for item in message.attachments if _is_image(item)), None)
                if attachment is None:
                    invalid_attempts += 1
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if invalid_attempts <= 1:
                        await interaction.followup.send("Nao encontrei uma imagem valida, envie novamente.", ephemeral=True)
                        continue
                    await interaction.followup.send("Registro cancelado: nenhuma imagem valida foi enviada.", ephemeral=True)
                    return None

                try:
                    image_bytes = await attachment.read()
                except Exception:
                    log.exception("Falha ao baixar anexo de parceria")
                    await interaction.followup.send("Nao consegui baixar a imagem enviada. Tente novamente.", ephemeral=True)
                    return None

                try:
                    await message.delete()
                except Exception:
                    pass
                filename = f"uniforme_{_slug(nome_familia)}{_extension(attachment.filename)}"
                return image_bytes, filename
        finally:
            try:
                await channel.set_permissions(
                    interaction.user,
                    overwrite=None,
                    reason="Encerramento do upload temporario de parceria",
                )
            except Exception:
                log.warning("Nao foi possivel revogar permissao temporaria de %s", interaction.user.id, exc_info=True)

    async def refresh_partner_message(
        self,
        guild: discord.Guild,
        parceria,
        *,
        image_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> None:
        if parceria is None:
            return
        channel = await self.get_ativas_channel(guild, str(guild.id))
        if channel is None:
            return
        try:
            message = await channel.fetch_message(int(parceria["mensagem_lista_id"]))
        except discord.NotFound:
            return
        embed = build_partner_embed(parceria)
        if image_bytes is not None and filename is not None:
            file = discord.File(io.BytesIO(image_bytes), filename=filename)
            await message.edit(embed=embed, attachments=[file])
        else:
            await message.edit(embed=embed)

    async def cleanup_orphan_permissions(self, guild: discord.Guild) -> None:
        guild_id = str(guild.id)
        channels = [
            await self.get_registrar_channel(guild, guild_id),
            await self.get_ativas_channel(guild, guild_id),
        ]
        bot_id = self.bot.user.id if self.bot.user else None
        for channel in channels:
            if channel is None:
                continue
            for target, overwrite in list(channel.overwrites.items()):
                if isinstance(target, discord.Role):
                    continue
                if getattr(target, "id", None) == bot_id:
                    continue
                if overwrite.send_messages is True:
                    try:
                        await channel.set_permissions(
                            target,
                            overwrite=None,
                            reason="Limpeza de permissao temporaria orfa de parceria",
                        )
                    except Exception:
                        log.warning("Falha ao limpar overwrite temporario em %s", channel.id, exc_info=True)

    @commands.Cog.listener()
    async def on_ready(self):
        if getattr(self.bot, "_parcerias_cleanup_done", False):
            return
        self.bot._parcerias_cleanup_done = True
        for guild in self.bot.guilds:
            await self.cleanup_orphan_permissions(guild)
            await self.apply_manager_permissions(guild)

    @app_commands.command(
        name="setup_parcerias",
        description="Posta ou atualiza o painel fixo de parcerias.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_parcerias(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        _, registrar_id, _, panel_message_id = db_get_parcerias_config(guild_id)
        channel = await self._get_text_channel(interaction.guild, registrar_id) if registrar_id else interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Canal de registro de parcerias nao encontrado.", ephemeral=True)
            return

        old_message = None
        if panel_message_id:
            try:
                old_message = await channel.fetch_message(int(panel_message_id))
            except Exception:
                old_message = None

        if old_message is not None:
            await old_message.edit(embed=build_panel_embed(), view=ParceriasPanelView())
            message = old_message
        else:
            message = await channel.send(embed=build_panel_embed(), view=ParceriasPanelView())
        db_set_parcerias_config(guild_id, registrar_channel_id=str(channel.id), panel_message_id=str(message.id))
        await self.apply_manager_permissions(interaction.guild)
        await interaction.followup.send(f"Painel de parcerias configurado em {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ParceriasCog(bot))
    log.info("ParceriasCog carregado.")
