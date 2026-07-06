"""Tickets privados de acompanhamento do farm semanal."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from datetime import date, timedelta

import discord
from discord.ext import commands, tasks

from core.date_utils import format_date_br, format_datetime_br
from core.role_sync import find_role_by_names
from services.db_service import (
    DINHEIRO_ITEMS,
    current_week_id,
    db_aprovar,
    db_editar_evento,
    db_evento_itens,
    db_get_guild_config,
    db_get_system_config,
    db_get_meta,
    db_get_progresso,
    db_meta_alvos_ativos,
    db_meta_tipo_efetivo,
    db_prog_itens,
    db_ticket_activate,
    db_ticket_active,
    db_ticket_add_action,
    db_ticket_claim,
    db_ticket_config_get,
    db_ticket_deletion_candidates,
    db_ticket_finalize_with_auto_approval,
    db_ticket_finalization_logs,
    db_ticket_expired,
    db_ticket_get,
    db_ticket_get_channel,
    db_ticket_get_week,
    db_ticket_launch,
    db_ticket_launches,
    db_ticket_latest_action,
    db_ticket_list_existing,
    db_ticket_list_week,
    db_ticket_mark_corrected,
    db_ticket_mark_deleted,
    db_ticket_mark_log_attempt,
    db_ticket_mark_manual_deleted,
    db_ticket_pending_actions,
    db_ticket_has_pending_logs,
    db_ticket_release_failed,
    db_ticket_recalculate_completion,
    db_ticket_reserve,
    db_ticket_resolve_review,
    db_ticket_set_log_result,
    db_ticket_set_log_anchor,
    db_ticket_set_review,
    db_verificar_conclusao,
    now_tz,
)
from services.log_service import send_log
from services.set_service import MemberFolderError, resolve_member_folder

log = logging.getLogger("farm")
PROOF_TIMEOUT = 180.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
GERENTE_PRODUCAO_NAMES = (
    "| Gerente de Produ\u00e7\u00e3o",
    "Gerente de Produ\u00e7\u00e3o",
    "| Gerente de Producao",
    "Gerente de Producao",
)
GERENTE_PRODUTOS_NAMES = ("| Gerente de Produtos", "Gerente de Produtos")


def _is_image(attachment: discord.Attachment) -> bool:
    return (attachment.content_type or "").startswith("image/") or attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized[:80] or "membro"


def _row_get(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _message_id(message) -> str | None:
    value = getattr(message, "id", None)
    return str(value) if value is not None else None


def _discord_id(value) -> str | None:
    value = str(value or "").strip()
    return value if re.fullmatch(r"\d{15,25}", value) else None


def _as_int_role_ids(role_ids) -> list[int]:
    ids: list[int] = []
    for role_id in role_ids or []:
        try:
            parsed = int(role_id)
        except (TypeError, ValueError):
            continue
        if parsed not in ids:
            ids.append(parsed)
    return ids


def _expanded_admin_role_ids(guild: discord.Guild | None, role_ids) -> list[int]:
    ids = _as_int_role_ids(role_ids)
    if guild is None:
        return ids

    gerente_producao = find_role_by_names(guild, GERENTE_PRODUCAO_NAMES)
    gerente_produtos = find_role_by_names(guild, GERENTE_PRODUTOS_NAMES)
    if gerente_producao is None or gerente_produtos is None:
        return ids

    has_producao = gerente_producao.id in ids
    has_produtos = gerente_produtos.id in ids
    if has_producao and not has_produtos:
        ids.append(gerente_produtos.id)
    elif has_produtos and not has_producao:
        ids.append(gerente_producao.id)
    return ids


def _admin_roles_for_guild(guild: discord.Guild, role_ids) -> list[discord.Role]:
    roles = []
    for role_id in _expanded_admin_role_ids(guild, role_ids):
        role = guild.get_role(role_id)
        if role is not None:
            roles.append(role)
    return roles


def _fmt_value(value: float, money: bool) -> str:
    if money:
        return f"R$ {value:,.0f}".replace(",", ".")
    return f"{value:,.0f}".replace(",", ".")


def _active_targets(meta) -> tuple[str, dict[str, float]]:
    return db_meta_alvos_ativos(meta)


def _progress(ticket, meta) -> tuple[dict[str, float], dict[str, float], float, bool, list]:
    meta_type, targets = _active_targets(meta)
    launches = db_ticket_launches(int(ticket["id"]))
    progress = db_get_progresso(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
    totals = db_prog_itens(progress)
    delivered: dict[str, float] = {}
    if meta_type == "dinheiro" and "Dinheiro" in targets:
        delivered["Dinheiro"] = sum(totals.get(name, 0) for name in DINHEIRO_ITEMS)
    else:
        delivered = {name: totals.get(name, 0) for name in targets}
    ratios = [min(delivered.get(name, 0) / target, 1) for name, target in targets.items() if target > 0]
    percentage = (sum(ratios) / len(ratios) * 100) if ratios else 0
    completed = bool(ratios) and all(ratio >= 1 for ratio in ratios)
    return targets, delivered, percentage, completed, launches


def build_ticket_embed(ticket, member: discord.Member, meta) -> discord.Embed:
    targets, delivered, percentage, completed, launches = _progress(ticket, meta)
    status = ticket["status"]
    if status == "finalizado":
        color, status_text = discord.Color.blue(), "🔒 Finalizado"
    elif status == "revisao":
        color, status_text = discord.Color.red(), "⚠️ Em revisão"
    elif completed:
        color, status_text = discord.Color.green(), "✅ Meta atingida - aguardando finalização"
    else:
        color, status_text = discord.Color.orange(), "🔄 Em andamento"

    meta_type = db_meta_tipo_efetivo(meta)
    type_label = {"dinheiro": "Dinheiro", "colete": "Materiais de Colete", "itens": "Kit Desmanche"}.get(meta_type, meta_type.title())
    money = meta_type == "dinheiro"
    filled = round(percentage / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    lines = []
    for name, target in targets.items():
        current = delivered.get(name, 0)
        remaining = max(target - current, 0)
        lines.append(f"**{name}:** `{_fmt_value(current, money)}` / `{_fmt_value(target, money)}`\nRestante: `{_fmt_value(remaining, money)}`")

    embed = discord.Embed(
        title="📌 Controle de Farm Semanal",
        description=f"{bar}\n\n**📊 Progresso geral: {percentage:.0f}%**",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Membro", value=member.mention, inline=True)
    if ticket["folder_slot"] is not None:
        embed.add_field(name="📁 Slot da Pasta", value=f"`{int(ticket['folder_slot']):02d}`", inline=True)
        embed.add_field(name="🏷️ Apelido", value=ticket["folder_nickname"] or ticket["member_name"], inline=True)
        embed.add_field(name="🎮 ID do Jogo", value=f"`{ticket['game_id']}`", inline=True)
        if ticket["folder_channel_id"]:
            embed.add_field(name="🗂️ Pasta Individual", value=f"<#{ticket['folder_channel_id']}>", inline=False)
    embed.add_field(name="🎯 Farm ativo", value=type_label, inline=True)
    embed.add_field(name="📅 Semana", value=format_date_br(ticket["week_id"]), inline=True)
    embed.add_field(name="💰 Entregas e metas", value="\n\n".join(lines) or "Meta não configurada.", inline=False)
    embed.add_field(name="📝 Lançamentos", value=str(len(launches)), inline=True)
    embed.add_field(name="📌 Status", value=status_text, inline=True)
    assigned = f"<@{ticket['assigned_to']}>" if ticket["assigned_to"] else "Não assumido"
    embed.add_field(name="👮 Responsável", value=assigned, inline=True)
    general_progress = db_get_progresso(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
    if general_progress and general_progress["aprovada"]:
        approval = f"✅ Aprovada por <@{general_progress['aprovada_por']}>"
    elif completed:
        approval = "⏳ Aguardando aprovação"
    else:
        approval = "🔒 Disponível ao atingir 100%"
    embed.add_field(name="✅ Aprovação da meta", value=approval, inline=False)

    history = []
    for launch in launches[-5:][::-1]:
        values = db_evento_itens(launch)
        text = ", ".join(f"+{_fmt_value(float(value), money)} {name}" for name, value in values.items())
        history.append(f"• {text} — {format_datetime_br(launch['criado_em'])}")
    embed.add_field(name="📂 Últimos lançamentos", value="\n".join(history) or "Nenhum lançamento no ticket.", inline=False)
    embed.add_field(name="🕒 Última atualização", value=format_datetime_br(ticket["atualizado_em"]), inline=False)
    embed.set_footer(text="Sistema de Farm • Prazo semanal: domingo às 23:59")
    return embed


class TicketLinkView(discord.ui.View):
    def __init__(self, channel_url: str):
        super().__init__(timeout=60)
        self.add_item(discord.ui.Button(label="Acessar ticket", emoji="🎫", url=channel_url))


class FarmTicketLaunchModal(discord.ui.Modal):
    def __init__(self, cog: "FarmTicketsCog", ticket, targets: dict[str, float]):
        super().__init__(title="Lançar farm no ticket")
        self.cog = cog
        self.ticket_id = int(ticket["id"])
        self.item_names = list(targets)[:5]
        self.inputs: list[discord.ui.TextInput] = []
        for name in self.item_names:
            item = discord.ui.TextInput(label=name[:45], placeholder="0", required=False, max_length=20)
            self.add_item(item)
            self.inputs.append(item)

    async def on_submit(self, interaction: discord.Interaction):
        ticket = db_ticket_get(self.ticket_id)
        if not ticket or str(interaction.user.id) != ticket["user_id"]:
            await interaction.response.send_message("Este lançamento pertence ao dono do ticket.", ephemeral=True)
            return
        meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        meta_type, current_targets = _active_targets(meta)
        if list(current_targets)[:5] != self.item_names:
            await interaction.response.send_message("A meta ativa mudou. Abra o modal novamente.", ephemeral=True)
            return
        values = {}
        try:
            for name, field in zip(self.item_names, self.inputs):
                raw = (field.value or "0").replace("R$", "").replace(".", "").replace(",", ".").strip()
                value = float(raw or 0) if meta_type == "dinheiro" else int(raw or 0)
                if value < 0:
                    raise ValueError
                if value > 0:
                    if name == "Dinheiro":
                        name = DINHEIRO_ITEMS[0]
                    values[name] = value
        except ValueError:
            await interaction.response.send_message("Informe apenas valores positivos válidos.", ephemeral=True)
            return
        if not values:
            await interaction.response.send_message("Informe pelo menos um valor acima de zero.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Envie agora uma imagem neste canal. O texto da mensagem será usado como observação opcional. "
            "Nada será registrado se o prazo de 3 minutos expirar.",
            ephemeral=True,
        )

        def check(message: discord.Message) -> bool:
            return message.author.id == interaction.user.id and message.channel.id == interaction.channel_id and any(_is_image(a) for a in message.attachments)

        try:
            proof_message = await interaction.client.wait_for("message", check=check, timeout=PROOF_TIMEOUT)
        except asyncio.TimeoutError:
            await interaction.followup.send("Tempo esgotado. Nenhum lançamento foi registrado.", ephemeral=True)
            return

        ticket = db_ticket_get(self.ticket_id)
        latest_meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        _, latest_targets = _active_targets(latest_meta)
        valid_names = set(latest_targets)
        if "Dinheiro" in valid_names:
            valid_names = set(DINHEIRO_ITEMS)
        if not set(values).issubset(valid_names):
            await interaction.followup.send("A meta mudou durante o envio. Nada foi registrado.", ephemeral=True)
            return

        attachment = next(a for a in proof_message.attachments if _is_image(a))
        progress_before = db_get_progresso(
            ticket["guild_id"], ticket["week_id"], ticket["user_id"]
        )
        status_before = progress_before["status"] if progress_before else "em_andamento"
        event_id, action_id = db_ticket_launch(
            self.ticket_id, str(interaction.user.id), values,
            str(proof_message.channel.id), str(proof_message.id), attachment.url,
            proof_message.content.strip() or None,
        )
        db_verificar_conclusao(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
        progress_after = db_get_progresso(
            ticket["guild_id"], ticket["week_id"], ticket["user_id"]
        )
        await self.cog.log_launch(ticket, interaction.user, event_id, action_id, values, proof_message, attachment)
        await self.cog.refresh_ticket(self.ticket_id)
        farm_cog = interaction.client.get_cog("FarmCog")
        if farm_cog:
            await farm_cog._atualizar_painel(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
            await farm_cog._atualizar_ranking_fixo(ticket["guild_id"])
            if (
                status_before != "concluida"
                and progress_after
                and progress_after["status"] == "concluida"
            ):
                await farm_cog._notificar_conclusao(
                    interaction.guild, ticket["user_id"], ticket["week_id"]
                )
        await interaction.followup.send("✅ Lançamento registrado e painel atualizado.", ephemeral=True)


class FinalizeTicketModal(discord.ui.Modal, title="Finalizar ticket de farm"):
    reason = discord.ui.TextInput(label="Motivo / observação", required=False, style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, cog: "FarmTicketsCog", ticket_id: int):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        ticket = db_ticket_get(self.ticket_id)
        if not ticket or not self.cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão para finalizar.", ephemeral=True)
            return
        meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        completed = _progress(ticket, meta)[3]
        reason = self.reason.value.strip()
        await interaction.response.defer(ephemeral=True)
        finalized, message = await self.cog.finalizar_ticket(
            self.ticket_id,
            reason or "Finalizacao manual por administrador",
            interaction.user,
            action="finalizacao",
        )
        if not finalized:
            await interaction.followup.send(message, ephemeral=True)
            return
        channel = interaction.channel
        owner = interaction.guild.get_member(int(ticket["user_id"]))
        if owner and isinstance(channel, discord.TextChannel):
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            overwrite.attach_files = False
            await channel.set_permissions(owner, overwrite=overwrite, reason="Ticket de farm finalizado")
        await self.cog.refresh_ticket(self.ticket_id)
        await interaction.followup.send(
            "Ticket finalizado e entregas aprovadas automaticamente. O canal sera excluido ao fim da semana.",
            ephemeral=True,
        )
        return
        if not completed and not reason:
            await interaction.response.send_message("Informe um motivo para finalizar abaixo da meta.", ephemeral=True)
            return
        if not db_ticket_finalize(self.ticket_id, str(interaction.user.id), reason or None):
            await interaction.response.send_message("O ticket já foi finalizado.", ephemeral=True)
            return
        action_id = db_ticket_add_action(self.ticket_id, "finalizacao", str(interaction.user.id), payload={"motivo": reason, "meta_atingida": completed})
        await self.cog.send_action_log(db_ticket_get(self.ticket_id), action_id, "Ticket finalizado", interaction.user, reason or "Meta atingida")
        channel = interaction.channel
        owner = interaction.guild.get_member(int(ticket["user_id"]))
        if owner and isinstance(channel, discord.TextChannel):
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            overwrite.attach_files = False
            await channel.set_permissions(owner, overwrite=overwrite, reason="Ticket de farm finalizado")
        await self.cog.refresh_ticket(self.ticket_id)
        await interaction.response.send_message("Ticket finalizado. O canal será excluído ao fim da semana.", ephemeral=True)


class ReviewReasonModal(discord.ui.Modal, title="Marcar lançamento em revisão"):
    reason = discord.ui.TextInput(label="Motivo", required=True, style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, event_id: int):
        super().__init__()
        self.cog, self.ticket_id, self.event_id = cog, ticket_id, event_id

    async def on_submit(self, interaction: discord.Interaction):
        ticket = db_ticket_get(self.ticket_id)
        if not ticket or not self.cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        db_ticket_set_review(self.ticket_id, self.event_id, str(interaction.user.id), self.reason.value)
        action_id = db_ticket_add_action(self.ticket_id, "revisao", str(interaction.user.id), event_id=self.event_id, payload={"motivo": self.reason.value})
        await self.cog.send_action_log(db_ticket_get(self.ticket_id), action_id, "Lançamento em revisão", interaction.user, self.reason.value)
        await self.cog.refresh_ticket(self.ticket_id)
        await interaction.response.send_message("Lançamento marcado para revisão.", ephemeral=True)


class CorrectLaunchModal(discord.ui.Modal):
    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, event_id: int, values: dict):
        super().__init__(title="Corrigir lançamento")
        self.cog, self.ticket_id, self.event_id = cog, ticket_id, event_id
        self.names = list(values)[:5]
        self.inputs = []
        for name in self.names:
            field = discord.ui.TextInput(label=name[:45], default=str(values[name]), max_length=20)
            self.add_item(field)
            self.inputs.append(field)
        self.reason = None
        if len(self.names) < 5:
            self.reason = discord.ui.TextInput(label="Motivo da correção", required=True, max_length=200)
            self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        ticket = db_ticket_get(self.ticket_id)
        if not ticket or not self.cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        try:
            values = {name: float(field.value.replace(".", "").replace(",", ".")) for name, field in zip(self.names, self.inputs)}
            if any(value < 0 for value in values.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Valores inválidos.", ephemeral=True)
            return
        if not db_editar_evento(ticket["guild_id"], ticket["week_id"], ticket["user_id"], self.event_id, values):
            await interaction.response.send_message("Lançamento não encontrado.", ephemeral=True)
            return
        reason = self.reason.value if self.reason else "Correção administrativa de meta com cinco itens"
        db_ticket_mark_corrected(self.ticket_id, self.event_id, str(interaction.user.id), reason)
        db_ticket_recalculate_completion(self.ticket_id)
        action_id = db_ticket_add_action(self.ticket_id, "correcao", str(interaction.user.id), event_id=self.event_id, payload={"valores": values, "motivo": reason})
        await self.cog.send_action_log(db_ticket_get(self.ticket_id), action_id, "Lançamento corrigido", interaction.user, reason)
        await self.cog.refresh_ticket(self.ticket_id)
        await interaction.response.send_message("Lançamento corrigido.", ephemeral=True)


class ReviewActionsView(discord.ui.View):
    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, launch):
        super().__init__(timeout=120)
        self.cog, self.ticket_id, self.launch = cog, ticket_id, launch

    @discord.ui.button(label="Marcar problema", style=discord.ButtonStyle.danger)
    async def mark(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewReasonModal(self.cog, self.ticket_id, int(self.launch["id"])))

    @discord.ui.button(label="Corrigir valores", style=discord.ButtonStyle.primary)
    async def correct(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CorrectLaunchModal(self.cog, self.ticket_id, int(self.launch["id"]), db_evento_itens(self.launch)))

    @discord.ui.button(label="Resolver revisão", style=discord.ButtonStyle.success)
    async def resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = db_ticket_get(self.ticket_id)
        if not ticket or not self.cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        db_ticket_resolve_review(self.ticket_id, int(self.launch["id"]), str(interaction.user.id))
        action_id = db_ticket_add_action(self.ticket_id, "revisao_resolvida", str(interaction.user.id), event_id=int(self.launch["id"]))
        await self.cog.send_action_log(db_ticket_get(self.ticket_id), action_id, "Revisão resolvida", interaction.user, "Lançamento liberado")
        await self.cog.refresh_ticket(self.ticket_id)
        await interaction.response.send_message("Revisão resolvida.", ephemeral=True)


class ReviewSelect(discord.ui.Select):
    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, launches: list):
        self.cog, self.ticket_id = cog, ticket_id
        self.launches = {str(row["id"]): row for row in launches[-25:]}
        options = []
        for row in launches[-25:][::-1]:
            summary = ", ".join(f"{name}: {value}" for name, value in db_evento_itens(row).items())
            options.append(discord.SelectOption(label=f"Lançamento #{row['id']}", description=summary[:100], value=str(row["id"])))
        super().__init__(placeholder="Selecione um lançamento", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Escolha a ação administrativa:", view=ReviewActionsView(self.cog, self.ticket_id, self.launches[self.values[0]]))


class ReviewSelectView(discord.ui.View):
    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, launches: list):
        super().__init__(timeout=120)
        self.add_item(ReviewSelect(cog, ticket_id, launches))


class FarmTicketView(discord.ui.View):
    def __init__(self, finalized: bool = False, can_approve: bool = True, approved: bool = False):
        super().__init__(timeout=None)
        for child in self.children:
            if getattr(child, "custom_id", "") == "farm_ticket:approve":
                child.disabled = approved or not can_approve
        if finalized:
            for child in self.children:
                if getattr(child, "custom_id", "") != "farm_ticket:proofs":
                    child.disabled = True

    async def _context(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("FarmTicketsCog")
        ticket = db_ticket_get_channel(str(interaction.guild_id), str(interaction.channel_id))
        return cog, ticket

    @discord.ui.button(label="Lançar Farm", emoji="📤", style=discord.ButtonStyle.primary, custom_id="farm_ticket:launch", row=0)
    async def launch(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not cog or not ticket or ticket["status"] not in {"aberto", "revisao"}:
            await interaction.response.send_message("Ticket indisponível.", ephemeral=True)
            return
        if str(interaction.user.id) != ticket["user_id"]:
            await interaction.response.send_message("Somente o dono pode lançar farm.", ephemeral=True)
            return
        meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        _, targets = _active_targets(meta)
        if not targets:
            await interaction.response.send_message("Não há meta ativa configurada.", ephemeral=True)
            return
        await interaction.response.send_modal(FarmTicketLaunchModal(cog, ticket, targets))

    @discord.ui.button(label="Ver Comprovantes", emoji="📎", style=discord.ButtonStyle.secondary, custom_id="farm_ticket:proofs", row=0)
    async def proofs(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not ticket or (str(interaction.user.id) != ticket["user_id"] and not cog.is_admin(interaction.user, ticket["guild_id"])):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        links = []
        for row in db_ticket_launches(int(ticket["id"]))[-20:][::-1]:
            links.append(f"• [Lançamento #{row['id']}]({row['log_proof_url'] or row['proof_url']}) — {format_datetime_br(row['criado_em'])}")
        await interaction.response.send_message("\n".join(links) or "Nenhum comprovante registrado.", ephemeral=True)

    @discord.ui.button(label="Recolhimento", emoji="📥", style=discord.ButtonStyle.primary, custom_id="farm_ticket:collection", row=0)
    async def collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not cog or not ticket or not cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão administrativa.", ephemeral=True)
            return
        if ticket["status"] not in {"aberto", "revisao"}:
            await interaction.response.send_message("Ticket indisponível.", ephemeral=True)
            return
        recolhimento_cog = interaction.client.get_cog("RecolhimentoCog")
        if not recolhimento_cog:
            await interaction.response.send_message(
                "Sistema de recolhimento indisponível.", ephemeral=True
            )
            return
        modal = recolhimento_cog._modal_recolhimento_ticket(
            ticket, str(interaction.user.id)
        )
        if not modal:
            await interaction.response.send_message(
                "Não há uma meta ativa configurada para esta semana.", ephemeral=True
            )
            return
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Assumir Ticket", emoji="👮", style=discord.ButtonStyle.secondary, custom_id="farm_ticket:claim", row=1)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not ticket or not cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão administrativa.", ephemeral=True)
            return
        if not db_ticket_claim(int(ticket["id"]), str(interaction.user.id)):
            current = db_ticket_get(int(ticket["id"]))
            await interaction.response.send_message(f"Ticket já assumido por <@{current['assigned_to']}>.", ephemeral=True)
            return
        action_id = db_ticket_add_action(int(ticket["id"]), "assuncao", str(interaction.user.id))
        await cog.send_action_log(db_ticket_get(int(ticket["id"])), action_id, "Ticket assumido", interaction.user, "Atendimento iniciado")
        await cog.refresh_ticket(int(ticket["id"]))
        await interaction.response.send_message("Ticket assumido.", ephemeral=True)

    @discord.ui.button(label="Revisar", emoji="🔎", style=discord.ButtonStyle.secondary, custom_id="farm_ticket:review", row=1)
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not ticket or not cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão administrativa.", ephemeral=True)
            return
        launches = db_ticket_launches(int(ticket["id"]))
        if not launches:
            await interaction.response.send_message("Nenhum lançamento para revisar.", ephemeral=True)
            return
        await interaction.response.send_message("Selecione o lançamento:", view=ReviewSelectView(cog, int(ticket["id"]), launches), ephemeral=True)

    @discord.ui.button(label="Aprovar Meta", emoji="✅", style=discord.ButtonStyle.success, custom_id="farm_ticket:approve", row=1)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not ticket or not cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão administrativa.", ephemeral=True)
            return
        if ticket["status"] == "revisao":
            await interaction.response.send_message("Resolva as revisões pendentes antes de aprovar.", ephemeral=True)
            return
        meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        if not _progress(ticket, meta)[3]:
            await interaction.response.send_message("A meta deste ticket ainda não atingiu 100%.", ephemeral=True)
            return
        progress = db_get_progresso(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
        if progress and progress["aprovada"]:
            await interaction.response.send_message("Esta meta já foi aprovada.", ephemeral=True)
            return
        db_aprovar(ticket["guild_id"], ticket["week_id"], ticket["user_id"], str(interaction.user.id))
        action_id = db_ticket_add_action(
            int(ticket["id"]), "aprovacao", str(interaction.user.id),
            payload={"meta_atingida_no_ticket": True},
        )
        await cog.send_action_log(
            ticket, action_id, "Meta aprovada", interaction.user,
            "Aprovação individual realizada diretamente pelo ticket.",
        )
        farm_cog = interaction.client.get_cog("FarmCog")
        if farm_cog:
            await farm_cog._notificar_aprovacao(
                interaction.guild, ticket["user_id"], interaction.user, antecipada=False
            )
            await farm_cog._atualizar_ranking_fixo(ticket["guild_id"])
        await cog.refresh_ticket(int(ticket["id"]))
        await interaction.response.send_message("✅ Meta do membro aprovada pelo ticket.", ephemeral=True)

    @discord.ui.button(label="Finalizar Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="farm_ticket:finish", row=1)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, ticket = await self._context(interaction)
        if not ticket or not cog.is_admin(interaction.user, ticket["guild_id"]):
            await interaction.response.send_message("Sem permissão administrativa.", ephemeral=True)
            return
        await interaction.response.send_modal(FinalizeTicketModal(cog, int(ticket["id"])))


class ManualDeleteConfirmView(discord.ui.View):
    def __init__(self, cog: "FarmTicketsCog", ticket_id: int, admin_id: int):
        super().__init__(timeout=90)
        self.cog = cog
        self.ticket_id = ticket_id
        self.admin_id = admin_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("Esta confirmação pertence a outro administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar exclusão", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.delete_ticket_manually(interaction, self.ticket_id)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Exclusão cancelada.", view=None)


class AdminTicketSelect(discord.ui.Select):
    def __init__(self, cog: "FarmTicketsCog", tickets: list, admin_id: int):
        self.cog = cog
        self.tickets = {str(ticket["id"]): ticket for ticket in tickets}
        options = []
        for ticket in tickets:
            slot = f"{int(ticket['folder_slot']):02d}" if ticket["folder_slot"] is not None else "--"
            label = f"{slot} - {ticket['folder_nickname'] or ticket['member_name']}"
            description = f"Semana {format_date_br(ticket['week_id'])} • {ticket['status']}"
            options.append(
                discord.SelectOption(label=label[:100], description=description[:100], value=str(ticket["id"]))
            )
        super().__init__(placeholder="Selecione o ticket para excluir", options=options)
        self.admin_id = admin_id

    async def callback(self, interaction: discord.Interaction):
        ticket = self.tickets[self.values[0]]
        channel_text = f"<#{ticket['channel_id']}>" if ticket["channel_id"] else f"ticket #{ticket['id']}"
        await interaction.response.edit_message(
            content=(
                f"⚠️ Confirme a exclusão manual de {channel_text}.\n"
                "O canal será apagado, mas lançamentos, progresso e logs serão preservados."
            ),
            view=ManualDeleteConfirmView(self.cog, int(ticket["id"]), self.admin_id),
        )


class AdminTicketListView(discord.ui.View):
    PAGE_SIZE = 25

    def __init__(self, cog: "FarmTicketsCog", tickets: list, admin_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.cog = cog
        self.tickets = tickets
        self.admin_id = admin_id
        self.page = page
        self.total_pages = max(1, (len(tickets) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        start = page * self.PAGE_SIZE
        page_tickets = tickets[start:start + self.PAGE_SIZE]
        if page_tickets:
            self.add_item(AdminTicketSelect(cog, page_tickets, admin_id))
        self.previous.disabled = page <= 0
        self.next.disabled = page >= self.total_pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("Este gerenciador pertence a outro administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"Tickets existentes • página {self.page}/{self.total_pages}",
            view=AdminTicketListView(self.cog, self.tickets, self.admin_id, self.page - 1),
        )

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"Tickets existentes • página {self.page + 2}/{self.total_pages}",
            view=AdminTicketListView(self.cog, self.tickets, self.admin_id, self.page + 1),
        )


class FarmTicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(FarmTicketView())
        self.cleanup_task.start()
        self.deadline_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()
        self.deadline_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if getattr(self, "_tickets_reconciled", False):
            return
        self._tickets_reconciled = True
        for ticket in db_ticket_active():
            await self.refresh_ticket(int(ticket["id"]))

    def is_admin(self, member: discord.Member, guild_id: str) -> bool:
        if member.guild_permissions.administrator:
            return True
        config = db_ticket_config_get(guild_id)
        allowed = set(
            _expanded_admin_role_ids(
                getattr(member, "guild", None),
                (config or {}).get("admin_role_ids", []),
            )
        )
        return bool(allowed.intersection(role.id for role in member.roles))

    async def ensure_ticket_admin_overwrites(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> None:
        config = db_ticket_config_get(str(guild.id)) or {}
        for role in _admin_roles_for_guild(guild, config.get("admin_role_ids", [])):
            overwrite = channel.overwrites_for(role)
            if (
                overwrite.view_channel is True
                and overwrite.send_messages is True
                and overwrite.read_message_history is True
                and overwrite.manage_messages is True
            ):
                continue
            overwrite.view_channel = True
            overwrite.send_messages = True
            overwrite.read_message_history = True
            overwrite.manage_messages = True
            await channel.set_permissions(
                role,
                overwrite=overwrite,
                reason="Sincronizacao de cargos administrativos dos tickets de farm",
            )

    async def lock_ticket_channel(self, ticket, guild: discord.Guild) -> None:
        if not ticket["channel_id"]:
            return
        channel = guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        owner = guild.get_member(int(ticket["user_id"]))
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            overwrite.attach_files = False
            await channel.set_permissions(owner, overwrite=overwrite, reason="Prazo do ticket de farm encerrado")

    def ticket_member_display(self, ticket) -> str:
        user_id = _discord_id(_row_get(ticket, "user_id"))
        if user_id:
            return f"<@{user_id}>"
        fallback = (
            _row_get(ticket, "folder_nickname")
            or _row_get(ticket, "member_name")
            or _row_get(ticket, "user_id")
        )
        return str(fallback or "Membro sem identificacao")

    def build_ticket_log_summary_embed(
        self,
        ticket,
        *,
        last_title: str = "Log iniciado",
        last_detail: str = "-",
    ) -> discord.Embed:
        meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
        try:
            _, _, percentage, completed, launches = _progress(ticket, meta)
        except Exception:
            percentage, completed, launches = 0, False, []

        status = ticket["status"]
        if status == "finalizado":
            color = discord.Color.blue()
        elif status == "revisao":
            color = discord.Color.red()
        elif completed:
            color = discord.Color.green()
        else:
            color = discord.Color.gold()

        embed = discord.Embed(
            title="Ticket de farm",
            description="Resumo consolidado. Os detalhes e comprovantes ficam na thread desta mensagem.",
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        embed.add_field(
            name="Ticket",
            value=f"<#{ticket['channel_id']}>" if ticket["channel_id"] else f"#{ticket['id']}",
            inline=True,
        )
        embed.add_field(name="Semana", value=format_date_br(ticket["week_id"]), inline=True)
        embed.add_field(name="Status", value=str(status).replace("_", " ").title(), inline=True)
        embed.add_field(name="Progresso", value=f"{percentage:.0f}%", inline=True)
        embed.add_field(name="Lancamentos", value=str(len(launches)), inline=True)
        embed.add_field(
            name="Responsavel",
            value=f"<@{ticket['assigned_to']}>" if ticket["assigned_to"] else "Nao assumido",
            inline=True,
        )
        if ticket["finalizado_em"]:
            embed.add_field(
                name="Finalizacao",
                value=f"{format_datetime_br(ticket['finalizado_em'])}\n{ticket['finalizacao_motivo'] or '-'}",
                inline=False,
            )
        embed.add_field(
            name="Ultima acao",
            value=f"**{last_title}**\n{(last_detail or '-')[:900]}",
            inline=False,
        )
        embed.set_footer(text=f"Ticket #{ticket['id']} | logs consolidados")
        return embed

    def ticket_log_thread_name(self, ticket) -> str:
        slot = f"{int(ticket['folder_slot']):02d}" if ticket["folder_slot"] is not None else str(ticket["id"])
        name = ticket["folder_nickname"] or ticket["member_name"] or f"ticket-{ticket['id']}"
        return f"ticket-farm-{slot}-{_slug(name)}"[:100]

    async def farm_log_channel(self, guild: discord.Guild):
        row = db_get_system_config(str(guild.id), "farm")
        if not row or not row["canal_log_id"]:
            log.info("Tickets de farm sem canal de log configurado (guild %s)", guild.id)
            return None
        channel_id = int(row["canal_log_id"])
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except Exception:
                log.warning("Canal de log do farm nao encontrado: %s", channel_id, exc_info=True)
                return None
        return channel if hasattr(channel, "send") else None

    async def ensure_ticket_log_thread(
        self,
        ticket,
        *,
        last_title: str = "Log iniciado",
        last_detail: str = "-",
    ):
        guild = self.bot.get_guild(int(ticket["guild_id"]))
        if not guild:
            return None, None
        channel = await self.farm_log_channel(guild)
        if channel is None:
            return None, None

        summary = None
        message_id = _row_get(ticket, "log_message_id")
        if message_id:
            try:
                summary = await channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden):
                summary = None
            except Exception:
                log.warning("Falha ao buscar resumo de log do ticket %s", ticket["id"], exc_info=True)
                summary = None

        if summary is None:
            try:
                summary = await channel.send(
                    embed=self.build_ticket_log_summary_embed(
                        ticket,
                        last_title=last_title,
                        last_detail=last_detail,
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                log.warning("Falha ao criar resumo de log do ticket %s", ticket["id"], exc_info=True)
                return None, None
            db_ticket_set_log_anchor(int(ticket["id"]), message_id=str(summary.id))
            ticket = db_ticket_get(int(ticket["id"])) or ticket

        thread = getattr(summary, "thread", None)
        thread_id = _row_get(ticket, "log_thread_id")
        if thread is None and thread_id:
            get_thread = getattr(guild, "get_thread", None)
            thread = get_thread(int(thread_id)) if get_thread else None
            if thread is None:
                try:
                    fetched = await guild.fetch_channel(int(thread_id))
                    if isinstance(fetched, discord.Thread):
                        thread = fetched
                except (discord.NotFound, discord.Forbidden):
                    thread = None
                except Exception:
                    log.warning("Falha ao buscar thread de log do ticket %s", ticket["id"], exc_info=True)
                    thread = None

        if thread is None:
            try:
                thread = await summary.create_thread(name=self.ticket_log_thread_name(ticket))
            except Exception:
                log.warning("Falha ao criar thread de log do ticket %s", ticket["id"], exc_info=True)
                return summary, None
            db_ticket_set_log_anchor(int(ticket["id"]), thread_id=str(thread.id))

        return summary, thread

    async def update_ticket_log_summary(
        self,
        ticket,
        summary,
        *,
        last_title: str,
        last_detail: str,
    ) -> None:
        if summary is None:
            return
        latest = db_ticket_get(int(ticket["id"])) or ticket
        try:
            await summary.edit(
                embed=self.build_ticket_log_summary_embed(
                    latest,
                    last_title=last_title,
                    last_detail=last_detail,
                )
            )
        except Exception:
            log.warning("Falha ao atualizar resumo de log do ticket %s", ticket["id"], exc_info=True)

    def build_ticket_action_embed(self, ticket, title: str, actor, detail: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        actor_mention = getattr(actor, "mention", f"<@{actor.id}>")
        embed.add_field(name="Responsavel", value=actor_mention, inline=True)
        embed.add_field(
            name="Ticket",
            value=f"<#{ticket['channel_id']}>" if ticket["channel_id"] else f"#{ticket['id']}",
            inline=True,
        )
        embed.add_field(name="Detalhes", value=(detail or "-")[:1024], inline=False)
        return embed

    async def send_finalization_log(self, result: dict, actor, detail: str) -> bool:
        ticket = result["ticket"]
        logs = result.get("logs") or []
        action_ids = {
            action_id
            for action_id in (result.get("action_id"), result.get("approval_action_id"))
            if action_id
        }
        summary, thread = await self.ensure_ticket_log_thread(
            ticket,
            last_title="Ticket finalizado",
            last_detail=detail,
        )
        if thread is None:
            for action_id in action_ids:
                db_ticket_mark_log_attempt(action_id)
            return False

        embed = discord.Embed(
            title="🎫 Ticket finalizado com aprovação automática",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        actor_mention = getattr(actor, "mention", f"<@{actor.id}>")
        embed.add_field(name="Responsável", value=actor_mention, inline=True)
        embed.add_field(
            name="Ticket",
            value=f"<#{ticket['channel_id']}>" if ticket["channel_id"] else f"#{ticket['id']}",
            inline=True,
        )
        lines = []
        for row in logs:
            money = row["item"] in {"Dinheiro", *DINHEIRO_ITEMS}
            entregue = _fmt_value(float(row["quantidade_entregue"]), money)
            meta = _fmt_value(float(row["quantidade_meta"]), money)
            lines.append(
                f"**{row['item']}:** {entregue} / {meta} — `{row['status_final']}`"
            )
        embed.add_field(
            name="Entregas aprovadas",
            value="\n".join(lines)[:1024] if lines else "Nenhuma meta ativa vinculada ao ticket.",
            inline=False,
        )
        embed.add_field(name="Motivo", value=detail[:1024] or "-", inline=False)
        try:
            result_message = await thread.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except Exception:
            log.warning("Falha ao enviar log final do ticket %s", ticket["id"], exc_info=True)
            result_message = None
        message_id = _message_id(result_message)
        if message_id:
            for action_id in action_ids:
                db_ticket_set_log_result(action_id, message_id=message_id)
            await self.update_ticket_log_summary(
                ticket,
                summary,
                last_title="Ticket finalizado",
                last_detail=detail,
            )
            return True
        for action_id in action_ids:
            db_ticket_mark_log_attempt(action_id)
        return False

    async def finalizar_ticket(
        self,
        ticket_id: int,
        motivo: str,
        actor,
        *,
        action: str = "finalizacao",
    ) -> tuple[bool, str]:
        try:
            result = db_ticket_finalize_with_auto_approval(
                ticket_id,
                str(actor.id),
                motivo,
                action=action,
            )
        except Exception:
            log.exception("Falha ao finalizar ticket %s", ticket_id)
            return False, "Nao foi possivel salvar a finalizacao no banco. O canal nao foi alterado."

        if not result["processed"]:
            return False, "O ticket ja foi finalizado."

        logged = await self.send_finalization_log(result, actor, motivo)
        if not logged:
            return False, "O ticket foi finalizado no banco, mas o log do Discord ficou pendente. O canal nao foi apagado."
        return True, "Ticket finalizado."

    async def show_admin_ticket_manager(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem excluir tickets manualmente.", ephemeral=True
            )
            return
        tickets = db_ticket_list_existing(str(interaction.guild_id))
        config = db_ticket_config_get(str(interaction.guild_id)) or {}
        category_ids = {str(value) for value in config.get("category_ids", [])}
        valid = []
        for ticket in tickets:
            channel = interaction.guild.get_channel(int(ticket["channel_id"])) if ticket["channel_id"] else None
            if channel and str(channel.category_id) in category_ids:
                valid.append(ticket)
        if not valid:
            await interaction.response.send_message(
                "Não há tickets rastreados nas categorias configuradas.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Tickets existentes • página 1/{max(1, (len(valid) + 24) // 25)}",
            view=AdminTicketListView(self, valid, interaction.user.id),
            ephemeral=True,
        )

    async def delete_ticket_manually(self, interaction: discord.Interaction, ticket_id: int) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Somente administradores podem excluir tickets.", ephemeral=True)
            return
        ticket = db_ticket_get(ticket_id)
        if not ticket or not ticket["channel_id"] or ticket["excluido_em"]:
            await interaction.response.edit_message(content="Este ticket já foi excluído.", view=None)
            return
        if db_ticket_has_pending_logs(ticket_id):
            await interaction.response.edit_message(
                content="O ticket possui logs ou comprovantes pendentes. Aguarde a sincronização antes de excluir.",
                view=None,
            )
            return
        config = db_ticket_config_get(ticket["guild_id"]) or {}
        category_ids = {str(value) for value in config.get("category_ids", [])}
        channel = interaction.guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel) or str(channel.category_id) not in category_ids:
            await interaction.response.edit_message(
                content="O canal não pertence a uma categoria configurada de tickets.", view=None
            )
            return
        await interaction.response.defer(ephemeral=True)
        ticket = db_ticket_get(ticket_id)
        if ticket and ticket["status"] != "finalizado" and not ticket["finalizado_em"]:
            finalized, message = await self.finalizar_ticket(
                ticket_id,
                "Ticket expirado - aprovação automática",
                interaction.user,
                action="exclusao_manual_finalizacao",
            )
            if not finalized:
                await interaction.followup.send(message, ephemeral=True)
                return
            ticket = db_ticket_get(ticket_id)
            if db_ticket_has_pending_logs(ticket_id):
                await interaction.followup.send(
                    "A finalizacao gerou logs pendentes. O canal nao foi excluido.",
                    ephemeral=True,
                )
                return
        reason = "Exclusão manual confirmada por administrador"
        action_id = db_ticket_add_action(
            ticket_id, "exclusao_manual", str(interaction.user.id), payload={"motivo": reason}
        )
        logged = await self.send_action_log(
            ticket, action_id, "Ticket excluído manualmente", interaction.user, reason
        )
        if not logged:
            await interaction.followup.send(
                "Não foi possível registrar o log. O canal não foi excluído.", ephemeral=True
            )
            return
        await channel.delete(reason=reason)
        db_ticket_mark_manual_deleted(ticket_id, str(interaction.user.id), reason)
        await interaction.followup.send(
            "Ticket excluído. Lançamentos, progresso e logs foram preservados.", ephemeral=True
        )

    async def refresh_ticket(self, ticket_id: int) -> None:
        ticket = db_ticket_get(ticket_id)
        if not ticket or not ticket["channel_id"] or not ticket["panel_message_id"]:
            return
        guild = self.bot.get_guild(int(ticket["guild_id"]))
        if not guild:
            return
        try:
            channel = guild.get_channel(int(ticket["channel_id"])) or await guild.fetch_channel(int(ticket["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                await self.ensure_ticket_admin_overwrites(guild, channel)
            message = await channel.fetch_message(int(ticket["panel_message_id"]))
            member = guild.get_member(int(ticket["user_id"])) or await guild.fetch_member(int(ticket["user_id"]))
            meta = db_get_meta(ticket["guild_id"], ticket["week_id"])
            completed = _progress(ticket, meta)[3]
            progress = db_get_progresso(ticket["guild_id"], ticket["week_id"], ticket["user_id"])
            approved = bool(progress and progress["aprovada"])
            await message.edit(
                embed=build_ticket_embed(ticket, member, meta),
                view=FarmTicketView(
                    finalized=ticket["status"] == "finalizado",
                    can_approve=completed and ticket["status"] != "revisao",
                    approved=approved,
                ),
            )
        except (discord.NotFound, discord.Forbidden):
            log.warning("Painel do ticket %s não pôde ser atualizado", ticket_id)

    async def refresh_week(self, guild_id: str, week_id: str) -> None:
        for ticket in db_ticket_list_week(guild_id, week_id):
            await self.refresh_ticket(int(ticket["id"]))

    async def send_action_log(self, ticket, action_id: int, title: str, actor, detail: str):
        guild = self.bot.get_guild(int(ticket["guild_id"]))
        if not guild:
            db_ticket_mark_log_attempt(action_id)
            return False
        embed = discord.Embed(title=f"🎫 {title}", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        actor_mention = getattr(actor, "mention", f"<@{actor.id}>")
        embed.add_field(name="Responsável", value=actor_mention, inline=True)
        embed.add_field(name="Ticket", value=f"<#{ticket['channel_id']}>" if ticket["channel_id"] else f"#{ticket['id']}", inline=True)
        embed.add_field(name="Detalhes", value=detail[:1024] or "-", inline=False)
        result = await send_log(self.bot, guild, "farm", embed, return_message=True)
        if isinstance(result, discord.Message):
            db_ticket_set_log_result(action_id, message_id=str(result.id))
            return True
        db_ticket_mark_log_attempt(action_id)
        return False

    async def log_launch(self, ticket, actor, event_id: int, action_id: int, values: dict, proof_message, attachment):
        guild = self.bot.get_guild(int(ticket["guild_id"]))
        if not guild:
            db_ticket_mark_log_attempt(action_id)
            return
        embed = discord.Embed(title="📤 Farm lançado no ticket", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        embed.add_field(name="Ticket", value=f"<#{ticket['channel_id']}>", inline=True)
        embed.add_field(name="Farm ativo", value=db_meta_tipo_efetivo(db_get_meta(ticket["guild_id"], ticket["week_id"])).title(), inline=True)
        embed.add_field(name="Valores", value="\n".join(f"**{name}:** {value}" for name, value in values.items()), inline=False)
        embed.add_field(name="Observação", value=proof_message.content[:1024] or "Sem observação", inline=False)
        embed.add_field(name="Status", value="Registrado", inline=True)
        try:
            file = await attachment.to_file(use_cached=True)
            embed.set_image(url=f"attachment://{file.filename}")
            result = await send_log(self.bot, guild, "farm", embed, files=[file], return_message=True)
        except Exception:
            result = False
            log.exception("Falha ao copiar comprovante do ticket %s", ticket["id"])
        if isinstance(result, discord.Message):
            log_url = result.attachments[0].url if result.attachments else attachment.url
            db_ticket_set_log_result(action_id, message_id=str(result.id), event_id=event_id, proof_url=log_url)
        else:
            db_ticket_mark_log_attempt(action_id)

    async def send_action_log(self, ticket, action_id: int, title: str, actor, detail: str):
        summary, thread = await self.ensure_ticket_log_thread(
            ticket,
            last_title=title,
            last_detail=detail,
        )
        if thread is None:
            db_ticket_mark_log_attempt(action_id)
            return False
        embed = self.build_ticket_action_embed(ticket, title, actor, detail)
        try:
            result = await thread.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except Exception:
            log.warning("Falha ao enviar log de acao do ticket %s", ticket["id"], exc_info=True)
            result = None
        message_id = _message_id(result)
        if message_id:
            db_ticket_set_log_result(action_id, message_id=message_id)
            await self.update_ticket_log_summary(
                ticket,
                summary,
                last_title=title,
                last_detail=detail,
            )
            return True
        db_ticket_mark_log_attempt(action_id)
        return False

    async def log_launch(self, ticket, actor, event_id: int, action_id: int, values: dict, proof_message, attachment):
        detail = ", ".join(f"{name}: {value}" for name, value in values.items())
        summary, thread = await self.ensure_ticket_log_thread(
            ticket,
            last_title="Farm lancado no ticket",
            last_detail=detail,
        )
        if thread is None:
            db_ticket_mark_log_attempt(action_id)
            return
        embed = discord.Embed(title="Farm lancado no ticket", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membro", value=self.ticket_member_display(ticket), inline=True)
        embed.add_field(name="Ticket", value=f"<#{ticket['channel_id']}>", inline=True)
        embed.add_field(name="Farm ativo", value=db_meta_tipo_efetivo(db_get_meta(ticket["guild_id"], ticket["week_id"])).title(), inline=True)
        embed.add_field(name="Valores", value="\n".join(f"**{name}:** {value}" for name, value in values.items()), inline=False)
        embed.add_field(name="Observacao", value=proof_message.content[:1024] or "Sem observacao", inline=False)
        embed.add_field(name="Status", value="Registrado", inline=True)
        try:
            file = await attachment.to_file(use_cached=True)
            embed.set_image(url=f"attachment://{file.filename}")
            result = await thread.send(
                embed=embed,
                files=[file],
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except Exception:
            result = None
            log.exception("Falha ao copiar comprovante do ticket %s", ticket["id"])
        message_id = _message_id(result)
        if message_id:
            log_url = result.attachments[0].url if result.attachments else attachment.url
            db_ticket_set_log_result(action_id, message_id=message_id, event_id=event_id, proof_url=log_url)
            await self.update_ticket_log_summary(
                ticket,
                summary,
                last_title="Farm lancado no ticket",
                last_detail=detail,
            )
        else:
            db_ticket_mark_log_attempt(action_id)

    async def open_ticket(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        config = db_ticket_config_get(guild_id)
        if not config:
            await interaction.response.send_message("Tickets de farm ainda não foram configurados no dashboard.", ephemeral=True)
            return
        meta = db_get_meta(guild_id, week_id)
        if not _active_targets(meta)[1]:
            await interaction.response.send_message("A meta ativa da semana ainda não foi definida.", ephemeral=True)
            return
        existing = db_ticket_get_week(guild_id, week_id, str(interaction.user.id))
        if existing:
            if existing["channel_id"]:
                channel = interaction.guild.get_channel(int(existing["channel_id"]))
                if channel:
                    await interaction.response.send_message(
                        "Você já possui um ticket nesta semana.",
                        view=TicketLinkView(channel.jump_url),
                        ephemeral=True,
                    )
                    return
            await interaction.response.send_message(
                "Seu ticket está sendo criado. Tente acessar novamente em alguns segundos.",
                ephemeral=True,
            )
            return

        guild_config = db_get_guild_config(guild_id)
        if not guild_config or not guild_config["private_category_id"]:
            await interaction.response.send_message(
                "A categoria de pastas individuais não está configurada.", ephemeral=True
            )
            return
        try:
            folder = await resolve_member_folder(
                interaction.guild,
                guild_id,
                interaction.user,
                int(guild_config["private_category_id"]),
            )
        except MemberFolderError as exc:
            log.warning("Ticket bloqueado por pasta inválida: guild=%s user=%s erro=%s", guild_id, interaction.user.id, exc)
            await interaction.response.send_message(
                f"❌ Não foi possível identificar sua pasta individual: {exc}\n"
                "Procure a administração para regularizar a pasta antes de abrir o ticket.",
                ephemeral=True,
            )
            return

        ticket, created = db_ticket_reserve(
            guild_id,
            week_id,
            str(interaction.user.id),
            interaction.user.display_name,
            folder_channel_id=str(folder.channel_id),
            folder_slot=folder.slot,
            game_id=folder.game_id,
            folder_nickname=folder.nickname,
        )
        if not created:
            if ticket["channel_id"]:
                channel = interaction.guild.get_channel(int(ticket["channel_id"]))
                if channel:
                    await interaction.response.send_message("Você já possui um ticket nesta semana.", view=TicketLinkView(channel.jump_url), ephemeral=True)
                    return
            await interaction.response.send_message("Seu ticket está sendo criado. Tente acessar novamente em alguns segundos.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        channel = None
        try:
            categories = []
            for category_id in config["category_ids"]:
                category = interaction.guild.get_channel(int(category_id))
                if isinstance(category, discord.CategoryChannel):
                    categories.append(category)
            category = next((item for item in categories if len(item.channels) < 50), None)
            if not category:
                raise RuntimeError("Todas as categorias configuradas estão lotadas ou inválidas.")
            admin_roles = _admin_roles_for_guild(interaction.guild, config["admin_role_ids"])
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True, read_message_history=True),
            }
            for role in admin_roles:
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
            slot_label = f"{folder.slot:02d}"
            base_name = f"farm-{slot_label}-{_slug(folder.nickname)}-{folder.game_id}"
            existing_names = {channel.name for cat in categories for channel in cat.text_channels}
            channel_name = base_name if base_name not in existing_names else f"{base_name[:75]}-{str(interaction.user.id)[-4:]}"
            channel = await interaction.guild.create_text_channel(channel_name, category=category, overwrites=overwrites, reason="Ticket semanal de farm")
            provisional = dict(ticket)
            provisional["channel_id"] = str(channel.id)
            provisional["status"] = "aberto"
            message = await channel.send(
                content=interaction.user.mention,
                embed=build_ticket_embed(provisional, interaction.user, meta),
                view=FarmTicketView(can_approve=False),
            )
            try:
                await message.pin(reason="Painel principal do ticket de farm")
            except discord.Forbidden:
                pass
            db_ticket_activate(int(ticket["id"]), str(channel.id), str(message.id))
            action_id = db_ticket_add_action(int(ticket["id"]), "abertura", str(interaction.user.id))
            await self.send_action_log(
                db_ticket_get(int(ticket["id"])), action_id, "Ticket aberto", interaction.user,
                f"Semana {format_date_br(ticket['week_id'])} • Pasta {slot_label} • ID {folder.game_id}",
            )
            await interaction.followup.send("Ticket criado com sucesso.", view=TicketLinkView(channel.jump_url), ephemeral=True)
        except Exception as exc:
            if channel is not None:
                try:
                    await channel.delete(reason="Falha durante criação do ticket de farm")
                except Exception:
                    log.exception("Falha ao remover canal órfão de ticket")
            db_ticket_release_failed(int(ticket["id"]))
            log.exception("Falha ao criar ticket de farm")
            await interaction.followup.send(f"Não foi possível criar o ticket: {exc}", ephemeral=True)

    @tasks.loop(minutes=15)
    async def cleanup_task(self):
        await self.bot.wait_until_ready()
        await self.retry_pending_logs()
        for ticket in db_ticket_deletion_candidates(current_week_id()):
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            if not guild or not ticket["channel_id"]:
                continue
            channel = guild.get_channel(int(ticket["channel_id"]))
            if not channel:
                db_ticket_mark_deleted(int(ticket["id"]))
                continue
            actor = guild.me
            deletion_action = db_ticket_latest_action(int(ticket["id"]), "exclusao")
            log_ready = bool(deletion_action and deletion_action["log_enviado_em"])
            if not deletion_action:
                action_id = db_ticket_add_action(int(ticket["id"]), "exclusao", str(actor.id), payload={"motivo": "fim_da_semana"})
                log_ready = await self.send_action_log(ticket, action_id, "Canal de ticket excluído", actor, "Retenção encerrada no fim da semana")
            if log_ready:
                await channel.delete(reason="Fim da retenção semanal do ticket de farm")
                db_ticket_mark_deleted(int(ticket["id"]))

    @tasks.loop(minutes=1)
    async def deadline_task(self):
        await self.bot.wait_until_ready()
        current_week = current_week_id()
        for ticket in db_ticket_expired(current_week):
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            if not guild:
                continue
            reason = "Prazo semanal de entrega encerrado (domingo 23:59)"
            finalized_ok, message = await self.finalizar_ticket(
                int(ticket["id"]),
                reason,
                guild.me,
                action="prazo_encerrado",
            )
            if not finalized_ok:
                log.warning("Ticket expirado %s nao foi fechado: %s", ticket["id"], message)
                continue
            finalized = db_ticket_get(int(ticket["id"]))
            try:
                await self.lock_ticket_channel(finalized, guild)
                await self.refresh_ticket(int(ticket["id"]))
            except Exception:
                log.exception("Falha ao bloquear ticket expirado %s", ticket["id"])

    async def retry_pending_logs(self) -> None:
        titles = {
            "abertura": "Ticket aberto",
            "assuncao": "Ticket assumido",
            "revisao": "Lançamento em revisão",
            "revisao_resolvida": "Revisão resolvida",
            "correcao": "Lançamento corrigido",
            "aprovacao": "Meta aprovada",
            "finalizacao": "Ticket finalizado",
            "exclusao_manual_finalizacao": "Ticket finalizado",
            "exclusao": "Canal de ticket excluído",
            "exclusao_manual": "Ticket excluído manualmente",
            "prazo_encerrado": "Prazo do ticket encerrado",
        }
        for action in db_ticket_pending_actions():
            ticket = db_ticket_get(int(action["ticket_id"]))
            guild = self.bot.get_guild(int(action["guild_id"]))
            if not ticket or not guild:
                db_ticket_mark_log_attempt(int(action["id"]))
                continue
            actor = guild.get_member(int(action["actor_id"])) or discord.Object(id=int(action["actor_id"]))
            payload = json.loads(action["payload_json"] or "{}")
            if payload.get("aprovacao_automatica") or (
                action["action"] == "aprovacao" and payload.get("automatica")
            ):
                final_action = None
                for action_name in (
                    "exclusao_manual_finalizacao",
                    "prazo_encerrado",
                    "finalizacao",
                ):
                    final_action = db_ticket_latest_action(int(ticket["id"]), action_name)
                    if final_action:
                        break
                approval_action = db_ticket_latest_action(int(ticket["id"]), "aprovacao")
                detail = payload.get("motivo") or "Ticket expirado - aprovação automática"
                await self.send_finalization_log(
                    {
                        "ticket": ticket,
                        "logs": db_ticket_finalization_logs(int(ticket["id"])),
                        "action_id": int(final_action["id"]) if final_action else int(action["id"]),
                        "approval_action_id": int(approval_action["id"]) if approval_action else None,
                    },
                    actor,
                    detail,
                )
                continue
            if action["action"] == "lancamento" and action["event_id"]:
                launch = next((row for row in db_ticket_launches(int(ticket["id"])) if int(row["id"]) == int(action["event_id"])), None)
                if not launch:
                    db_ticket_mark_log_attempt(int(action["id"]))
                    continue
                try:
                    channel = guild.get_channel(int(launch["proof_channel_id"])) or await guild.fetch_channel(int(launch["proof_channel_id"]))
                    proof_message = await channel.fetch_message(int(launch["proof_message_id"]))
                    attachment = next(item for item in proof_message.attachments if _is_image(item))
                    await self.log_launch(ticket, actor, int(launch["id"]), int(action["id"]), db_evento_itens(launch), proof_message, attachment)
                except Exception:
                    db_ticket_mark_log_attempt(int(action["id"]))
                    log.exception("Falha ao reenviar log do lançamento %s", action["event_id"])
                continue
            detail = payload.get("motivo") or payload.get("detalhes") or json.dumps(payload, ensure_ascii=False)
            await self.send_action_log(ticket, int(action["id"]), titles.get(action["action"], action["action"].replace("_", " ").title()), actor, detail or "-")

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @deadline_task.before_loop
    async def before_deadline(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmTicketsCog(bot))
