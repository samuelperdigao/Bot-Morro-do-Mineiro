"""
cogs/ausencia.py - Sistema de ausências (multi-server).

Ausências migradas de ausencias.json para a tabela 'ausencias' no SQLite.
Canal de ausências lido da tabela guild_config por guild.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

from core.logger import get_logger
from core.error_reporting import proteger_loop
from core.command_config import is_enabled as _cmd_enabled, get_cog_config as _cog_cfg
from services.log_service import send_log
from services.db_service import (
    db_get_guild_config,
    db_is_ausencia_configured,
    db_ausencia_set,
    db_ausencias_ativos,
    db_ausencias_todos,
    db_ausencia_marcar_avisado,
    db_all_configured_guilds,
    TZ,
)

log = get_logger("ausencia", "ausencia.log")
COR_EMBED = 0xFFD700
FOOTER_AUSENCIA = "Morro do Mineiro — Sistema de Ausência"
LIMITE_DESCRICAO = 4000
ORCAMENTO_LISTA = 5400  # soma de todas as embeds da mensagem fica < 6000


# As datas continuam gravadas em UTC sem fuso (compatível com os registros
# existentes); a exibição é sempre no horário de Brasília.
def _utc_naive(valor: str | datetime) -> datetime:
    dt = datetime.fromisoformat(valor) if isinstance(valor, str) else valor
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _para_brt(valor: str | datetime) -> datetime:
    return _utc_naive(valor).replace(tzinfo=timezone.utc).astimezone(TZ)


def _fmt_data_brt(valor: str | datetime) -> str:
    return _para_brt(valor).strftime("%d/%m/%Y")


def _dias_restantes(fim: str | datetime, agora_utc: datetime) -> int:
    """Dias corridos (no calendário de Brasília) até a data de retorno."""
    hoje = _para_brt(agora_utc).date()
    return max((_para_brt(fim).date() - hoje).days, 0)


def _linhas_ausencias(ativos, agora_utc: datetime) -> list[str]:
    linhas = []
    for row in sorted(ativos, key=lambda r: _utc_naive(r["fim"])):
        motivo = (row["motivo"] or "Não informado").replace("\n", " ")
        if len(motivo) > 80:
            motivo = motivo[:77] + "..."
        nome = discord.utils.escape_markdown(row["nome"] or f"ID {row['user_id']}")
        linhas.append(
            f"👤 **{nome}** (<@{row['user_id']}>) — retorno `{_fmt_data_brt(row['fim'])}` "
            f"({_dias_restantes(row['fim'], agora_utc)} dia(s))\n└ {motivo}"
        )
    return linhas


def _embeds_ausencias(ativos, agora_utc: datetime) -> list[discord.Embed]:
    """Lista compacta em até 2 embeds.

    O Discord limita a 6000 caracteres a soma de TODAS as embeds de uma
    mensagem; quem não couber aparece como "+N ausente(s)".
    """
    linhas = _linhas_ausencias(ativos, agora_utc)
    blocos: list[str] = []
    atual = ""
    usados = 0
    exibidos = 0
    for linha in linhas:
        custo = len(linha) + 2
        if usados + custo > ORCAMENTO_LISTA:
            break
        candidato = f"{atual}\n\n{linha}" if atual else linha
        if len(candidato) > LIMITE_DESCRICAO:
            blocos.append(atual)
            atual = linha
        else:
            atual = candidato
        usados += custo
        exibidos += 1
    if atual:
        blocos.append(atual)
    restantes = len(linhas) - exibidos
    if restantes:
        blocos[-1] += f"\n\n… e mais **{restantes}** ausente(s)."

    embeds = []
    for i, bloco in enumerate(blocos, 1):
        titulo = "📋 Jogadores em Ausência"
        if len(blocos) > 1:
            titulo += f" ({i}/{len(blocos)})"
        embed = discord.Embed(title=titulo, description=bloco, color=COR_EMBED)
        embed.set_footer(text=f"{FOOTER_AUSENCIA} • {len(ativos)} ausente(s)")
        embeds.append(embed)
    return embeds


class AusenciaModal(discord.ui.Modal, title="📋 Registrar Ausência"):
    dias   = discord.ui.TextInput(
        label="Quantos dias ficará fora?",
        placeholder="Ex: 5  (máximo 7 dias)",
        min_length=1, max_length=1, required=True,
    )
    motivo = discord.ui.TextInput(
        label="Motivo da ausência",
        placeholder="Ex: Viagem, trabalho...",
        style=discord.TextStyle.paragraph,
        max_length=300, required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)

        if not _cmd_enabled("ausencia"):
            await interaction.followup.send(
                "❌ O registro de ausências está desativado pela administração.", ephemeral=True
            )
            return

        if not db_is_ausencia_configured(guild_id):
            await interaction.followup.send(
                "❌ O módulo de Ausências não está configurado. Um administrador deve usar `/setup_ausencia`.",
                ephemeral=True,
            )
            return

        if not self.dias.value.strip().isdigit():
            await interaction.followup.send("❌ Digite apenas o número de dias.", ephemeral=True)
            return

        dias_int = int(self.dias.value.strip())
        if dias_int < 1:
            await interaction.followup.send("❌ O número de dias precisa ser pelo menos 1.", ephemeral=True)
            return
        max_dias = _cog_cfg("ausencia").get("max_days", 7)
        if dias_int > max_dias:
            await interaction.followup.send(
                f"❌ Ausências acima de **{max_dias} dias** resultam em **PD automático**.\nEntre em contato com a administração.",
                ephemeral=True,
            )
            return

        motivo_texto = self.motivo.value.strip() or "Não informado"
        alerta_pd    = dias_int > 3
        inicio       = datetime.utcnow()
        fim          = inicio + timedelta(days=dias_int)
        user_id      = str(interaction.user.id)
        retorno_fmt  = _fmt_data_brt(fim)

        # Confere o canal ANTES de gravar: se não houver canal, nada é salvo.
        cfg = db_get_guild_config(guild_id)
        canal_id = int(cfg["canal_ausencias_id"]) if cfg and cfg["canal_ausencias_id"] else None
        canal    = interaction.guild.get_channel(canal_id) if canal_id else None
        if canal is None:
            await interaction.followup.send("❌ Canal de ausências não encontrado. Avise um admin.", ephemeral=True)
            return

        dados = {
            "nome":   interaction.user.display_name,
            "dias":   dias_int,
            "motivo": motivo_texto,
            "inicio": inicio.isoformat(),
            "fim":    fim.isoformat(),
            "avisado":    False,
            "message_id": None,
        }
        aviso_pd = (
            "\n\n⚠️ **Atenção:** você está no limite. Se ultrapassar **7 dias sem novo aviso**, receberá **PD automático**."
            if alerta_pd else ""
        )

        embed = discord.Embed(
            title="🏖️ Registro de Ausência",
            color=COR_EMBED,
            timestamp=inicio.replace(tzinfo=timezone.utc),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.description = (
            f"**{interaction.user.display_name}** estará ausente do RP por **{dias_int} dia(s)**." + aviso_pd
        )
        embed.add_field(name="👤 Jogador",   value=interaction.user.mention,        inline=True)
        embed.add_field(name="📅 Dias fora", value=f"`{dias_int} dia(s)`",          inline=True)
        embed.add_field(name="🔙 Retorno",   value=f"`{retorno_fmt}`",              inline=True)
        embed.add_field(name="📝 Motivo",    value=motivo_texto,                    inline=False)
        embed.set_footer(text=FOOTER_AUSENCIA)

        try:
            msg = await canal.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.error("Falha ao publicar ausência no canal %s", canal.id, exc_info=True)
            await interaction.followup.send(
                "❌ Não consegui publicar no canal de ausências. Avise um admin.", ephemeral=True
            )
            return
        dados["message_id"] = str(msg.id)
        db_ausencia_set(guild_id, user_id, dados)
        await interaction.followup.send(f"✅ Ausência registrada! Confira em {canal.mention}.", ephemeral=True)

        log_embed = discord.Embed(
            title="🏖️ Ausência Registrada",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(name="👤 Membro", value=f"{interaction.user.mention}\n`{user_id}`", inline=True)
        log_embed.add_field(name="📅 Dias", value=f"`{dias_int}`", inline=True)
        log_embed.add_field(name="🔙 Retorno", value=f"`{retorno_fmt}`", inline=True)
        log_embed.add_field(name="📝 Motivo", value=motivo_texto, inline=False)
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Ausência")
        await send_log(interaction.client, interaction.guild, "ausencia", log_embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no AusenciaModal: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
        except Exception:
            pass


class AusenciaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 Registrar Ausência",
        style=discord.ButtonStyle.primary,
        custom_id="ausencia_panel:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _cmd_enabled("ausencia"):
            await interaction.response.send_message(
                "❌ O registro de ausências está desativado pela administração.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AusenciaModal())


class Ausencia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        proteger_loop(self.verificar_ausencias, "ausencia_verificacao", lambda: self.bot)
        self.verificar_ausencias.start()

    async def cog_load(self):
        self.bot.add_view(AusenciaPanelView())

    def cog_unload(self):
        self.verificar_ausencias.cancel()

    @app_commands.command(
        name="painel_ausencia",
        description="Posta o painel de registro de ausência. (Apenas admins)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_ausencia_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not db_is_ausencia_configured(guild_id):
            await interaction.response.send_message(
                "❌ Configure o canal de ausências primeiro com `/setup_ausencia`.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🏖️ Sistema de Ausência",
            description=(
                "Vai ficar fora da cidade por um tempo?\n\n"
                "Clique no botão abaixo para registrar sua ausência.\n\n"
                "📌 **Regras:**\n"
                "• Ausências de até **3 dias** — registre e fique tranquilo\n"
                "• Ausências de **3 a 7 dias** — registre com atenção ao prazo\n"
                "• **Mais de 7 dias sem aviso** — PD automático aplicado\n\n"
                "Sempre renove seu aviso se precisar de mais tempo."
            ),
            color=COR_EMBED,
        )
        embed.set_footer(text=FOOTER_AUSENCIA)
        await interaction.channel.send(embed=embed, view=AusenciaPanelView())
        await interaction.response.send_message("✅ Painel de ausências postado!", ephemeral=True)

    @setup_ausencia_painel.error
    async def setup_ausencia_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)

    @app_commands.command(name="ausencias", description="Lista todos os jogadores atualmente ausentes.")
    async def listar_ausencias(self, interaction: discord.Interaction):
        if not _cmd_enabled("ausencia"):
            await interaction.response.send_message("❌ Este comando está desativado pela administração.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        if not db_is_ausencia_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo de Ausências não está configurado. Um administrador deve usar `/setup_ausencia`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=False)
        ativos = db_ausencias_ativos(guild_id)
        agora  = datetime.utcnow()
        if not ativos:
            await interaction.followup.send("✅ Nenhum jogador ausente no momento.")
            return
        await interaction.followup.send(embeds=_embeds_ausencias(ativos, agora))

    @tasks.loop(hours=1)
    async def verificar_ausencias(self):
        agora = datetime.utcnow()
        for guild_id_str in db_all_configured_guilds():
            if not db_is_ausencia_configured(guild_id_str):
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            todos = db_ausencias_todos(guild_id_str)
            for row in todos:
                if row["avisado"]:
                    continue
                try:
                    fim_dt = _utc_naive(row["fim"])
                except (TypeError, ValueError):
                    log.warning("Data de fim inválida na ausência de %s: %r", row["user_id"], row["fim"])
                    continue
                if agora >= fim_dt:
                    membro = guild.get_member(int(row["user_id"]))
                    if membro:
                        try:
                            await membro.send(
                                f"⏰ **Sua ausência venceu hoje ({_fmt_data_brt(fim_dt)}).**\n"
                                f"Se precisar de mais tempo, registre uma nova ausência pelo painel.\n"
                                f"Lembre-se: mais de **7 dias sem aviso** resulta em **PD automático**."
                            )
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    db_ausencia_marcar_avisado(guild_id_str, row["user_id"])

    @verificar_ausencias.before_loop
    async def _before_verificar(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Ausencia(bot))
