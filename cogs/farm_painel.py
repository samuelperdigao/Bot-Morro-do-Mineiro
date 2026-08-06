"""Painel fixo de farm com lançamentos exclusivos por ticket."""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from core.farm_policy import FARM_TICKET_ONLY_MESSAGE
from core.permissions import is_lideranca, is_permitido_farm
from services.db_service import (
    current_week_id,
    fmt_dt,
    db_eventos_usuario,
    db_get_editores_farm_role_ids,
    db_get_lideranca_role_ids,
    db_get_meta,
    db_get_permitidos_role_ids,
    db_get_progresso,
    db_get_system_config,
    db_get_ultimo_evento,
    db_evento_itens,
    db_is_farm_configured,
)

log = get_logger("farm_painel", "farm.log")

COR_FARM   = 0xFFD700
FOOTER_FARM = "Morro do Mineiro — Sistema de Farm"


async def lock_farm_panel_channel(
    channel: discord.TextChannel,
    guild: discord.Guild,
) -> int:
    """Deixa o painel somente leitura sem impedir interacoes com os botoes."""
    targets = list(channel.overwrites)
    if guild.default_role not in targets:
        targets.insert(0, guild.default_role)

    changed = 0
    bot_member = guild.me
    for target in targets:
        if bot_member is not None and target == bot_member:
            continue
        overwrite = channel.overwrites_for(target)
        if overwrite.send_messages is False and overwrite.send_messages_in_threads is False:
            continue
        overwrite.send_messages = False
        overwrite.send_messages_in_threads = False
        await channel.set_permissions(
            target,
            overwrite=overwrite,
            reason="Painel de farm somente leitura",
        )
        changed += 1

    if bot_member is not None:
        overwrite = channel.overwrites_for(bot_member)
        if overwrite.send_messages is not True:
            overwrite.send_messages = True
            await channel.set_permissions(
                bot_member,
                overwrite=overwrite,
                reason="Permitir publicacoes do bot no painel de farm",
            )
            changed += 1
    return changed


class FarmPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ── Ver Meu Farm ──────────────────────────────────────────────────────────

    @discord.ui.button(
        label="📊 Ver Meu Farm",
        style=discord.ButtonStyle.primary,
        custom_id="farm_painel:ver",
        row=0,
    )
    async def ver(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id       = str(interaction.guild_id)
        member         = interaction.user
        permitidos_ids = db_get_permitidos_role_ids(guild_id)

        if not is_permitido_farm(member, permitidos_ids):
            await interaction.response.send_message(
                "❌ Você não tem permissão para ver farm.", ephemeral=True
            )
            return

        week_id = current_week_id()
        prog    = db_get_progresso(guild_id, week_id, str(member.id))
        meta    = db_get_meta(guild_id, week_id)

        if not prog and not meta:
            await interaction.response.send_message(
                "⚠️ Nenhum farm registrado esta semana.", ephemeral=True
            )
            return

        from cogs.farm import build_farm_embed
        embed = build_farm_embed(meta, prog, member, week_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("ver_meu_farm via painel: %s (guild %s)", member.name, guild_id)

    # ── Editar Farm ───────────────────────────────────────────────────────────

    @discord.ui.button(
        label="✏️ Editar Farm",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_painel:editar",
        row=1,
    )
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id      = str(interaction.guild_id)
        member        = interaction.user
        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        editores_ids  = db_get_editores_farm_role_ids(guild_id)

        if not is_lideranca(member, lideranca_ids) and not is_lideranca(member, editores_ids):
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
        log.info("editar_farm via painel: %s (guild %s)", member.name, guild_id)

    # ── Farm Membro ──────────────────────────────────────────────────────────

    @discord.ui.button(
        label="👥 Farm Membro",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_painel:farm_membro",
        row=1,
    )
    async def farm_membro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmPainelCog")
        if not cog:
            await interaction.response.send_message(
                "❌ Erro interno: FarmPainelCog não carregado.",
                ephemeral=True,
            )
            return

        await cog.mostrar_acoes_farm_membro(interaction)

    @discord.ui.button(
        label="🎫 Abrir Ticket Semanal",
        style=discord.ButtonStyle.success,
        custom_id="farm_painel:abrir_ticket",
        row=2,
    )
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        if not is_permitido_farm(interaction.user, db_get_permitidos_role_ids(guild_id)):
            await interaction.response.send_message(
                "❌ Você não tem permissão para participar do farm.", ephemeral=True
            )
            return
        cog = interaction.client.get_cog("FarmTicketsCog")
        if not cog:
            await interaction.response.send_message(
                "❌ Sistema de tickets indisponível.", ephemeral=True
            )
            return
        await cog.open_ticket(interaction)

    @discord.ui.button(
        label="Abrir para Membro",
        style=discord.ButtonStyle.success,
        custom_id="farm_painel:abrir_ticket_membro",
        row=2,
    )
    async def abrir_ticket_membro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmTicketsCog")
        if not cog:
            await interaction.response.send_message(
                "Sistema de tickets indisponivel.", ephemeral=True
            )
            return
        if not cog.is_ticket_operator(interaction.user):
            await interaction.response.send_message(
                "Apenas Gerente de Farm, Gerente Geral ou Administrador podem abrir ticket para outro membro.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Selecione o membro que sera dono do ticket:",
            view=FarmTicketMemberSelectView(cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="🗑️ Excluir Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="farm_painel:excluir_ticket_admin",
        row=2,
    )
    async def excluir_ticket_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("FarmTicketsCog")
        if not cog:
            await interaction.response.send_message(
                "❌ Sistema de tickets indisponível.", ephemeral=True
            )
            return
        await cog.show_admin_ticket_manager(interaction)


class LegacyFarmLaunchView(discord.ui.View):
    """Responde aos botões de lançamento que ainda existam em mensagens antigas."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _disabled(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)

    @discord.ui.button(
        label="Lançamento antigo desativado",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_painel:lancar",
    )
    async def lancar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disabled(interaction)

    @discord.ui.button(
        label="Lançamento antigo desativado",
        style=discord.ButtonStyle.secondary,
        custom_id="farm_painel:lancar_dinheiro",
    )
    async def lancar_dinheiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disabled(interaction)


class FarmTicketMemberSelect(discord.ui.UserSelect):
    def __init__(self, ticket_cog):
        super().__init__(
            placeholder="Selecione quem sera dono do ticket",
            min_values=1,
            max_values=1,
        )
        self.ticket_cog = ticket_cog

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            if not interaction.guild:
                await interaction.response.send_message(
                    "Nao consegui identificar o servidor desta interacao.",
                    ephemeral=True,
                )
                return
            try:
                member = await interaction.guild.fetch_member(member.id)
            except Exception:
                await interaction.response.send_message(
                    "Nao consegui encontrar esse membro no servidor.",
                    ephemeral=True,
                )
                return
        await self.ticket_cog._open_ticket_for_owner(
            interaction,
            member,
            administrative=True,
        )


class FarmTicketMemberSelectView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=180)
        self.add_item(FarmTicketMemberSelect(ticket_cog))


class FarmMembroSelect(discord.ui.UserSelect):
    def __init__(self, cog: "FarmPainelCog", acao: str):
        placeholder = (
            "Selecione o membro que receberá o farm"
            if acao == "lancar"
            else "Selecione o membro que terá farm editado"
        )
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
        )
        self.cog = cog
        self.acao = acao

    async def callback(self, interaction: discord.Interaction):
        membro = self.values[0]
        if not isinstance(membro, discord.Member):
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ Não consegui identificar o servidor desta interação.",
                    ephemeral=True,
                )
                return
            try:
                membro = await interaction.guild.fetch_member(membro.id)
            except Exception:
                await interaction.response.send_message(
                    "❌ Não consegui encontrar esse membro no servidor.",
                    ephemeral=True,
                )
                return

        await self.cog.processar_farm_membro(interaction, self.acao, membro)


class FarmMembroSelectView(discord.ui.View):
    def __init__(self, cog: "FarmPainelCog", acao: str):
        super().__init__(timeout=180)
        self.add_item(FarmMembroSelect(cog, acao))


class FarmMembroActionView(discord.ui.View):
    def __init__(self, cog: "FarmPainelCog"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="✏️ Editar Farm", style=discord.ButtonStyle.secondary)
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.mostrar_seletor_farm_membro(interaction, "editar")


class FarmMembroEventoSelect(discord.ui.Select):
    def __init__(self, cog: "FarmPainelCog", membro: discord.Member, eventos: list):
        self.cog = cog
        self.membro = membro
        options = []
        for ev in eventos[:25]:
            itens = db_evento_itens(ev)
            resumo = " | ".join(f"{nome}: {qtd}" for nome, qtd in itens.items() if qtd > 0) or "todos zerados"
            options.append(discord.SelectOption(
                label=f"#{ev['id']} - {fmt_dt(ev['criado_em'])}"[:100],
                value=str(ev["id"]),
                description=resumo[:100],
            ))
        super().__init__(
            placeholder="Selecione o lançamento que deseja editar",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.abrir_edicao_evento_membro(
            interaction,
            self.membro,
            int(self.values[0]),
        )


class FarmMembroEventoSelectView(discord.ui.View):
    def __init__(self, cog: "FarmPainelCog", membro: discord.Member, eventos: list):
        super().__init__(timeout=180)
        self.add_item(FarmMembroEventoSelect(cog, membro, eventos))


# ── Embed fixo do painel ──────────────────────────────────────────────────────

def _build_painel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌾 Painel de Farm — Morro do Mineiro",
        description=(
            "**Abrir para Membro** - Gerente de Farm, Gerente Geral e Administrador abrem ticket para outra pessoa.\n"
            "**🎫 Abrir Ticket Semanal** — Único local para enviar novos lançamentos e comprovantes.\n"
            "**📊 Ver Meu Farm** — Veja seu progresso e percentual atingido.\n"
            "**👥 Farm Membro** — Liderança consulta lançamentos para edição administrativa.\n"
            "**✏️ Editar Farm** — Correção administrativa de registros existentes."
        ),
        color=COR_FARM,
    )
    embed.set_footer(text=FOOTER_FARM)
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class FarmPainelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(FarmPainelView())
        bot.add_view(LegacyFarmLaunchView())

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            row = db_get_system_config(str(guild.id), "farm")
            if not row or not row["canal_interacao_id"]:
                continue
            try:
                channel = guild.get_channel(int(row["canal_interacao_id"]))
                if channel is None:
                    channel = await guild.fetch_channel(int(row["canal_interacao_id"]))
                if isinstance(channel, discord.TextChannel):
                    changed = await lock_farm_panel_channel(channel, guild)
                    if changed:
                        log.info(
                            "Permissoes do painel farm atualizadas (guild %s, canal %s, alteracoes %s)",
                            guild.id,
                            channel.id,
                            changed,
                        )
            except (discord.Forbidden, discord.HTTPException, ValueError):
                log.exception(
                    "Falha ao aplicar permissoes no painel farm (guild %s)", guild.id
                )

    @app_commands.command(
        name="farm_membro",
        description="Edita um lançamento existente de outro membro (liderança).",
    )
    @app_commands.describe(
        acao="Ação administrativa disponível.",
        membro="Membro que receberá a ação.",
    )
    @app_commands.choices(acao=[
        app_commands.Choice(name="Editar Farm", value="editar"),
    ])
    async def farm_membro(
        self,
        interaction: discord.Interaction,
        acao: str,
        membro: discord.Member,
    ):
        await self.processar_farm_membro(interaction, acao, membro)

    async def mostrar_acoes_farm_membro(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        executor = interaction.user

        if not await self._validar_lideranca_farm(interaction, guild_id, executor):
            return

        await interaction.response.send_message(
            "Escolha o que deseja fazer para um membro:",
            view=FarmMembroActionView(self),
            ephemeral=True,
        )

    async def mostrar_seletor_farm_membro(self, interaction: discord.Interaction, acao: str):
        guild_id = str(interaction.guild_id)
        executor = interaction.user

        if not await self._validar_lideranca_farm(interaction, guild_id, executor):
            return

        verbo = "receberá o lançamento" if acao == "lancar" else "terá um lançamento editado"
        await interaction.response.send_message(
            f"Selecione o membro que {verbo}:",
            view=FarmMembroSelectView(self, acao),
            ephemeral=True,
        )

    async def processar_farm_membro(self, interaction: discord.Interaction, acao: str, membro: discord.Member):
        if acao == "lancar":
            await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)
        elif acao == "editar":
            await self.mostrar_lancamentos_edicao_membro(interaction, membro)
        else:
            await interaction.response.send_message("❌ Ação inválida.", ephemeral=True)

    async def _validar_lideranca_farm(
        self,
        interaction: discord.Interaction,
        guild_id: str,
        executor: discord.Member,
    ) -> bool:
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return False

        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        if not is_lideranca(executor, lideranca_ids):
            await interaction.response.send_message(
                "❌ Apenas liderança pode lançar farm para outro membro.",
                ephemeral=True,
            )
            return False
        return True

    async def _validar_membro_alvo(
        self,
        interaction: discord.Interaction,
        guild_id: str,
        membro: discord.Member,
    ) -> bool:
        if membro.bot:
            await interaction.response.send_message(
                "❌ Não é possível lançar farm para bots.",
                ephemeral=True,
            )
            return False

        permitidos_ids = db_get_permitidos_role_ids(guild_id)
        if not is_permitido_farm(membro, permitidos_ids):
            await interaction.response.send_message(
                "❌ O membro escolhido não tem permissão/cargo para participar do farm.",
                ephemeral=True,
            )
            return False
        return True

    async def abrir_lancamento_membro(self, interaction: discord.Interaction, membro: discord.Member):
        await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)

    async def mostrar_lancamentos_edicao_membro(self, interaction: discord.Interaction, membro: discord.Member):
        guild_id = str(interaction.guild_id)
        executor = interaction.user

        if not await self._validar_lideranca_farm(interaction, guild_id, executor):
            return
        if not await self._validar_membro_alvo(interaction, guild_id, membro):
            return

        week_id = current_week_id()
        eventos = list(reversed(db_eventos_usuario(guild_id, week_id, str(membro.id))))[:25]
        if not eventos:
            await interaction.response.send_message(
                "❌ Nenhum lançamento encontrado para esse membro nesta semana.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Selecione qual lançamento de {membro.mention} deseja editar:",
            view=FarmMembroEventoSelectView(self, membro, eventos),
            ephemeral=True,
        )

    async def abrir_edicao_evento_membro(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        event_id: int,
    ):
        guild_id = str(interaction.guild_id)
        executor = interaction.user

        if not await self._validar_lideranca_farm(interaction, guild_id, executor):
            return
        if not await self._validar_membro_alvo(interaction, guild_id, membro):
            return

        week_id = current_week_id()
        evento = next(
            (ev for ev in db_eventos_usuario(guild_id, week_id, str(membro.id)) if int(ev["id"]) == event_id),
            None,
        )
        if not evento:
            await interaction.response.send_message(
                "❌ Lançamento não encontrado para esse membro nesta semana.",
                ephemeral=True,
            )
            return

        farm_cog = interaction.client.get_cog("FarmCog")
        if not farm_cog:
            await interaction.response.send_message(
                "❌ Erro interno: FarmCog não carregado.",
                ephemeral=True,
            )
            return

        from cogs.farm import EditarUltimoModal
        await interaction.response.send_modal(
            EditarUltimoModal(
                farm_cog,
                week_id,
                guild_id,
                str(membro.id),
                db_evento_itens(evento),
                event_id=event_id,
            )
        )

        log.info(
            "editar_farm_membro via painel: executor=%s alvo=%s evento=%s (guild %s)",
            executor.id,
            membro.id,
            event_id,
            guild_id,
        )

    @app_commands.command(
        name="setup_farm_painel",
        description="Posta o painel de farm no canal configurado no dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_farm_painel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        row = db_get_system_config(guild_id, "farm")
        if not row or not row["canal_interacao_id"]:
            await interaction.followup.send(
                "❌ Configure o canal do sistema de Farm no dashboard primeiro (`/setup_dashboard`).",
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

        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ O canal configurado precisa ser um canal de texto.", ephemeral=True
            )
            return

        await lock_farm_panel_channel(channel, interaction.guild)
        await channel.send(embed=_build_painel_embed(), view=FarmPainelView())
        await interaction.followup.send(
            f"✅ Painel de farm postado em {channel.mention}!", ephemeral=True
        )
        log.info("Painel farm postado (guild %s, canal %s)", guild_id, channel.id)

    @setup_farm_painel.error
    async def _error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
        else:
            log.error("Erro em /setup_farm_painel: %s", error, exc_info=True)
            try:
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmPainelCog(bot))
    log.info("FarmPainelCog carregado com sucesso.")
