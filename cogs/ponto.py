"""Sistema de ponto: entrada, saida, logs e ranking semanal."""

from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import current_week_id
from services.ponto_service import (
    ponto_abrir,
    ponto_atualizar_ranking_message,
    ponto_fechar,
    ponto_get_aberto,
    ponto_get_config,
    ponto_ranking_semana,
    ponto_resumo_semana,
    ponto_sessoes_abertas,
    ponto_sessoes_usuario_semana,
    ponto_set_config,
    ponto_total_usuario_semana,
)

log = get_logger("ponto", "ponto.log")

PONTO_CATEGORY_ID = 1510973429791064218
LOG_CATEGORY_ID = 1510973908319338516

PAINEL_CHANNEL_NAME = "bater-ponto"
LOG_CHANNEL_NAME = "log-ponto"
RANKING_CHANNEL_NAME = "ranking-ponto"

COR_PONTO = 0x2ECC71
COR_SAIDA = 0xE67E22
COR_INFO = 0x3498DB
FOOTER = "Morro do Mineiro - Sistema de Ponto"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _fmt_dt(value: str | None) -> str:
    dt = _parse_dt(value)
    if not dt:
        return "-"
    return dt.strftime("%d/%m/%Y %H:%M")


def _fmt_date_br(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d/%m/%Y")


def _fmt_duration(seconds: int | float | None) -> str:
    total = int(seconds or 0)
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02}m"
    if minutos:
        return f"{minutos}m {segundos:02}s"
    return f"{segundos}s"


def _safe_name(member: discord.Member | None, fallback: str, limit: int = 28) -> str:
    name = member.display_name if member else fallback
    return name if len(name) <= limit else f"{name[: limit - 1]}..."


def _build_painel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Controle de Ponto",
        description=(
            "**Registre sua entrada e saida de forma rapida.**\n"
            "Abra o ponto ao iniciar e feche quando encerrar sua atividade."
        ),
        color=COR_INFO,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Como funciona",
        value=(
            "`Bater Ponto` abre seu ponto se voce nao tiver outro aberto.\n"
            "`Fechar Ponto` encerra seu ponto aberto e calcula o tempo."
        ),
        inline=False,
    )
    embed.add_field(
        name="Semana atual",
        value=f"`{_fmt_date_br(current_week_id())}`",
        inline=True,
    )
    embed.set_footer(text=FOOTER)
    return embed


def _build_ranking_embed(guild: discord.Guild, guild_id: str, week_id: str) -> discord.Embed:
    ranking = ponto_ranking_semana(guild_id, week_id, limit=25)
    resumo = ponto_resumo_semana(guild_id, week_id)

    embed = discord.Embed(
        title="Ranking Semanal de Ponto",
        description=f"Semana: `{week_id}`",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Resumo",
        value=(
            f"Membros ativos: `{resumo['usuarios']}`\n"
            f"Sessoes fechadas: `{resumo['sessoes']}`\n"
            f"Tempo total: `{_fmt_duration(resumo['total_segundos'])}`\n"
            f"Pontos abertos agora: `{resumo['abertas']}`"
        ),
        inline=False,
    )

    if not ranking:
        embed.add_field(
            name="Ranking",
            value="Nenhum ponto fechado nesta semana ainda.",
            inline=False,
        )
    else:
        medalhas = ["1.", "2.", "3."]
        linhas = []
        for idx, row in enumerate(ranking, start=1):
            member = guild.get_member(int(row["user_id"]))
            pos = medalhas[idx - 1] if idx <= 3 else f"{idx}."
            nome = _safe_name(member, f"ID {row['user_id']}", limit=24)
            linhas.append(
                f"`{pos}` **{nome}** - `{_fmt_duration(row['total_segundos'])}` "
                f"em `{row['sessoes']}` sessao(oes)"
            )
        embed.add_field(name="Ranking", value="\n".join(linhas), inline=False)

    embed.set_footer(text=FOOTER)
    return embed


def _build_status_embed(member: discord.Member | discord.User, guild_id: str) -> discord.Embed:
    user_id = str(member.id)
    week_id = current_week_id()
    aberto = ponto_get_aberto(guild_id, user_id)
    total = ponto_total_usuario_semana(guild_id, week_id, user_id)
    sessoes = ponto_sessoes_usuario_semana(guild_id, week_id, user_id)

    embed = discord.Embed(
        title="Meu Ponto",
        description=f"Resumo de **{member.display_name}** nesta semana.",
        color=COR_PONTO if aberto else COR_INFO,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Semana", value=f"`{week_id}`", inline=True)
    embed.add_field(name="Status", value="`Aberto`" if aberto else "`Fechado`", inline=True)
    embed.add_field(name="Total fechado", value=f"`{_fmt_duration(total)}`", inline=True)
    embed.add_field(name="Sessoes na semana", value=f"`{len(sessoes)}`", inline=True)
    if aberto:
        embed.add_field(name="Entrada atual", value=f"`{_fmt_dt(aberto['entrada_em'])}`", inline=True)
    embed.set_footer(text=FOOTER)
    return embed


def _build_result_embed(member: discord.Member | discord.User, sessao, acao: str) -> discord.Embed:
    is_saida = acao == "saida"
    embed = discord.Embed(
        title="Saida registrada" if is_saida else "Entrada registrada",
        description=(
            "Seu ponto foi fechado com sucesso."
            if is_saida
            else "Seu ponto foi aberto com sucesso."
        ),
        color=COR_SAIDA if is_saida else COR_PONTO,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Membro", value=member.mention, inline=True)
    embed.add_field(name="Entrada", value=f"`{_fmt_dt(sessao['entrada_em'])}`", inline=True)
    if is_saida:
        embed.add_field(name="Saida", value=f"`{_fmt_dt(sessao['saida_em'])}`", inline=True)
        embed.add_field(name="Duracao", value=f"`{_fmt_duration(sessao['duracao_segundos'])}`", inline=True)
    embed.set_footer(text=FOOTER)
    return embed


class PontoPainelView(discord.ui.View):
    def __init__(self, cog: "PontoCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Bater Ponto - Abrir Entrada",
        style=discord.ButtonStyle.success,
        custom_id="ponto_painel:bater",
        row=0,
    )
    async def bater_ponto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.abrir_ponto(interaction)

    @discord.ui.button(
        label="Fechar Ponto - Encerrar Saida",
        style=discord.ButtonStyle.danger,
        custom_id="ponto_painel:fechar",
        row=0,
    )
    async def fechar_ponto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.fechar_ponto_usuario(interaction)


class PontoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(PontoPainelView(self))

    async def _fetch_channel(self, guild: discord.Guild, channel_id: int):
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except Exception:
                return None
        return channel

    async def _get_or_create_text_channel(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        read_only: bool,
    ) -> discord.TextChannel:
        existing = discord.utils.get(guild.text_channels, name=name, category=category)
        if existing:
            return existing

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                send_messages=not read_only,
            )
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
            )

        return await guild.create_text_channel(
            name,
            category=category,
            overwrites=overwrites,
            reason="Criacao do sistema de ponto",
        )

    async def enviar_log_ponto(
        self,
        guild: discord.Guild,
        member: discord.Member | discord.User,
        sessao,
        acao: str,
    ) -> bool:
        cfg = ponto_get_config(str(guild.id))
        if not cfg or not cfg["log_channel_id"]:
            return False

        channel = guild.get_channel(int(cfg["log_channel_id"]))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(cfg["log_channel_id"]))
            except Exception as exc:
                log.warning("Canal de log de ponto nao encontrado: %s", exc)
                return False

        entrada = _fmt_dt(sessao["entrada_em"])
        saida = _fmt_dt(sessao["saida_em"])
        is_saida = acao == "saida"

        embed = discord.Embed(
            title="Ponto fechado" if is_saida else "Ponto aberto",
            color=COR_SAIDA if is_saida else COR_PONTO,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Membro", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Entrada", value=f"`{entrada}`", inline=True)
        if is_saida:
            embed.add_field(name="Saida", value=f"`{saida}`", inline=True)
            embed.add_field(
                name="Duracao",
                value=f"`{_fmt_duration(sessao['duracao_segundos'])}`",
                inline=True,
            )
        observacao = sessao["observacao_saida"] if is_saida else sessao["observacao_entrada"]
        if observacao:
            embed.add_field(name="Observacao", value=observacao[:1024], inline=False)
        if sessao["fechado_por"] and str(sessao["fechado_por"]) != str(member.id):
            embed.add_field(name="Fechado por", value=f"<@{sessao['fechado_por']}>", inline=True)
        embed.set_footer(text=FOOTER)

        try:
            await channel.send(embed=embed)
            return True
        except Exception as exc:
            log.error("Erro ao enviar log de ponto: %s", exc, exc_info=True)
            return False

    async def atualizar_ranking_fixo(self, guild_id: str) -> bool:
        cfg = ponto_get_config(guild_id)
        if not cfg or not cfg["ranking_channel_id"] or not cfg["ranking_message_id"]:
            return False

        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return False

        week_id = current_week_id()
        embed = _build_ranking_embed(guild, guild_id, week_id)

        try:
            channel = guild.get_channel(int(cfg["ranking_channel_id"])) or await guild.fetch_channel(
                int(cfg["ranking_channel_id"])
            )
            message = await channel.fetch_message(int(cfg["ranking_message_id"]))
            await message.edit(embed=embed)
            ponto_atualizar_ranking_message(guild_id, str(channel.id), str(message.id), week_id)
            return True
        except discord.NotFound:
            log.warning("Mensagem de ranking de ponto nao encontrada para guild %s", guild_id)
            return False
        except Exception as exc:
            log.error("Erro ao atualizar ranking de ponto: %s", exc, exc_info=True)
            return False

    @app_commands.command(name="setup_ponto", description="Cria ou recria o painel e canais do sistema de ponto.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_ponto(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        guild_id = str(interaction.guild_id)

        ponto_target = await self._fetch_channel(guild, PONTO_CATEGORY_ID)
        log_target = await self._fetch_channel(guild, LOG_CATEGORY_ID)
        if ponto_target is None:
            await interaction.followup.send(
                f"Nao encontrei o destino do painel de ponto `{PONTO_CATEGORY_ID}`. "
                "Confirme se o ID e de um canal/categoria deste servidor e se o bot consegue ver.",
                ephemeral=True,
            )
            return
        if log_target is None:
            await interaction.followup.send(
                f"Nao encontrei o destino de logs `{LOG_CATEGORY_ID}`. "
                "Confirme se o ID e de um canal/categoria deste servidor e se o bot consegue ver.",
                ephemeral=True,
            )
            return

        if isinstance(ponto_target, discord.CategoryChannel):
            painel_channel = await self._get_or_create_text_channel(
                guild, ponto_target, PAINEL_CHANNEL_NAME, read_only=True
            )
        elif isinstance(ponto_target, discord.TextChannel):
            painel_channel = ponto_target
        else:
            await interaction.followup.send(
                f"O destino do painel `{PONTO_CATEGORY_ID}` precisa ser uma categoria ou canal de texto.",
                ephemeral=True,
            )
            return

        if isinstance(log_target, discord.CategoryChannel):
            log_channel = await self._get_or_create_text_channel(
                guild, log_target, LOG_CHANNEL_NAME, read_only=True
            )
            ranking_channel = await self._get_or_create_text_channel(
                guild, log_target, RANKING_CHANNEL_NAME, read_only=True
            )
        elif isinstance(log_target, discord.TextChannel):
            log_channel = log_target
            ranking_channel = log_target
        else:
            await interaction.followup.send(
                f"O destino de logs `{LOG_CATEGORY_ID}` precisa ser uma categoria ou canal de texto.",
                ephemeral=True,
            )
            return

        painel_msg = await painel_channel.send(embed=_build_painel_embed(), view=PontoPainelView(self))
        week_id = current_week_id()
        ranking_msg = await ranking_channel.send(embed=_build_ranking_embed(guild, guild_id, week_id))

        ponto_set_config(
            guild_id,
            str(PONTO_CATEGORY_ID),
            str(LOG_CATEGORY_ID),
            str(painel_channel.id),
            str(log_channel.id),
            str(ranking_channel.id),
            str(ranking_msg.id),
            week_id,
        )

        await interaction.followup.send(
            "Sistema de ponto configurado:\n"
            f"Painel: {painel_channel.mention}\n"
            f"Logs: {log_channel.mention}\n"
            f"Ranking: {ranking_channel.mention}",
            ephemeral=True,
        )
        log.info("Sistema de ponto configurado (guild %s, painel msg %s)", guild_id, painel_msg.id)

    @setup_ponto.error
    async def setup_ponto_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Voce precisa da permissao Gerenciar Servidor.",
                ephemeral=True,
            )
        else:
            log.error("Erro em /setup_ponto: %s", error, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("Erro inesperado ao configurar ponto.", ephemeral=True)
            else:
                await interaction.response.send_message("Erro inesperado ao configurar ponto.", ephemeral=True)

    async def abrir_ponto(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este recurso em um servidor.", ephemeral=True)
            return
        if getattr(interaction.user, "bot", False):
            await interaction.response.send_message("Bots nao podem bater ponto.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        aberto = ponto_get_aberto(guild_id, user_id)
        if aberto:
            await interaction.followup.send(
                f"Voce ja tem um ponto aberto desde **{_fmt_dt(aberto['entrada_em'])}**. "
                "Feche esse ponto antes de abrir outro.",
                ephemeral=True,
            )
            return

        sessao = ponto_abrir(guild_id, user_id)
        await self.enviar_log_ponto(interaction.guild, interaction.user, sessao, "entrada")
        await interaction.followup.send(
            embed=_build_result_embed(interaction.user, sessao, "entrada"),
            ephemeral=True,
        )

    async def fechar_ponto_usuario(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este recurso em um servidor.", ephemeral=True)
            return
        if getattr(interaction.user, "bot", False):
            await interaction.response.send_message("Bots nao podem bater ponto.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        aberto = ponto_get_aberto(guild_id, user_id)
        if not aberto:
            await interaction.followup.send(
                "Voce nao tem nenhum ponto aberto para fechar.",
                ephemeral=True,
            )
            return

        sessao = ponto_fechar(guild_id, user_id, fechado_por=user_id)
        if sessao is None:
            await interaction.followup.send(
                "Nao encontrei um ponto aberto para fechar. Tente novamente.",
                ephemeral=True,
            )
            return

        await self.enviar_log_ponto(interaction.guild, interaction.user, sessao, "saida")
        await self.atualizar_ranking_fixo(guild_id)
        await interaction.followup.send(
            embed=_build_result_embed(interaction.user, sessao, "saida"),
            ephemeral=True,
        )

    async def enviar_status_pessoal(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este recurso em um servidor.", ephemeral=True)
            return

        embed = _build_status_embed(interaction.user, str(interaction.guild_id))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def enviar_ranking(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este recurso em um servidor.", ephemeral=True)
            return

        embed = _build_ranking_embed(interaction.guild, str(interaction.guild_id), current_week_id())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ponto", description="Mostra seu status e total semanal de ponto.")
    async def ponto(self, interaction: discord.Interaction):
        await self.enviar_status_pessoal(interaction)

    @app_commands.command(name="ranking_ponto", description="Mostra o ranking semanal de ponto.")
    async def ranking_ponto(self, interaction: discord.Interaction):
        await self.enviar_ranking(interaction)

    @app_commands.command(name="ponto_abertos", description="Lista pontos abertos. Apenas admins.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ponto_abertos(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
            return

        abertos = ponto_sessoes_abertas(str(interaction.guild_id))
        embed = discord.Embed(
            title="Pontos Abertos",
            color=COR_INFO,
            timestamp=discord.utils.utcnow(),
        )
        if not abertos:
            embed.description = "Nenhum ponto aberto no momento."
        else:
            linhas = []
            for row in abertos[:25]:
                member = interaction.guild.get_member(int(row["user_id"]))
                nome = _safe_name(member, f"ID {row['user_id']}", limit=24)
                linhas.append(f"**{nome}** - entrada `{_fmt_dt(row['entrada_em'])}`")
            embed.description = "\n".join(linhas)
            if len(abertos) > 25:
                embed.set_footer(text=f"Exibindo 25 de {len(abertos)} pontos abertos")
            else:
                embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ponto_abertos.error
    async def ponto_abertos_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Voce precisa da permissao Gerenciar Servidor.",
                ephemeral=True,
            )

    @app_commands.command(name="ponto_fechar", description="Fecha manualmente o ponto aberto de um membro.")
    @app_commands.describe(membro="Membro que tera o ponto fechado")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ponto_fechar(self, interaction: discord.Interaction, membro: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        sessao = ponto_fechar(
            guild_id,
            str(membro.id),
            observacao=f"Fechado manualmente por {interaction.user} ({interaction.user.id})",
            fechado_por=str(interaction.user.id),
        )
        if sessao is None:
            await interaction.followup.send(
                f"{membro.mention} nao possui ponto aberto.",
                ephemeral=True,
            )
            return

        await self.enviar_log_ponto(interaction.guild, membro, sessao, "saida")
        await self.atualizar_ranking_fixo(guild_id)
        await interaction.followup.send(
            f"Ponto de {membro.mention} fechado. Duracao: **{_fmt_duration(sessao['duracao_segundos'])}**.",
            ephemeral=True,
        )

    @ponto_fechar.error
    async def ponto_fechar_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Voce precisa da permissao Gerenciar Servidor.",
                ephemeral=True,
            )
        else:
            log.error("Erro em /ponto_fechar: %s", error, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("Erro inesperado ao fechar ponto.", ephemeral=True)
            else:
                await interaction.response.send_message("Erro inesperado ao fechar ponto.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PontoCog(bot))
    log.info("PontoCog carregado com sucesso.")
