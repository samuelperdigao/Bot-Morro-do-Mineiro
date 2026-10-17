"""Painel privado para consultar pendentes da semana de Farm atualmente aberta."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.farm_policy import (
    farm_week_membership,
    is_farm_manager,
    is_farm_warning_eligible,
    member_joined_date,
    previous_farm_week_id,
)
from core.logger import get_logger
from services.db_service import (
    current_week_id,
    db_farm_report_get,
    db_farm_report_set_panel,
    db_farm_report_set_report_message,
    db_get_meta,
    db_get_permitidos_role_ids,
    db_is_farm_configured,
    db_meta_tipo_efetivo,
    db_ticket_config_get,
)
from services.farm_status_service import build_farm_week_snapshot

log = get_logger("farm_relatorio", "farm.log")

REPORT_CHANNEL_NAME = "┃📊-relatório-farm"
REPORT_FIELD_LIMIT = 1000
REPORT_FIELDS_PER_EMBED = 5


def previous_week_id(week_id: str | None = None) -> str:
    return previous_farm_week_id(week_id or current_week_id())


def format_report_week_range(week_id: str) -> str:
    start = date.fromisoformat(week_id)
    end = start + timedelta(days=6)
    return f"{start.strftime('%d/%m')} a {end.strftime('%d/%m')}"


def is_main_farm_category(category: discord.CategoryChannel) -> bool:
    name = category.name.casefold()
    return "farm" in name and "ticket" not in name


def can_generate_report(member: discord.Member, guild_id: str) -> bool:
    if member.guild_permissions.administrator:
        return True
    config = db_ticket_config_get(guild_id) or {}
    allowed = {int(role_id) for role_id in config.get("admin_role_ids", [])}
    return bool(allowed.intersection(role.id for role in member.roles))


def snapshot_eligible_members(
    guild: discord.Guild,
    guild_id: str,
    week_id: str | None = None,
) -> list[dict[str, str]]:
    week_id = week_id or current_week_id()
    permitted_role_ids = db_get_permitidos_role_ids(guild_id)
    members = [
        {"user_id": str(member.id), "display_name": member.display_name}
        for member in guild.members
        if (
            not member.bot
            and is_farm_warning_eligible(member, permitted_role_ids)
            and not is_farm_manager(member)
            and farm_week_membership(member, week_id) == "obrigado"
        )
    ]
    return sorted(members, key=lambda member: member["display_name"].casefold())


def report_member_control(
    guild: discord.Guild,
    guild_id: str,
    week_id: str,
    snapshot_members: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Separa obrigados atuais, novos isentos e membros que sairam.

    O snapshot preserva quem tinha obrigacao no fechamento. A intersecao com
    os membros atuais garante que quem saiu do servidor nunca apareca como
    pendente quando o relatorio for consultado.
    """
    current_by_id = {
        str(member.id): member
        for member in guild.members
        if not getattr(member, "bot", False)
    }
    present: list[dict[str, str]] = []
    departed: list[dict[str, str]] = []
    exempt_by_id: dict[str, dict[str, str]] = {}
    for item in snapshot_members:
        user_id = str(item["user_id"])
        member = current_by_id.get(user_id)
        if member is None:
            departed.append(item)
            continue
        membership = farm_week_membership(member, week_id)
        if membership == "obrigado":
            present.append(item)
        elif membership == "isento_entrada":
            joined_date = member_joined_date(member)
            exempt_by_id[user_id] = {
                "user_id": user_id,
                "display_name": member.display_name,
                "joined_date": joined_date.isoformat() if joined_date else "",
            }

    permitted_role_ids = db_get_permitidos_role_ids(guild_id)
    for member in guild.members:
        if (
            getattr(member, "bot", False)
            or not is_farm_warning_eligible(member, permitted_role_ids)
            or is_farm_manager(member)
            or farm_week_membership(member, week_id) != "isento_entrada"
        ):
            continue
        joined_date = member_joined_date(member)
        exempt_by_id[str(member.id)] = {
            "user_id": str(member.id),
            "display_name": member.display_name,
            "joined_date": joined_date.isoformat() if joined_date else "",
        }

    key = lambda member: member.get("display_name", "").casefold()
    return (
        sorted(present, key=key),
        sorted(exempt_by_id.values(), key=key),
        sorted(departed, key=key),
    )


def _meta_label(meta) -> str:
    return {
        "dinheiro": "Farm Padrão da Semana — Dinheiro",
        "colete": "Farm Padrão da Semana — Materiais de colete",
        "itens": "Farm Padrão da Semana — Itens de produção",
    }.get(db_meta_tipo_efetivo(meta), "Farm Padrão da Semana")


def _chunk_pending_names(names: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for name in names:
        line = f"- {name}"
        added_length = len(line) + (1 if current else 0)
        if current and current_length + added_length > REPORT_FIELD_LIMIT:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += len(line) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _chunk_report_lines(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        added_length = len(line) + (1 if current else 0)
        if current and current_length + added_length > REPORT_FIELD_LIMIT:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += added_length
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_pending_report_embeds(
    meta,
    week_id: str,
    required_members: list[dict[str, str]],
    approved_user_ids: set[str],
    *,
    exempt_members: list[dict[str, str]] | None = None,
    departed_members: list[dict[str, str]] | None = None,
    status_snapshot: dict | None = None,
) -> list[discord.Embed]:
    exempt_members = exempt_members or []
    departed_members = departed_members or []
    if status_snapshot is None:
        required_ids = {str(member["user_id"]) for member in required_members}
        delivered_ids = required_ids.intersection(approved_user_ids)
        delivered_members = [
            member
            for member in required_members
            if str(member["user_id"]) in delivered_ids
        ]
        partial_members: list[dict] = []
        absence_members: list[dict] = []
        manager_members: list[dict] = []
        pending = [
            member
            for member in required_members
            if str(member["user_id"]) not in delivered_ids
        ]
    else:
        required_members = status_snapshot.get("obrigados", [])
        required_ids = {str(member["user_id"]) for member in required_members}
        delivered_members = status_snapshot.get("entregaram", [])
        delivered_ids = {str(member["user_id"]) for member in delivered_members}
        partial_members = status_snapshot.get("parciais", [])
        absence_members = status_snapshot.get("ausentes", [])
        manager_members = status_snapshot.get("gerentes", [])
        pending = status_snapshot.get("pendentes", [])

    delivered_members.sort(key=lambda member: member.get("display_name", "").casefold())
    partial_members.sort(key=lambda member: member.get("display_name", "").casefold())
    absence_members.sort(key=lambda member: member.get("display_name", "").casefold())
    manager_members.sort(key=lambda member: member.get("display_name", "").casefold())
    pending.sort(key=lambda member: member.get("display_name", "").casefold())

    summary = (
        f"📅 **Período:** {format_report_week_range(week_id)}\n"
        f"🎯 **Meta:** {_meta_label(meta)}\n"
        f"👥 **Membros obrigados:** {len(required_ids)}\n"
        f"✅ **Entregaram:** {len(delivered_ids)}\n"
        f"❌ **Pendentes:** {len(pending)}\n"
        f"🟡 **Parciais:** {len(partial_members)}\n"
        f"📌 **Ausências:** {len(absence_members)}\n"
        f"🛡️ **Isentos (entraram na semana):** {len(exempt_members)}\n"
        f"🧑‍💼 **Gerentes — decisão manual:** {len(manager_members)}"
    )
    if departed_members and status_snapshot is None:
        summary += (
            f"\n🚪 **Desconsiderados (saíram do servidor):** "
            f"{len(departed_members)}"
        )
    if not pending:
        summary += "\n\n✅ Todos os membros obrigados entregaram a meta desta semana."

    first = discord.Embed(
        title="📋 Relatório de Farm — Semana Atual",
        description=summary,
        color=discord.Color.green() if not pending else discord.Color.red(),
    )
    embeds = [first]

    # Mantém a renderização legada para chamadas externas/testes antigos. O
    # fluxo oficial do cog usa ``status_snapshot`` e renderiza todas as abas.
    if status_snapshot is None:
        for index, chunk in enumerate(
            _chunk_pending_names(
                [member.get("display_name") or "Apelido indisponível" for member in pending]
            )
        ):
            current = embeds[-1]
            if len(current.fields) >= REPORT_FIELDS_PER_EMBED:
                current = discord.Embed(
                    title="📋 Relatório de Pendentes — Continuação",
                    color=discord.Color.red(),
                )
                embeds.append(current)
            current.add_field(
                name="❌ Não entregaram:" if index == 0 else "❌ Não entregaram (continuação):",
                value=chunk,
                inline=False,
            )
        for embed in embeds:
            embed.set_footer(
                text="Morro do Mineiro • semana aberta • atualização automática"
            )
        return embeds

    sections = [
        (
            "✅ Entregaram",
            [f"- {member.get('display_name') or 'Apelido indisponível'}" for member in delivered_members],
        ),
        (
            "🟡 Parciais — cobrança manual",
            [
                f"- {member.get('display_name') or 'Apelido indisponível'} ({member.get('pct', 0)}%)"
                for member in partial_members
            ],
        ),
        (
            "❌ Pendentes",
            [f"- {member.get('display_name') or 'Apelido indisponível'}" for member in pending],
        ),
        (
            "📌 Ausências",
            [f"- {member.get('display_name') or 'Apelido indisponível'}" for member in absence_members],
        ),
        (
            "🛡️ Isentos — entrada na semana",
            [
                f"- {member.get('display_name') or 'Apelido indisponível'}"
                for member in exempt_members
            ],
        ),
        (
            "🧑‍💼 Gerentes — decisão manual",
            [
                (
                    f"- {member.get('display_name') or 'Apelido indisponível'} — entrou na semana"
                    if member.get("status") == "isento_entrada"
                    else f"- {member.get('display_name') or 'Apelido indisponível'} — entregou"
                    if member.get("status") == "entregou"
                    else f"- {member.get('display_name') or 'Apelido indisponível'} — parcial ({member.get('pct', 0)}%)"
                    if member.get("status") == "parcial"
                    else f"- {member.get('display_name') or 'Apelido indisponível'} — ausência registrada"
                    if member.get("status") == "ausente"
                    else f"- {member.get('display_name') or 'Apelido indisponível'} — pendente, não aplicar automaticamente"
                )
                for member in manager_members
            ],
        ),
    ]
    for name, lines in sections:
        if not lines:
            continue
        for index, chunk in enumerate(_chunk_report_lines(lines)):
            current = embeds[-1]
            if len(current.fields) >= REPORT_FIELDS_PER_EMBED:
                current = discord.Embed(
                    title="📋 Relatório de Farm — Continuação",
                    color=discord.Color.red(),
                )
                embeds.append(current)
            suffix = "" if index == 0 else " (continuação)"
            current.add_field(name=f"{name}{suffix}", value=chunk, inline=False)

    for embed in embeds:
        embed.set_footer(
            text="Morro do Mineiro • semana aberta • gerentes exigem decisão manual"
        )
    return embeds


def build_report_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📊 Relatório de Pendentes de Farm",
        description=(
            "Acompanhe a **semana atualmente aberta** com as regras de participação "
            "aplicadas automaticamente.\n\n"
            "🛡️ Quem entrou durante a semana fica **isento**.\n"
            "🚪 Quem saiu do servidor é **retirado da contagem**.\n"
            "🧑‍💼 Gerentes aparecem em seção própria e exigem decisão manual.\n"
            "🔄 O relatório é atualizado automaticamente a cada 5 minutos.\n"
            "📋 Use o botão para atualizar imediatamente."
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Morro do Mineiro • Sistema de Farm")
    return embed


def build_no_meta_report_embed(week_id: str) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001F4CB Relatório de Pendentes — Semana Atual",
        description=(
            f"\U0001F4C5 **Período:** {format_report_week_range(week_id)}\n\n"
            "⏳ A meta desta semana ainda não foi configurada. O relatório será "
            "preenchido automaticamente assim que a meta estiver disponível."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Morro do Mineiro • semana aberta • aguardando meta")
    return embed


def build_report_overwrites(
    guild: discord.Guild, admin_role_ids: list[str]
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    for role_id in admin_role_ids:
        role = guild.get_role(int(role_id))
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            )
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            manage_messages=True,
        )
    return overwrites


class FarmPendingReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔄 Atualizar Relatório Agora",
        style=discord.ButtonStyle.primary,
        custom_id="farm_pending_report:generate",
    )
    async def generate(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmPendingReportCog")
        if cog is None:
            await interaction.response.send_message(
                "❌ O relatório de Farm está indisponível no momento.", ephemeral=True
            )
            return
        await cog.generate_report(interaction)


class FarmPendingReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._permissions_reconciled = False
        bot.add_view(FarmPendingReportView())
        self.report_refresh_task.start()

    def cog_unload(self):
        self.report_refresh_task.cancel()

    async def _get_text_channel(
        self, guild: discord.Guild, channel_id: str | None
    ) -> discord.TextChannel | None:
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _configure_channel_permissions(
        self, channel: discord.TextChannel, admin_role_ids: list[str]
    ) -> None:
        await channel.edit(
            overwrites=build_report_overwrites(channel.guild, admin_role_ids),
            reason="Canal privado do relatório semanal de Farm",
        )

    async def _get_or_create_channel(
        self,
        guild: discord.Guild,
        ticket_config: dict,
        requested_channel: discord.TextChannel | None,
    ) -> discord.TextChannel:
        if requested_channel is not None:
            category = requested_channel.category
            if (
                not isinstance(category, discord.CategoryChannel)
                or not is_main_farm_category(category)
            ):
                raise ValueError("O canal precisa estar dentro da categoria principal de Farm.")
            return requested_channel

        ticket_categories = [
            guild.get_channel(int(category_id))
            for category_id in ticket_config["category_ids"]
        ]
        ticket_categories = [
            category
            for category in ticket_categories
            if isinstance(category, discord.CategoryChannel)
        ]
        category = next(
            (item for item in guild.categories if is_main_farm_category(item)),
            ticket_categories[0] if ticket_categories else None,
        )
        if category is None:
            raise ValueError("Nenhuma categoria de Farm foi encontrada.")

        for channel in guild.text_channels:
            if channel.name == REPORT_CHANNEL_NAME and channel.category_id == category.id:
                return channel

        return await guild.create_text_channel(
            REPORT_CHANNEL_NAME,
            category=category,
            overwrites=build_report_overwrites(guild, ticket_config["admin_role_ids"]),
            reason="Criação do painel de relatório semanal de Farm",
        )

    async def _upsert_panel(self, channel: discord.TextChannel) -> discord.Message:
        guild_id = str(channel.guild.id)
        config = db_farm_report_get(guild_id) or {}
        panel_message = None
        if config.get("channel_id") == str(channel.id) and config.get("panel_message_id"):
            try:
                panel_message = await channel.fetch_message(int(config["panel_message_id"]))
            except discord.NotFound:
                panel_message = None

        if panel_message is None:
            panel_message = await channel.send(
                embed=build_report_panel_embed(), view=FarmPendingReportView()
            )
        else:
            await panel_message.edit(
                content=None, embed=build_report_panel_embed(), view=FarmPendingReportView()
            )

        report_message_id = (
            config.get("report_message_id")
            if config.get("channel_id") == str(channel.id)
            else None
        )
        db_farm_report_set_panel(
            guild_id, str(channel.id), str(panel_message.id), report_message_id
        )
        return panel_message

    async def _upsert_report_message(
        self, channel: discord.TextChannel, embeds: list[discord.Embed]
    ) -> discord.Message:
        guild_id = str(channel.guild.id)
        config = db_farm_report_get(guild_id) or {}
        report_message = None
        if config.get("report_message_id"):
            try:
                report_message = await channel.fetch_message(int(config["report_message_id"]))
            except discord.NotFound:
                report_message = None

        if report_message is None:
            report_message = await channel.send(embeds=embeds)
        else:
            await report_message.edit(content=None, embeds=embeds)
        db_farm_report_set_report_message(guild_id, str(report_message.id))
        return report_message

    async def _refresh_current_report(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | None = None,
    ) -> tuple[str, bool]:
        guild_id = str(guild.id)
        week_id = current_week_id()
        config = db_farm_report_get(guild_id) or {}
        channel = channel or await self._get_text_channel(guild, config.get("channel_id"))
        if channel is None:
            raise LookupError("Canal do relatório não encontrado.")

        meta = db_get_meta(guild_id, week_id)
        if meta is None:
            await self._upsert_report_message(
                channel,
                [build_no_meta_report_embed(week_id)],
            )
            return week_id, False

        status_snapshot = build_farm_week_snapshot(guild, guild_id, week_id)
        embeds = build_pending_report_embeds(
            meta,
            week_id,
            status_snapshot.get("obrigados", []),
            set(),
            exempt_members=status_snapshot.get("isentos", []),
            status_snapshot=status_snapshot,
        )
        await self._upsert_report_message(channel, embeds)
        return week_id, True

    async def generate_report(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        guild_id = str(interaction.guild_id)
        if guild is None or not can_generate_report(interaction.user, guild_id):
            await interaction.response.send_message(
                "❌ Apenas os responsáveis pelos tickets de Farm podem atualizar este relatório.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        config = db_farm_report_get(guild_id)
        if not config:
            await interaction.followup.send(
                "❌ O painel do relatório ainda não foi configurado.",
                ephemeral=True,
            )
            return

        channel = await self._get_text_channel(guild, config.get("channel_id"))
        if channel is None:
            await interaction.followup.send(
                "❌ O canal do relatório não foi encontrado. Execute `/setup_relatorio_farm` novamente.",
                ephemeral=True,
            )
            return
        week_id, meta_available = await self._refresh_current_report(guild, channel)
        status = "atualizado" if meta_available else "aguardando a configuração da meta"
        await interaction.followup.send(
            f"✅ Relatório da semana aberta `{format_report_week_range(week_id)}` {status}.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_ready(self):
        if self._permissions_reconciled:
            return
        self._permissions_reconciled = True
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            report_config = db_farm_report_get(guild_id)
            ticket_config = db_ticket_config_get(guild_id)
            if not report_config or not ticket_config:
                continue
            channel = await self._get_text_channel(guild, report_config.get("channel_id"))
            if channel is None:
                continue
            try:
                await self._configure_channel_permissions(
                    channel, ticket_config["admin_role_ids"]
                )
                await self._upsert_panel(channel)
                await self._refresh_current_report(guild, channel)
            except discord.HTTPException:
                log.exception(
                    "Falha ao reconciliar painel e permissões do relatório na guild %s",
                    guild.id,
                )

    @tasks.loop(minutes=5)
    async def report_refresh_task(self):
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            if not db_is_farm_configured(guild_id) or not db_ticket_config_get(guild_id):
                continue
            if not db_farm_report_get(guild_id):
                continue
            try:
                await self._refresh_current_report(guild)
            except Exception:
                log.exception(
                    "Falha ao atualizar automaticamente o relatório de Farm na guild %s",
                    guild.id,
                )

    @report_refresh_task.before_loop
    async def before_report_refresh_task(self):
        await self.bot.wait_until_ready()
        # O on_ready faz a primeira atualizacao; evita uma segunda edicao concorrente.
        await asyncio.sleep(10)

    @app_commands.command(
        name="setup_relatorio_farm",
        description="Cria ou atualiza o painel privado de pendentes do Farm.",
    )
    @app_commands.describe(
        canal="Canal dentro de uma categoria de tickets de Farm; se vazio, será criado."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_report_panel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ Configure primeiro o sistema de Farm.", ephemeral=True
            )
            return
        ticket_config = db_ticket_config_get(guild_id)
        if not ticket_config:
            await interaction.response.send_message(
                "❌ Configure primeiro as categorias e os cargos administrativos dos tickets de Farm.",
                ephemeral=True,
            )
            return
        valid_admin_roles = [
            interaction.guild.get_role(int(role_id))
            for role_id in ticket_config["admin_role_ids"]
        ]
        if not any(valid_admin_roles):
            await interaction.response.send_message(
                "❌ Nenhum cargo administrativo configurado para os tickets existe no servidor.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            channel = await self._get_or_create_channel(
                interaction.guild, ticket_config, canal
            )
            await self._configure_channel_permissions(
                channel, ticket_config["admin_role_ids"]
            )
            await self._upsert_panel(channel)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        except discord.HTTPException:
            log.exception("Falha ao configurar painel de relatório na guild %s", guild_id)
            await interaction.followup.send(
                "❌ Não foi possível criar ou atualizar o painel. Verifique as permissões do bot.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Painel de relatório de Farm configurado em {channel.mention}.",
            ephemeral=True,
        )

    @setup_report_panel.error
    async def setup_report_panel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão Gerenciar Servidor.", ephemeral=True
            )
            return
        log.error("Erro em /setup_relatorio_farm: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmPendingReportCog(bot))
    log.info("FarmPendingReportCog carregado.")
