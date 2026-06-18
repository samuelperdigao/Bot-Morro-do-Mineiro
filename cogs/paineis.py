"""
Listeners e handlers dos painéis de operações e set.
Responde a cliques de botões e abre os modals/embeds correspondentes.
"""

from datetime import date, timedelta

import discord
from discord.ext import commands
from core.date_utils import (
    format_date_br,
    format_week_range_br,
    week_id_from_date_br,
)
from core.farm_policy import FARM_TICKET_ONLY_MESSAGE
from core.permissions import is_lideranca, is_permitido_farm
from services.db_service import (
    db_get_lideranca_role_ids,
    db_get_permitidos_role_ids,
    db_get_progresso,
    db_get_meta,
    db_get_ultimo_evento,
    db_evento_itens,
    current_week_id,
    db_ranking_semana,
)
from services.paineis_service import PainelOperacoesView, PainelSetView
import logging

log = logging.getLogger("paineis")

RANKING_WEEKS_PER_PAGE = 20


class LegacyPainelFarmView(discord.ui.View):
    """Mantém os botões de mensagens antigas respondendo com a nova orientação."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _disabled(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)

    @discord.ui.button(label="Farm antigo desativado", custom_id="painel:lancar_farm")
    async def lancar_farm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disabled(interaction)

    @discord.ui.button(label="Farm antigo desativado", custom_id="painel:lancar_dinheiro")
    async def lancar_dinheiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disabled(interaction)


def _ranking_week_id_by_offset(offset: int) -> str:
    current_start = date.fromisoformat(current_week_id())
    return (current_start - timedelta(weeks=max(offset, 0))).isoformat()


def _build_ranking_history_embed(
    guild: discord.Guild,
    guild_id: str,
    week_id: str,
) -> discord.Embed:
    from cogs.farm import build_ranking_embed

    participantes = db_ranking_semana(guild_id, week_id)
    embed = build_ranking_embed(guild_id, week_id, participantes, guild)
    embed.description = embed.description.replace(
        format_date_br(week_id),
        format_week_range_br(week_id),
        1,
    )
    embed.set_footer(text="Use o seletor abaixo para consultar outra semana")
    return embed


class RankingWeekSelect(discord.ui.Select):
    def __init__(self, ranking_view: "RankingHistoryView"):
        self.ranking_view = ranking_view
        first_offset = ranking_view.page * RANKING_WEEKS_PER_PAGE
        current_id = current_week_id()
        options = []

        for index in range(RANKING_WEEKS_PER_PAGE):
            week_id = _ranking_week_id_by_offset(first_offset + index)
            label = format_week_range_br(week_id)
            if week_id == current_id:
                label = f"Semana atual | {label}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=week_id,
                    description="Consultar ranking e lançamentos desta semana",
                    default=week_id == ranking_view.week_id,
                )
            )

        super().__init__(
            placeholder="Escolha uma semana para consultar",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.ranking_view.show_week(interaction, self.values[0])


class RankingDateModal(discord.ui.Modal, title="Consultar Semana do Ranking"):
    data = discord.ui.TextInput(
        label="Data da semana",
        placeholder="Ex: 15/01/2026",
        min_length=10,
        max_length=10,
    )

    def __init__(self, ranking_view: "RankingHistoryView"):
        super().__init__()
        self.ranking_view = ranking_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            week_id = week_id_from_date_br(self.data.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        current_id = current_week_id()
        if week_id > current_id:
            await interaction.response.send_message(
                "❌ Não é possível consultar uma semana futura.",
                ephemeral=True,
            )
            return

        current_start = date.fromisoformat(current_id)
        selected_start = date.fromisoformat(week_id)
        offset = (current_start - selected_start).days // 7
        self.ranking_view.page = offset // RANKING_WEEKS_PER_PAGE
        self.ranking_view.week_id = week_id
        self.ranking_view.rebuild()

        embed = _build_ranking_history_embed(
            self.ranking_view.guild,
            self.ranking_view.guild_id,
            week_id,
        )
        await interaction.response.edit_message(embed=embed, view=self.ranking_view)


class RankingHistoryView(discord.ui.View):
    def __init__(
        self,
        guild: discord.Guild,
        guild_id: str,
        *,
        week_id: str | None = None,
        page: int = 0,
    ):
        super().__init__(timeout=300)
        self.guild = guild
        self.guild_id = guild_id
        self.week_id = week_id or current_week_id()
        self.page = max(page, 0)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        self.add_item(RankingWeekSelect(self))

        older = discord.ui.Button(
            label="Semanas mais antigas",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        older.callback = self.show_older_weeks
        self.add_item(older)

        newer = discord.ui.Button(
            label="Semanas mais recentes",
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
            row=1,
        )
        newer.callback = self.show_newer_weeks
        self.add_item(newer)

        choose_date = discord.ui.Button(
            label="Informar data",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        choose_date.callback = self.open_date_modal
        self.add_item(choose_date)

    async def show_week(self, interaction: discord.Interaction, week_id: str):
        self.week_id = week_id
        self.rebuild()
        embed = _build_ranking_history_embed(self.guild, self.guild_id, week_id)
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_older_weeks(self, interaction: discord.Interaction):
        self.page += 1
        await self.show_week(
            interaction,
            _ranking_week_id_by_offset(self.page * RANKING_WEEKS_PER_PAGE),
        )

    async def show_newer_weeks(self, interaction: discord.Interaction):
        self.page = max(self.page - 1, 0)
        await self.show_week(
            interaction,
            _ranking_week_id_by_offset(self.page * RANKING_WEEKS_PER_PAGE),
        )

    async def open_date_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RankingDateModal(self))


class PaineisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Registra views persistentes para sobreviver a reinicializações do bot
        bot.add_view(PainelOperacoesView())
        bot.add_view(PainelSetView())
        bot.add_view(LegacyPainelFarmView())

    # ══════════════════════════════════════════════════════════════════════════
    # HANDLER: PAINEL DE OPERAÇÕES
    # ══════════════════════════════════════════════════════════════════════════

    async def _handle_painel_operacoes(self, interaction: discord.Interaction, custom_id: str):
        funcao    = custom_id.removeprefix("painel:")
        member    = interaction.user
        guild_id  = str(interaction.guild_id)

        lideranca_ids  = db_get_lideranca_role_ids(guild_id)
        permitidos_ids = db_get_permitidos_role_ids(guild_id)

        try:
            # ── Lançar Farm ───────────────────────────────────────────────────
            if funcao == "lancar_farm":
                await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)

            elif funcao == "lancar_dinheiro":
                await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)

            # ── Ver Meu Farm ──────────────────────────────────────────────────
            elif funcao == "ver_meu_farm":
                if not is_permitido_farm(member, permitidos_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para ver farm.", ephemeral=True
                    )
                    return
                from cogs.farm import build_farm_embed
                week_id = current_week_id()
                prog    = db_get_progresso(guild_id, week_id, str(member.id))
                meta    = db_get_meta(guild_id, week_id)
                if not prog and not meta:
                    await interaction.response.send_message(
                        "⚠️ Nenhum farm registrado esta semana.", ephemeral=True
                    )
                    return
                embed = build_farm_embed(meta, prog, member, week_id)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                log.info("ver_meu_farm: %s (%s)", member.name, guild_id)

            # ── Editar Farm ───────────────────────────────────────────────────
            elif funcao == "editar_farm":
                if not is_lideranca(member, lideranca_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para editar farms.", ephemeral=True
                    )
                    return
                week_id = current_week_id()
                ultimo  = db_get_ultimo_evento(guild_id, week_id, str(member.id))
                if not ultimo:
                    await interaction.response.send_message(
                        "❌ Nenhum lançamento encontrado para editar.", ephemeral=True
                    )
                    return
                farm_cog = interaction.client.get_cog("FarmCog")
                if not farm_cog:
                    await interaction.response.send_message(
                        "❌ Erro interno: FarmCog não carregado.", ephemeral=True
                    )
                    return
                from cogs.farm import EditarUltimoModal
                await interaction.response.send_modal(
                    EditarUltimoModal(farm_cog, week_id, guild_id, str(member.id), db_evento_itens(ultimo))
                )
                log.info("editar_farm: %s (%s)", member.name, guild_id)

            # ── Definir Metas ─────────────────────────────────────────────────
            elif funcao == "definir_metas":
                if not is_lideranca(member, lideranca_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para definir metas.", ephemeral=True
                    )
                    return
                week_id  = current_week_id()
                farm_cog = interaction.client.get_cog("FarmCog")
                if not farm_cog:
                    await interaction.response.send_message(
                        "❌ Erro interno: FarmCog não carregado.", ephemeral=True
                    )
                    return
                from cogs.farm import EscolherTipoMetaView
                await interaction.response.send_message(
                    "Escolha o tipo de meta para esta semana:",
                    view=EscolherTipoMetaView(farm_cog, week_id, guild_id),
                    ephemeral=True,
                )
                log.info("definir_metas: %s (%s)", member.name, guild_id)

            # ── Fazer Anúncio ─────────────────────────────────────────────────
            elif funcao == "fazer_anuncio":
                from cogs.anuncio import db_get_anuncio_cargo_ids, db_get_anuncio_canal, pode_anunciar, AnuncioModal
                cargo_ids = db_get_anuncio_cargo_ids(guild_id)
                if not pode_anunciar(member, cargo_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para fazer anúncios.", ephemeral=True
                    )
                    return
                canal_id = db_get_anuncio_canal(guild_id)
                canal    = interaction.guild.get_channel(canal_id) if canal_id else None
                if not canal:
                    await interaction.response.send_message(
                        "❌ Canal de anúncios não configurado. Use `/setup_anuncio`.", ephemeral=True
                    )
                    return
                await interaction.response.send_modal(AnuncioModal(canal_anuncio=canal))
                log.info("fazer_anuncio: %s (%s)", member.name, guild_id)

            # ── Ranking ───────────────────────────────────────────────────────
            elif funcao == "recolhimento":
                if not is_lideranca(member, lideranca_ids):
                    await interaction.response.send_message(
                        "Voce nao tem permissao para iniciar recolhimento.", ephemeral=True
                    )
                    return
                recolhimento_cog = interaction.client.get_cog("RecolhimentoCog")
                if not recolhimento_cog:
                    await interaction.response.send_message(
                        "Erro interno: RecolhimentoCog nao carregado.", ephemeral=True
                    )
                    return
                from cogs.recolhimento import EscolherTipoView
                await interaction.response.send_message(
                    "Escolha o tipo de recolhimento para esta semana:",
                    view=EscolherTipoView(recolhimento_cog),
                    ephemeral=True,
                )
                log.info("recolhimento: %s (%s)", member.name, guild_id)

            elif funcao == "ranking":
                week_id = current_week_id()
                embed = _build_ranking_history_embed(interaction.guild, guild_id, week_id)
                view = RankingHistoryView(interaction.guild, guild_id, week_id=week_id)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                log.info("ranking: %s (%s)", member.name, guild_id)

            else:
                await interaction.response.send_message(
                    f"❓ Função desconhecida: `{funcao}`", ephemeral=True
                )

        except Exception as e:
            log.error("Erro em painel_operacoes/%s: %s", custom_id, e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Erro interno. Tente novamente.", ephemeral=True
                )

    # ══════════════════════════════════════════════════════════════════════════
    # HANDLER: PAINEL DE SET
    # ══════════════════════════════════════════════════════════════════════════

    async def _handle_painel_set(self, interaction: discord.Interaction, custom_id: str):
        funcao = custom_id.removeprefix("painel_set:")
        try:
            if funcao == "pedir":
                from cogs.set_views import SetModal
                await interaction.response.send_modal(SetModal())
                log.info("set_solicitado: %s (%s)", interaction.user.name, interaction.guild_id)
            else:
                await interaction.response.send_message(
                    f"❓ Função desconhecida: `{funcao}`", ephemeral=True
                )
        except Exception as e:
            log.error("Erro em painel_set/%s: %s", custom_id, e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Erro interno. Tente novamente.", ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(PaineisCog(bot))
