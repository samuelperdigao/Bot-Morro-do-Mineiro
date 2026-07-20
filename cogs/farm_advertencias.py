"""Advertencias automaticas por falta de entrega completa do farm semanal."""

from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands

from core.config import BASE_DIR
from core.date_utils import format_week_range_br
from core.logger import get_logger
from core.permissions import is_lideranca
from cogs.hierarquia import HIERARQUIA_CARGOS
from services.db_service import (
    current_week_id,
    db_farm_adv_fechamento_claim,
    db_farm_adv_fechamento_criar,
    db_farm_adv_fechamento_finalizar,
    db_farm_adv_fechamento_get,
    db_farm_advertencia_criar,
    db_farm_advertencia_remover,
    db_farm_advertencia_status,
    db_farm_advertencias_usuario,
    db_farm_ausencia_registrar,
    db_farm_ausencia_user_ids,
    db_farm_ausencias_semana,
    db_get_farm_adv_panel,
    db_get_farm_adv_role_ids,
    db_get_guild_config,
    db_get_lideranca_role_ids,
    db_get_meta,
    db_get_permitidos_role_ids,
    db_get_system_config,
    db_is_farm_configured,
    db_ranking_semana,
    db_set_farm_adv_panel,
    db_set_farm_adv_role_ids,
    db_set_system_config,
)
from services.log_service import send_log

log = get_logger("farm_advertencias", "farm.log")

SYSTEM_KEY = "farm_advertencias"
COR_ADV = 0xD64545
COR_INFO = 0xF0A500
MOTIVO_FALTA = "Nao entregou o farm da semana"
PANEL_CHANNEL_NAME = "┃⚠️-advertencias-farm"
LOG_CHANNEL_NAME = "┃📋-log-adv"
PANEL_TITLE = "Painel de Advertências do Farm"
LEGACY_PANEL_TITLES = {
    "painel de advertencias do farm",
    "painel de advertência",
}
PANEL_LOGO_PATH = BASE_DIR / "assets" / "farm_advertencias" / "logo.jpg"
PANEL_LOGO_FILENAME = "mdm-logo.jpg"
WARNING_ROLE_NAMES = {
    1: "Advertência 1",
    2: "Advertência 2",
    3: "Advertência 3",
}
WARNING_ROLE_COLORS = {
    1: 0xF1C40F,
    2: 0xE67E22,
    3: 0xC0392B,
}

PUNICOES = {
    1: {"multa": 300_000, "dias": 3, "titulo": "1a Advertencia"},
    2: {"multa": 500_000, "dias": 5, "titulo": "2a Advertencia"},
    3: {"multa": 0, "dias": 0, "titulo": "3a Advertencia / PD"},
}

HIERARQUIA_CORTE_ADVERTENCIA = "| 02"


def _fmt_money(value: int) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


def _display(item: dict) -> str:
    return item.get("display_name") or f"ID {item['user_id']}"


def _member_line(item: dict) -> str:
    return f"`{_display(item)}`"


def _chunk(lines: list[str], limit: int = 950) -> list[str]:
    if not lines:
        return ["-"]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        add = len(line) + (1 if current else 0)
        if current and size + add > limit:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += add
    if current:
        chunks.append("\n".join(current))
    return chunks


def _highest_hierarchy_index(member: discord.Member) -> int | None:
    indexes = [
        HIERARQUIA_CARGOS.index(getattr(role, "name", ""))
        for role in member.roles
        if getattr(role, "name", "") in HIERARQUIA_CARGOS
    ]
    return max(indexes) if indexes else None


def is_farm_warning_eligible(member: discord.Member, permitted_role_ids: list[int]) -> bool:
    if member.bot:
        return False
    if {role.id for role in member.roles} & set(permitted_role_ids):
        return True
    cutoff = HIERARQUIA_CARGOS.index(HIERARQUIA_CORTE_ADVERTENCIA)
    member_index = _highest_hierarchy_index(member)
    return member_index is not None and member_index < cutoff


def next_warning_level_from_history(guild_id: str, user_id: str) -> int | None:
    active_levels = {
        int(row["nivel"])
        for row in db_farm_advertencias_usuario(guild_id, user_id)
        if row["status"] == "ativa"
    }
    if 3 in active_levels:
        return None
    if 2 in active_levels:
        return 3
    if 1 in active_levels:
        return 2
    return 1


def _role_config_complete(role_ids: dict[int, str]) -> bool:
    return all(role_ids.get(level) for level in (1, 2, 3))


async def ensure_farm_warning_roles(guild: discord.Guild) -> dict[int, str]:
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        raise PermissionError("O bot precisa da permissao Gerenciar Cargos.")

    role_ids: dict[int, str] = {}
    for nivel, name in WARNING_ROLE_NAMES.items():
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(
                name=name,
                colour=discord.Colour(WARNING_ROLE_COLORS[nivel]),
                hoist=False,
                mentionable=False,
                reason="Criacao dos cargos oficiais de advertencia do Farm",
            )
        if bot_member.top_role <= role:
            raise PermissionError(
                f"O cargo do bot precisa ficar acima de {name} para aplicar advertencias."
            )
        role_ids[nivel] = str(role.id)
    return role_ids


def build_farm_warning_preview(
    guild: discord.Guild,
    guild_id: str,
    week_id: str,
) -> dict:
    role_ids = db_get_farm_adv_role_ids(guild_id)
    if not _role_config_complete(role_ids):
        raise ValueError("Configure os tres cargos de advertencia antes de gerar a previa.")

    if db_get_meta(guild_id, week_id) is None:
        raise ValueError("Nenhuma meta de Farm foi encontrada para a semana ativa.")

    permitidos_ids = db_get_permitidos_role_ids(guild_id)
    members = sorted(
        [
            member
            for member in guild.members
            if is_farm_warning_eligible(member, permitidos_ids)
        ],
        key=lambda member: member.display_name.casefold(),
    )
    ranking = {
        str(row["user_id"]): row
        for row in db_ranking_semana(guild_id, week_id, [str(member.id) for member in members])
    }
    ausentes_ids = db_farm_ausencia_user_ids(guild_id, week_id)

    entregaram: list[dict] = []
    parciais: list[dict] = []
    ausentes: list[dict] = []
    pendentes: list[dict] = []

    for member in members:
        user_id = str(member.id)
        row = ranking.get(user_id, {})
        classificacao = row.get("classificacao", "zero")
        base = {
            "user_id": user_id,
            "display_name": member.display_name,
            "classificacao": classificacao,
            "pct": row.get("pct", 0),
        }
        if classificacao in {"elite", "meta_batida"}:
            entregaram.append(base)
        elif user_id in ausentes_ids:
            ausentes.append(base)
        elif classificacao == "parcial":
            parciais.append(base)
        else:
            nivel = next_warning_level_from_history(guild_id, user_id)
            base["nivel"] = nivel
            base["status"] = "ja_pd" if nivel is None else "advertir"
            pendentes.append(base)

    return {
        "guild_id": guild_id,
        "week_id": week_id,
        "role_ids": role_ids,
        "entregaram": entregaram,
        "parciais": parciais,
        "ausentes": ausentes,
        "pendentes": pendentes,
    }


def build_preview_embed(snapshot: dict, *, title: str = "🌾 Fechamento do Farm - Previa") -> discord.Embed:
    week_id = snapshot["week_id"]
    pendentes = snapshot.get("pendentes", [])
    parciais = snapshot.get("parciais", [])
    embed = discord.Embed(
        title=title,
        description=(
            f"**Semana:** `{format_week_range_br(week_id)}`\n"
            f"✅ **Completo:** `{len(snapshot.get('entregaram', []))}`\n"
            f"🟡 **Incompleto:** `{len(parciais)}`\n"
            f"📌 **Ausencias:** `{len(snapshot.get('ausentes', []))}`\n"
            f"⚠️ **Zerados para advertencia:** `{len(pendentes)}`"
        ),
        color=COR_ADV if pendentes else discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    sections = [
        ("✅ Entregaram completo", [_member_line(item) for item in snapshot.get("entregaram", [])]),
        (
            "🟡 Farm incompleto - cobrar manualmente",
            [
                f"`{_display(item)}` - {item.get('pct', 0)}%"
                for item in parciais
            ],
        ),
        ("📌 Ausencia registrada", [_member_line(item) for item in snapshot.get("ausentes", [])]),
        (
            "⚠️ Receberao advertencia",
            [
                (
                    f"`{_display(item)}` -> ja esta em PD"
                    if item.get("nivel") is None
                    else f"`{_display(item)}` -> Advertencia {item['nivel']}"
                )
                for item in pendentes
            ],
        ),
    ]
    for name, lines in sections:
        for index, chunk in enumerate(_chunk(lines)):
            field_name = name if index == 0 else f"{name} (cont.)"
            embed.add_field(name=field_name, value=chunk, inline=False)
    embed.set_footer(text="Parcial nao aplica advertencia. Contagem iniciada pelo novo sistema.")
    return embed


def build_absence_embed(member: discord.Member, week_id: str, motivo: str) -> discord.Embed:
    embed = discord.Embed(
        title="AUSENCIA REGISTRADA",
        color=COR_INFO,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Membro", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="Semana do farm", value=format_week_range_br(week_id), inline=True)
    embed.add_field(name="Motivo", value=motivo[:1000], inline=False)
    embed.add_field(name="Status", value="Ausencia valida para a semana ativa", inline=False)
    return embed


def build_warning_embed(member: discord.Member, nivel: int) -> discord.Embed:
    punicao = PUNICOES[nivel]
    if nivel == 3:
        embed = discord.Embed(
            title="PD - 3a ADVERTENCIA",
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Membro", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Motivo", value="Nao entregou o farm novamente", inline=False)
        embed.add_field(name="Status", value="O membro chegou na 3a advertencia", inline=False)
        embed.add_field(
            name="Aviso",
            value="O membro atingiu o limite de advertencias e deve receber PD conforme as regras da organizacao.",
            inline=False,
        )
        return embed

    embed = discord.Embed(
        title="ADVERTENCIA APLICADA",
        color=COR_ADV,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Membro", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="Motivo", value=MOTIVO_FALTA, inline=False)
    embed.add_field(name="Advertencia", value=punicao["titulo"], inline=True)
    embed.add_field(name="Multa", value=_fmt_money(punicao["multa"]), inline=True)
    embed.add_field(name="Punicao", value=f"{punicao['dias']} dias sem desmanchar carro", inline=True)
    return embed


async def _fetch_text_channel(guild: discord.Guild, channel_id: str | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def _ensure_channel_name(channel: discord.TextChannel, expected_name: str) -> None:
    if channel.name == expected_name:
        return
    await channel.edit(
        name=expected_name,
        reason="Padronizacao do sistema de advertencias do Farm",
    )


def build_panel_embed(guild: discord.Guild, guild_id: str) -> discord.Embed:
    embed = discord.Embed(
        title=PANEL_TITLE,
        description=(
            "**Fechamento semanal com prévia antes da aplicação.**\n\n"
            "📊 Gere a lista organizada antes de punir.\n"
            "🟡 Farm parcial aparece apenas para cobrança da liderança.\n"
            "⚠️ Use advertência individual para um membro zerado específico.\n"
            "🧹 Remova uma advertência aplicada por engano."
        ),
        color=COR_ADV,
        timestamp=discord.utils.utcnow(),
    )
    if PANEL_LOGO_PATH.exists():
        embed.set_image(url=f"attachment://{PANEL_LOGO_FILENAME}")
    embed.set_footer(text="Sistema de Advertencia • Farm")
    return embed


def panel_logo_file() -> discord.File | None:
    if not PANEL_LOGO_PATH.exists():
        return None
    return discord.File(PANEL_LOGO_PATH, filename=PANEL_LOGO_FILENAME)


class FarmAdvertenciasPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Gerar previa",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        custom_id="farm_adv:preview",
    )
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.gerar_previa(interaction)

    @discord.ui.button(
        label="Ausencias",
        emoji="📌",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_adv:ausencias",
    )
    async def ausencias(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.listar_ausencias(interaction)

    @discord.ui.button(
        label="Consultar",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_adv:consultar",
    )
    async def consultar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.abrir_consulta(interaction)

    @discord.ui.button(
        label="Advertencia individual",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="farm_adv:individual",
    )
    async def individual(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.abrir_individual(interaction)

    @discord.ui.button(
        label="Remover",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
        custom_id="farm_adv:remover",
    )
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.abrir_remocao(interaction)


class ApplyPreviewView(discord.ui.View):
    def __init__(self, fechamento_id: int, owner_id: int):
        super().__init__(timeout=300)
        self.fechamento_id = fechamento_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta confirmacao pertence a outro responsavel.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Aplicar advertencias", style=discord.ButtonStyle.danger)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmAdvertenciasCog")
        if cog:
            await cog.aplicar_fechamento(interaction, self.fechamento_id)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Aplicacao cancelada.", view=None)


class ConsultMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(placeholder="Selecione o membro", min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Membro nao encontrado.", ephemeral=True)
            return
        await self.cog.enviar_consulta(interaction, member)


class ConsultMemberView(discord.ui.View):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(timeout=120)
        self.add_item(ConsultMemberSelect(cog))


class IndividualWarningSelect(discord.ui.UserSelect):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(placeholder="Selecione quem nao lancou o farm", min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Membro nao encontrado.", ephemeral=True)
            return
        await self.cog.aplicar_individual(interaction, member)


class IndividualWarningView(discord.ui.View):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(timeout=120)
        self.add_item(IndividualWarningSelect(cog))


class RemoveMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(placeholder="Selecione o membro", min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Membro nao encontrado.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Escolha qual advertencia remover de {member.mention}:",
            view=RemoveLevelView(self.cog, member),
            ephemeral=True,
        )


class RemoveMemberView(discord.ui.View):
    def __init__(self, cog: "FarmAdvertenciasCog"):
        super().__init__(timeout=120)
        self.add_item(RemoveMemberSelect(cog))


class RemoveLevelSelect(discord.ui.Select):
    def __init__(self, cog: "FarmAdvertenciasCog", member: discord.Member):
        self.cog = cog
        self.member = member
        options = [
            discord.SelectOption(label=f"Advertencia {level}", value=str(level))
            for level in (1, 2, 3)
        ]
        super().__init__(placeholder="Nivel", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            RemoveWarningModal(self.cog, self.member, int(self.values[0]))
        )


class RemoveLevelView(discord.ui.View):
    def __init__(self, cog: "FarmAdvertenciasCog", member: discord.Member):
        super().__init__(timeout=120)
        self.add_item(RemoveLevelSelect(cog, member))


class RemoveWarningModal(discord.ui.Modal, title="Remover advertencia"):
    motivo = discord.ui.TextInput(
        label="Motivo da remocao",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
    )

    def __init__(self, cog: "FarmAdvertenciasCog", member: discord.Member, nivel: int):
        super().__init__()
        self.cog = cog
        self.member = member
        self.nivel = nivel

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.remover_advertencia(
            interaction,
            self.member,
            self.nivel,
            self.motivo.value.strip(),
        )


class FarmAdvertenciasCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._panel_reconciled = False
        bot.add_view(FarmAdvertenciasPanelView())

    async def upsert_panel(self, channel: discord.TextChannel) -> discord.Message:
        guild_id = str(channel.guild.id)
        await _ensure_channel_name(channel, PANEL_CHANNEL_NAME)
        stored_channel_id, stored_message_id = db_get_farm_adv_panel(guild_id)
        message = None
        if stored_channel_id == str(channel.id) and stored_message_id:
            try:
                message = await channel.fetch_message(int(stored_message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                message = None

        if message is None:
            try:
                async for candidate in channel.history(limit=50):
                    if candidate.author.id != self.bot.user.id:
                        continue
                    if not candidate.embeds:
                        continue
                    title = (candidate.embeds[0].title or "").casefold()
                    if title in {PANEL_TITLE.casefold(), *LEGACY_PANEL_TITLES}:
                        message = candidate
                        break
            except (discord.Forbidden, discord.HTTPException):
                message = None

        embed = build_panel_embed(channel.guild, guild_id)
        logo_file = panel_logo_file()
        if message is None:
            if logo_file is not None:
                message = await channel.send(
                    embed=embed,
                    view=FarmAdvertenciasPanelView(),
                    file=logo_file,
                )
            else:
                message = await channel.send(embed=embed, view=FarmAdvertenciasPanelView())
        else:
            if logo_file is not None:
                await message.edit(
                    content=None,
                    embed=embed,
                    view=FarmAdvertenciasPanelView(),
                    attachments=[logo_file],
                )
            else:
                await message.edit(content=None, embed=embed, view=FarmAdvertenciasPanelView())
        db_set_farm_adv_panel(guild_id, str(channel.id), str(message.id))
        return message

    @commands.Cog.listener()
    async def on_ready(self):
        if self._panel_reconciled:
            return
        self._panel_reconciled = True
        for guild in self.bot.guilds:
            row = db_get_system_config(str(guild.id), SYSTEM_KEY)
            if not row or not row["canal_interacao_id"]:
                continue
            channel = await _fetch_text_channel(guild, row["canal_interacao_id"])
            if channel is None:
                continue
            try:
                role_ids = await ensure_farm_warning_roles(guild)
                db_set_farm_adv_role_ids(
                    str(guild.id),
                    role_ids[1],
                    role_ids[2],
                    role_ids[3],
                )
                await self.upsert_panel(channel)
                log_channel = await _fetch_text_channel(guild, row["canal_log_id"])
                if log_channel is not None:
                    await _ensure_channel_name(log_channel, LOG_CHANNEL_NAME)
                log.info("Painel de advertencias atualizado na guild %s", guild.id)
            except Exception:
                log.exception("Falha ao atualizar painel de advertencias na guild %s", guild.id)

    async def _is_lideranca(self, interaction: discord.Interaction) -> bool:
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "Configure primeiro o sistema de Farm.",
                ephemeral=True,
            )
            return False
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message(
                "Apenas lideranca pode usar este painel.",
                ephemeral=True,
            )
            return False
        return True

    @app_commands.command(
        name="setup_farm_advertencias",
        description="Configura canais e cria cargos oficiais de advertencia do Farm.",
    )
    @app_commands.describe(
        canal_painel="Canal onde o painel da lideranca sera postado",
        canal_log="Canal de logs das advertencias",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_farm_advertencias(
        self,
        interaction: discord.Interaction,
        canal_painel: discord.TextChannel,
        canal_log: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        role_ids = await ensure_farm_warning_roles(interaction.guild)
        db_set_farm_adv_role_ids(
            guild_id,
            role_ids[1],
            role_ids[2],
            role_ids[3],
        )
        db_set_system_config(guild_id, SYSTEM_KEY, str(canal_painel.id), str(canal_log.id))
        await _ensure_channel_name(canal_log, LOG_CHANNEL_NAME)
        message = await self.upsert_panel(canal_painel)
        await interaction.followup.send(
            "Sistema de advertencias do Farm configurado com cargos oficiais "
            f"e painel atualizado em {message.channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setup_farm_advertencias_painel",
        description="Posta o painel de advertencias de Farm para a lideranca.",
    )
    @app_commands.describe(canal="Canal para postar o painel; vazio usa o canal configurado.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_farm_advertencias_painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        row = db_get_system_config(guild_id, SYSTEM_KEY)
        target = canal
        if target is None and row and row["canal_interacao_id"]:
            target = await _fetch_text_channel(interaction.guild, row["canal_interacao_id"])
        if target is None:
            await interaction.followup.send(
                "Canal de painel nao configurado.",
                ephemeral=True,
            )
            return
        role_ids = await ensure_farm_warning_roles(interaction.guild)
        db_set_farm_adv_role_ids(
            guild_id,
            role_ids[1],
            role_ids[2],
            role_ids[3],
        )
        message = await self.upsert_panel(target)
        await interaction.followup.send(
            f"Painel atualizado em {message.channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="farm_ausencia",
        description="Registra uma ausencia valida para a semana ativa de farm.",
    )
    @app_commands.describe(motivo="Motivo da ausencia")
    async def farm_ausencia(self, interaction: discord.Interaction, motivo: str):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "O sistema de Farm nao esta configurado.",
                ephemeral=True,
            )
            return
        if not is_farm_warning_eligible(interaction.user, db_get_permitidos_role_ids(guild_id)):
            await interaction.response.send_message(
                "Voce nao participa do controle de farm.",
                ephemeral=True,
            )
            return
        week_id = current_week_id()
        motivo = motivo.strip() or "Nao informado"
        created, row = db_farm_ausencia_registrar(
            guild_id,
            week_id,
            str(interaction.user.id),
            motivo[:300],
        )
        if not created:
            await interaction.response.send_message(
                f"Voce ja registrou ausencia nesta semana: `{format_week_range_br(week_id)}`.",
                ephemeral=True,
            )
            return

        cfg = db_get_guild_config(guild_id)
        channel = await _fetch_text_channel(
            interaction.guild,
            cfg["canal_ausencias_id"] if cfg and cfg["canal_ausencias_id"] else None,
        )
        embed = build_absence_embed(interaction.user, week_id, motivo)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                log.exception("Falha ao enviar ausencia de farm no canal configurado")
        await send_log(self.bot, interaction.guild, SYSTEM_KEY, embed)
        await interaction.response.send_message(
            "Ausencia registrada para a semana ativa.",
            ephemeral=True,
        )

    async def gerar_previa(self, interaction: discord.Interaction):
        if not await self._is_lideranca(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        try:
            snapshot = build_farm_warning_preview(interaction.guild, guild_id, week_id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        fechamento = db_farm_adv_fechamento_criar(
            guild_id,
            week_id,
            snapshot,
            str(interaction.user.id),
        )
        await interaction.followup.send(
            embed=build_preview_embed(snapshot),
            view=ApplyPreviewView(int(fechamento["id"]), interaction.user.id),
            ephemeral=True,
        )

    async def listar_ausencias(self, interaction: discord.Interaction):
        if not await self._is_lideranca(interaction):
            return
        week_id = current_week_id()
        rows = db_farm_ausencias_semana(str(interaction.guild_id), week_id)
        embed = discord.Embed(
            title="Ausencias da semana",
            description=f"Semana: `{format_week_range_br(week_id)}`",
            color=COR_INFO,
        )
        lines = [f"- <@{row['user_id']}>: {row['motivo']}" for row in rows]
        for index, chunk in enumerate(_chunk(lines)):
            embed.add_field(
                name="Registros" if index == 0 else "Registros (cont.)",
                value=chunk,
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def abrir_consulta(self, interaction: discord.Interaction):
        if not await self._is_lideranca(interaction):
            return
        await interaction.response.send_message(
            "Selecione o membro para consultar.",
            view=ConsultMemberView(self),
            ephemeral=True,
        )

    async def abrir_individual(self, interaction: discord.Interaction):
        if not await self._is_lideranca(interaction):
            return
        await interaction.response.send_message(
            "Selecione o membro zerado que deve receber advertencia.",
            view=IndividualWarningView(self),
            ephemeral=True,
        )

    async def aplicar_individual(self, interaction: discord.Interaction, member: discord.Member):
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        if not is_farm_warning_eligible(member, db_get_permitidos_role_ids(guild_id)):
            await interaction.response.send_message(
                "Esse membro nao esta abaixo do cargo 02 nem nos cargos configurados de farm.",
                ephemeral=True,
            )
            return
        if str(member.id) in db_farm_ausencia_user_ids(guild_id, week_id):
            await interaction.response.send_message(
                "Esse membro possui ausencia valida nesta semana.",
                ephemeral=True,
            )
            return
        ranking = db_ranking_semana(guild_id, week_id, [str(member.id)])
        row = next((item for item in ranking if str(item["user_id"]) == str(member.id)), {})
        classificacao = row.get("classificacao", "zero")
        if classificacao in {"elite", "meta_batida"}:
            await interaction.response.send_message(
                "Esse membro ja entregou o farm completo nesta semana.",
                ephemeral=True,
            )
            return
        if classificacao == "parcial":
            await interaction.response.send_message(
                "Esse membro esta parcial. Parcial gera cobranca manual, nao advertencia.",
                ephemeral=True,
            )
            return
        role_ids = db_get_farm_adv_role_ids(guild_id)
        if not _role_config_complete(role_ids):
            await interaction.response.send_message(
                "Configure os tres cargos de advertencia antes de aplicar.",
                ephemeral=True,
            )
            return
        item = {
            "user_id": str(member.id),
            "display_name": member.display_name,
            "nivel": next_warning_level_from_history(guild_id, str(member.id)),
        }
        snapshot = {"guild_id": guild_id, "week_id": week_id, "role_ids": role_ids}
        await interaction.response.defer(ephemeral=True)
        result = await self._apply_warning_item(interaction, snapshot, item, role_ids)
        await self._send_apply_summary(interaction, snapshot, [result])

    async def enviar_consulta(self, interaction: discord.Interaction, member: discord.Member):
        guild_id = str(interaction.guild_id)
        rows = db_farm_advertencias_usuario(guild_id, str(member.id))
        role_ids = db_get_farm_adv_role_ids(guild_id)
        current_roles = [
            f"Advertencia {level}"
            for level, role_id in role_ids.items()
            if member.get_role(int(role_id)) is not None
        ]
        embed = discord.Embed(
            title=f"Advertencias - {member.display_name}",
            color=COR_INFO,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Cargos atuais",
            value=", ".join(current_roles) if current_roles else "Nenhum",
            inline=False,
        )
        if rows:
            lines = [
                f"- Semana `{row['week_id']}`: Adv {row['nivel']} ({row['status']})"
                for row in rows[:15]
            ]
            embed.add_field(name="Historico", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Historico", value="Nenhum registro.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def abrir_remocao(self, interaction: discord.Interaction):
        if not await self._is_lideranca(interaction):
            return
        await interaction.response.send_message(
            "Selecione o membro.",
            view=RemoveMemberView(self),
            ephemeral=True,
        )

    async def remover_advertencia(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        nivel: int,
        motivo: str,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        role_id = db_get_farm_adv_role_ids(guild_id).get(nivel)
        role = interaction.guild.get_role(int(role_id)) if role_id else None
        removed_role = False
        if role and role in member.roles:
            try:
                await member.remove_roles(
                    role,
                    reason=f"Advertencia removida por {interaction.user} - {motivo}",
                )
                removed_role = True
            except discord.HTTPException:
                log.exception("Falha ao remover cargo de advertencia")
                await interaction.followup.send(
                    "O Discord não permitiu remover o cargo. O registro foi mantido "
                    "para evitar inconsistência; confira a hierarquia do cargo do bot.",
                    ephemeral=True,
                )
                return
        row = db_farm_advertencia_remover(
            guild_id,
            str(member.id),
            nivel,
            str(interaction.user.id),
            motivo,
        )
        embed = discord.Embed(
            title="Advertencia removida",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Membro", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Nivel", value=str(nivel), inline=True)
        embed.add_field(name="Cargo removido", value="Sim" if removed_role else "Nao", inline=True)
        embed.add_field(name="Registro no banco", value="Atualizado" if row else "Nao encontrado", inline=True)
        embed.add_field(name="Motivo", value=motivo[:1000], inline=False)
        await send_log(self.bot, interaction.guild, SYSTEM_KEY, embed)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def aplicar_fechamento(self, interaction: discord.Interaction, fechamento_id: int):
        if not await self._is_lideranca(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not db_farm_adv_fechamento_claim(fechamento_id, str(interaction.user.id)):
            await interaction.followup.send(
                "Esta previa ja foi aplicada ou esta em processamento.",
                ephemeral=True,
            )
            return

        snapshot: dict = {}
        try:
            fechamento = db_farm_adv_fechamento_get(fechamento_id)
            if fechamento is None:
                raise LookupError(f"Fechamento {fechamento_id} nao encontrado")
            snapshot = json.loads(fechamento["snapshot_json"])
            results = []
            role_ids = {
                int(level): role_id
                for level, role_id in snapshot["role_ids"].items()
            }

            partials = snapshot.get("parciais", [])
            if partials:
                partial_embed = discord.Embed(
                    title="Farm incompleto - aviso para lideranca",
                    description=f"Semana: `{format_week_range_br(snapshot['week_id'])}`",
                    color=COR_INFO,
                    timestamp=discord.utils.utcnow(),
                )
                lines = [
                    f"`{_display(item)}` - {item.get('pct', 0)}%"
                    for item in partials
                ]
                for index, chunk in enumerate(_chunk(lines)):
                    partial_embed.add_field(
                        name="Parciais" if index == 0 else "Parciais (cont.)",
                        value=chunk,
                        inline=False,
                    )
                await send_log(self.bot, interaction.guild, SYSTEM_KEY, partial_embed)

            for item in snapshot.get("pendentes", []):
                results.append(
                    await self._apply_warning_item(
                        interaction,
                        snapshot,
                        item,
                        role_ids,
                    )
                )

            snapshot["resultados"] = results
            db_farm_adv_fechamento_finalizar(fechamento_id, snapshot)
            await self._send_apply_summary(interaction, snapshot, results)
        except Exception as exc:
            log.exception("Falha ao aplicar fechamento de farm %s", fechamento_id)
            snapshot["erro_aplicacao"] = type(exc).__name__
            try:
                db_farm_adv_fechamento_finalizar(
                    fechamento_id,
                    snapshot,
                    status="erro",
                )
            except Exception:
                log.exception(
                    "Falha ao registrar erro do fechamento de farm %s",
                    fechamento_id,
                )
            await interaction.followup.send(
                "Não foi possível concluir a aplicação. A prévia foi liberada para "
                "uma nova tentativa e nenhuma falha ficará presa em processamento.",
                ephemeral=True,
            )

    async def _apply_warning_item(
        self,
        interaction: discord.Interaction,
        snapshot: dict,
        item: dict,
        role_ids: dict[int, str] | dict[str, str],
    ) -> dict:
        user_id = str(item["user_id"])
        nivel = item.get("nivel")
        result = {
            "user_id": user_id,
            "display_name": item.get("display_name"),
            "nivel": nivel,
        }
        if nivel is None:
            return {**result, "status": "ja_pd"}
        member = interaction.guild.get_member(int(user_id))
        if member is None:
            return {**result, "status": "membro_nao_encontrado"}
        role_id = role_ids.get(int(nivel)) or role_ids.get(str(nivel))
        role = interaction.guild.get_role(int(role_id)) if role_id else None
        if role is None:
            return {**result, "status": "cargo_inexistente"}
        bot_member = interaction.guild.me
        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or bot_member.top_role <= role
        ):
            return {**result, "status": "sem_permissao"}

        punicao = PUNICOES[int(nivel)]
        created, adv_row = db_farm_advertencia_criar(
            snapshot["guild_id"],
            snapshot["week_id"],
            user_id,
            int(nivel),
            MOTIVO_FALTA,
            punicao["multa"],
            punicao["dias"],
            str(interaction.user.id),
        )
        if not created:
            return {**result, "status": "duplicada"}
        try:
            if role not in member.roles:
                await member.add_roles(
                    role,
                    reason=f"Advertencia de farm aplicada por {interaction.user}",
                )
            await send_log(self.bot, interaction.guild, SYSTEM_KEY, build_warning_embed(member, int(nivel)))
            return {**result, "status": "aplicada", "id": int(adv_row["id"]) if adv_row else None}
        except discord.HTTPException:
            if adv_row:
                db_farm_advertencia_status(int(adv_row["id"]), "erro")
            return {**result, "status": "erro_discord"}

    async def _send_apply_summary(
        self,
        interaction: discord.Interaction,
        snapshot: dict,
        results: list[dict],
    ) -> None:
        lines = []
        for result in results:
            nivel = result.get("nivel")
            suffix = f" Adv {nivel}" if nivel else ""
            display = result.get("display_name") or f"ID {result['user_id']}"
            lines.append(f"`{display}`: {result['status']}{suffix}")
        embed = discord.Embed(
            title="Resultado da aplicacao de advertencias",
            description=f"Semana: `{format_week_range_br(snapshot['week_id'])}`",
            color=COR_ADV,
            timestamp=discord.utils.utcnow(),
        )
        for index, chunk in enumerate(_chunk(lines)):
            embed.add_field(
                name="Resultados" if index == 0 else "Resultados (cont.)",
                value=chunk,
                inline=False,
            )
        embed.add_field(name="Confirmado por", value=interaction.user.mention, inline=True)
        await send_log(self.bot, interaction.guild, SYSTEM_KEY, embed)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_farm_advertencias.error
    @setup_farm_advertencias_painel.error
    async def setup_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "Voce precisa da permissao Gerenciar Servidor."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        original = getattr(error, "original", error)
        if isinstance(original, PermissionError):
            msg = str(original)
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        log.error("Erro no setup de farm advertencias: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("Erro inesperado.", ephemeral=True)
        else:
            await interaction.followup.send("Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmAdvertenciasCog(bot))
    log.info("FarmAdvertenciasCog carregado.")
