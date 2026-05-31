"""
Listeners e handlers dos painéis de operações e set.
Responde a cliques de botões e abre os modals/embeds correspondentes.
"""

import discord
from discord.ext import commands
from core.permissions import is_lideranca, is_permitido_farm
from services.db_service import (
    db_get_lideranca_role_ids,
    db_get_permitidos_role_ids,
    db_get_progresso,
    db_get_meta,
    db_meta_itens_ativos,
    db_get_ultimo_evento,
    db_evento_itens,
    db_lista_progresso,
    db_get_guild_config,
    current_week_id,
    db_ranking_semana,
)
from services.paineis_service import PainelOperacoesView, PainelSetView
import logging

log = logging.getLogger("paineis")


class AvisoFarmModal(discord.ui.Modal, title="📢 Aviso de Farm"):
    titulo = discord.ui.TextInput(
        label="Título do aviso",
        placeholder="Ex: Lembrete de entrega semanal",
        max_length=256,
    )
    mensagem = discord.ui.TextInput(
        label="Mensagem",
        style=discord.TextStyle.paragraph,
        placeholder="Escreva o aviso aqui...",
        max_length=2000,
    )
    mencionar_todos = discord.ui.TextInput(
        label="Mencionar @everyone? (sim/não)",
        placeholder="sim ou não",
        max_length=3,
        required=False,
    )

    def __init__(self, canal_avisos: discord.TextChannel):
        super().__init__()
        self.canal_avisos = canal_avisos

    async def on_submit(self, interaction: discord.Interaction):
        mencionar = self.mencionar_todos.value.strip().lower() in ("sim", "s", "yes", "y", "1")
        embed = discord.Embed(
            title=f"📢 {self.titulo.value.strip()}",
            description=self.mensagem.value.strip(),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Aviso enviado por {interaction.user.display_name}")
        content = "@everyone" if mencionar else None
        await self.canal_avisos.send(content=content, embed=embed)
        await interaction.response.send_message("✅ Aviso enviado com sucesso!", ephemeral=True)
        log.info("aviso_farm enviado por %s para canal %s (everyone=%s)", interaction.user.name, self.canal_avisos.id, mencionar)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no AvisoFarmModal: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro ao enviar aviso.", ephemeral=True)


class PaineisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Registra views persistentes para sobreviver a reinicializações do bot
        bot.add_view(PainelOperacoesView())
        bot.add_view(PainelSetView())

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
                permissao = is_permitido_farm(member, permitidos_ids)
                if not permissao:
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para lançar farm.", ephemeral=True
                    )
                    return

                week_id = current_week_id()
                meta    = db_get_meta(guild_id, week_id)
                itens   = db_meta_itens_ativos(meta)

                if not itens or not any((qtd or 0) > 0 for qtd in itens.values()):
                    await interaction.response.send_message(
                        "❌ A meta Kit Desmanche ainda não foi definida. Use `/meta` para defini-la.",
                        ephemeral=True,
                    )
                    return

                farm_cog = interaction.client.get_cog("FarmCog")
                if not farm_cog:
                    await interaction.response.send_message(
                        "❌ Erro interno: FarmCog não carregado.", ephemeral=True
                    )
                    return

                from cogs.farm import LancarModal
                await interaction.response.send_modal(
                    LancarModal(farm_cog, week_id, guild_id, str(member.id), itens)
                )
                log.info("lancar_farm: %s (%s)", member.name, guild_id)

            elif funcao == "lancar_dinheiro":
                if not is_permitido_farm(member, permitidos_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para lançar dinheiro.", ephemeral=True
                    )
                    return

                week_id = current_week_id()
                meta = db_get_meta(guild_id, week_id)
                if not meta or (meta["meta_dinheiro"] or 0) <= 0:
                    await interaction.response.send_message(
                        "❌ A meta de dinheiro ainda não foi definida. Use `/meta` para defini-la.",
                        ephemeral=True,
                    )
                    return

                farm_cog = interaction.client.get_cog("FarmCog")
                if not farm_cog:
                    await interaction.response.send_message(
                        "❌ Erro interno: FarmCog não carregado.", ephemeral=True
                    )
                    return

                from cogs.farm import LancarDinheiroModal
                await interaction.response.send_modal(
                    LancarDinheiroModal(farm_cog, week_id, guild_id, str(member.id))
                )
                log.info("lancar_dinheiro: %s (%s)", member.name, guild_id)

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

            # ── Aprovar Farm ──────────────────────────────────────────────────
            elif funcao == "aprovar_farm":
                if not is_lideranca(member, lideranca_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para aprovar farms.", ephemeral=True
                    )
                    return
                week_id       = current_week_id()
                participantes = db_lista_progresso(guild_id, week_id)
                if not participantes:
                    await interaction.response.send_message(
                        "⚠️ Nenhum farm registrado esta semana.", ephemeral=True
                    )
                    return
                farm_cog = interaction.client.get_cog("FarmCog")
                if not farm_cog:
                    await interaction.response.send_message(
                        "❌ Erro interno: FarmCog não carregado.", ephemeral=True
                    )
                    return
                from cogs.farm import ResultadoView
                embed = discord.Embed(
                    title="📊 Aprovar Farm — Semana Atual",
                    description=f"📅 Semana: `{week_id}` — {len(participantes)} participante(s)\nSelecione um membro para ver detalhes e aprovar.",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )
                view = ResultadoView(farm_cog, guild_id, week_id, participantes, interaction.guild)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                log.info("aprovar_farm: %s (%s)", member.name, guild_id)

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

            # ── Avisos Farm ───────────────────────────────────────────────────
            elif funcao == "avisos_farm":
                if not is_lideranca(member, lideranca_ids):
                    await interaction.response.send_message(
                        "❌ Você não tem permissão para enviar avisos.", ephemeral=True
                    )
                    return
                cfg = db_get_guild_config(guild_id)
                canal_avisos_id = int(cfg["canal_avisos_farm"]) if cfg and cfg["canal_avisos_farm"] else None
                canal_avisos = interaction.guild.get_channel(canal_avisos_id) if canal_avisos_id else None
                if not canal_avisos:
                    await interaction.response.send_message(
                        "❌ Canal de avisos de farm não configurado. Use `/setup_farm`.", ephemeral=True
                    )
                    return
                await interaction.response.send_modal(AvisoFarmModal(canal_avisos=canal_avisos))
                log.info("avisos_farm: %s (%s)", member.name, guild_id)

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
                from cogs.farm import build_ranking_embed
                week_id       = current_week_id()
                participantes = db_ranking_semana(guild_id, week_id)
                embed         = build_ranking_embed(guild_id, week_id, participantes, interaction.guild)
                await interaction.response.send_message(embed=embed, ephemeral=True)
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
