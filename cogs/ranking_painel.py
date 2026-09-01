"""
cogs/ranking_painel.py - Painel fixo publico do ranking semanal de farm.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import format_date_br
from core.logger import get_logger
from core.permissions import is_permitido_farm
from services.db_service import (
    current_week_id,
    db_get_meta,
    db_get_painel_ranking,
    db_get_permitidos_role_ids,
    db_is_farm_configured,
    db_meta_tipo_efetivo,
    db_ranking_semana,
    db_set_painel_ranking,
)

log = get_logger("ranking", "ranking.log")

RANKING_CATEGORY_NAME = "Ranking"
RANKING_CATEGORY_ID = 1504287738298372216
RANKING_CHANNEL_NAME = "ranking-farm"
RANKING_FIELD_LIMIT = 900
RANKING_MAX_FIELDS = 6


def _status_visual(classificacao: str) -> tuple[str, str]:
    return {
        "elite": ("🔥", "Elite"),
        "meta_batida": ("✅", "Meta Batida"),
        "parcial": ("⚠️", "Parcial"),
        "zero": ("❌", "Zero"),
    }.get(classificacao, ("❌", "Zero"))


def _safe_name(member: discord.Member | None, fallback: str, limit: int = 28) -> str:
    name = member.display_name if member else fallback
    return name if len(name) <= limit else f"{name[: limit - 1]}…"


def _split_ranking_fields(lines: list[str]) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        add_len = len(line) + 1
        if current and current_len + add_len > RANKING_FIELD_LIMIT:
            fields.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += add_len

    if current:
        fields.append("\n".join(current))
    return fields


def _fmt_total(meta, total: float) -> str:
    if db_meta_tipo_efetivo(meta) == "dinheiro":
        return f"R$ {total:,.0f}".replace(",", ".")
    return f"{int(total)} itens"


def _membros_elegiveis(guild: discord.Guild, guild_id: str) -> list[discord.Member]:
    permitidos_ids = db_get_permitidos_role_ids(guild_id)
    membros = [
        member
        for member in guild.members
        if not member.bot and is_permitido_farm(member, permitidos_ids)
    ]
    return sorted(membros, key=lambda m: m.display_name.casefold())


def build_ranking_publico_embeds(guild: discord.Guild, guild_id: str, week_id: str) -> list[discord.Embed]:
    meta = db_get_meta(guild_id, week_id)
    membros = _membros_elegiveis(guild, guild_id)
    participantes = db_ranking_semana(guild_id, week_id, [str(m.id) for m in membros])
    membros_por_id = {str(m.id): m for m in membros}

    if not meta:
        embed = discord.Embed(
            title="🏆 Ranking Semanal de Farm",
            description=(
                f"**Semana:** `{format_date_br(week_id)}`\n\n"
                "⚠️ As metas ainda não foram definidas para esta semana."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Atualiza automaticamente após cada lançamento")
        return [embed]

    tipo = db_meta_tipo_efetivo(meta)
    if tipo == "misto":
        tipo_meta = "📦 Produtos + 💵 Dinheiro"
    elif tipo == "dinheiro":
        tipo_meta = "💵 Dinheiro"
    elif tipo == "colete":
        tipo_meta = "🦺 Materiais de Colete"
    else:
        tipo_meta = "📦 Itens de produção"
    total_membros = len(membros)
    com_entrega = sum(1 for row in participantes if row.get("total", 0) > 0)
    zerados = max(total_membros - com_entrega, 0)
    concluidos = sum(
        1
        for row in participantes
        if row.get("classificacao") in {"elite", "meta_batida"}
    )

    medalhas = ["🥇", "🥈", "🥉"]
    ranking_lines = []
    for idx, row in enumerate(participantes, start=1):
        member = membros_por_id.get(str(row["user_id"]))
        nome = _safe_name(member, f"ID {row['user_id']}", limit=24)
        pos = medalhas[idx - 1] if idx <= 3 else f"`#{idx:02}`"
        emoji, label = _status_visual(row.get("classificacao", "zero"))
        total = _fmt_total(meta, row.get("total", 0))
        ranking_lines.append(
            f"{pos} **{nome}** — **{row.get('pct', 0):.0f}%** • {total} • {emoji} {label}"
        )

    if not ranking_lines:
        ranking_lines.append("Nenhum membro elegível encontrado.")

    embed = discord.Embed(
        title="🏆 Ranking Semanal de Farm",
        description=(
            f"**Semana:** `{format_date_br(week_id)}`\n"
            f"**Meta:** {tipo_meta}\n"
            "Painel público atualizado automaticamente após cada lançamento."
        ),
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Resumo",
        value=(
            f"👥 Membros: `{total_membros}`\n"
            f"📤 Com entrega: `{com_entrega}`\n"
            f"🎯 Meta batida: `{concluidos}`\n"
            f"❌ Zerados: `{zerados}`"
        ),
        inline=False,
    )

    podium_rows = [row for row in participantes if row.get("total", 0) > 0][:3]
    if podium_rows:
        podium = []
        for idx, row in enumerate(podium_rows, start=1):
            member = membros_por_id.get(str(row["user_id"]))
            nome = _safe_name(member, f"ID {row['user_id']}", limit=22)
            emoji, label = _status_visual(row.get("classificacao", "zero"))
            podium.append(
                f"{medalhas[idx - 1]} **{nome}** — {row.get('pct', 0):.0f}% • "
                f"{_fmt_total(meta, row.get('total', 0))} • {emoji} {label}"
            )
        podium_text = "\n".join(podium)
    else:
        podium_text = "Aguardando lançamentos."

    embed.add_field(name="Pódio da semana", value=podium_text, inline=False)

    fields = _split_ranking_fields(ranking_lines)
    hidden_count = 0
    if len(fields) > RANKING_MAX_FIELDS:
        shown_fields = fields[:RANKING_MAX_FIELDS]
        shown_lines = sum(field.count("\n") + 1 for field in shown_fields)
        hidden_count = max(len(ranking_lines) - shown_lines, 0)
        fields = shown_fields

    for idx, field in enumerate(fields, start=1):
        title = "Ranking geral" if idx == 1 else f"Ranking geral ({idx})"
        embed.add_field(name=title, value=field, inline=False)

    if hidden_count:
        embed.add_field(
            name="Lista muito grande",
            value=f"`{hidden_count}` membro(s) não couberam no painel por limite do Discord.",
            inline=False,
        )

    embed.set_footer(text="Morro do Mineiro • atualizado automaticamente")
    return [embed]


class RankingPainelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _obter_ou_criar_canal(self, guild: discord.Guild) -> discord.TextChannel:
        category = guild.get_channel(RANKING_CATEGORY_ID)
        if isinstance(category, discord.TextChannel):
            return category
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.get(guild.categories, name=RANKING_CATEGORY_NAME)

        channel = discord.utils.get(
            guild.text_channels,
            name=RANKING_CHANNEL_NAME,
            category=category if isinstance(category, discord.CategoryChannel) else None,
        )
        if channel:
            return channel

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
            )
        if category is None:
            category = await guild.create_category(
                RANKING_CATEGORY_NAME,
                overwrites=overwrites,
                reason="Criacao do painel fixo de ranking de farm",
            )
        return await guild.create_text_channel(
            RANKING_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            reason="Criacao do painel fixo de ranking de farm",
        )

    async def atualizar_ranking_fixo(self, guild_id: str) -> bool:
        channel_id, message_id, _ = db_get_painel_ranking(guild_id)
        if not channel_id or not message_id:
            return False

        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return False

        week_id = current_week_id()
        embeds = build_ranking_publico_embeds(guild, guild_id, week_id)
        try:
            channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
            message = await channel.fetch_message(int(message_id))
            await message.edit(content=None, embeds=embeds)
            db_set_painel_ranking(guild_id, str(channel.id), str(message.id), week_id)
            return True
        except discord.NotFound:
            log.warning("Painel de ranking nao encontrado para guild %s", guild_id)
            return False
        except Exception as e:
            log.error("Erro ao atualizar painel de ranking da guild %s: %s", guild_id, e, exc_info=True)
            return False

    @app_commands.command(
        name="setup_ranking_painel",
        description="Cria ou atualiza o painel fixo publico do ranking semanal de farm.",
    )
    @app_commands.describe(canal="Canal onde o ranking fixo sera postado. Se vazio, cria #ranking-farm.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_ranking_painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "O modulo Farm precisa estar configurado antes de criar o ranking.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        channel = canal or await self._obter_ou_criar_canal(interaction.guild)
        week_id = current_week_id()
        embeds = build_ranking_publico_embeds(interaction.guild, guild_id, week_id)
        message = await channel.send(embeds=embeds)
        db_set_painel_ranking(guild_id, str(channel.id), str(message.id), week_id)
        await interaction.followup.send(
            f"Painel fixo de ranking criado em {channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RankingPainelCog(bot))
    log.info("RankingPainelCog adicionado ao bot.")
