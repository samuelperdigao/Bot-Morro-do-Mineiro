"""
cogs/backup.py - Backup diário dos bancos do bot.

Todos os dias às 04:00 (horário de Brasília) gera uma cópia compactada do
farm.db e do bau.db em backups/ (mantém as últimas 14 de cada) e, se
CANAL_BACKUP_ID estiver configurado, envia os arquivos para esse canal.

/backup_agora (administradores) roda o mesmo processo na hora.
"""

from __future__ import annotations

import asyncio
import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.config import CANAL_BACKUP_ID, TZ_STR
from core.error_reporting import proteger_loop, report_error
from core.logger import get_logger
from services.backup_service import BackupResultado, backup_todos

log = get_logger("backup", "bot.log")

TZ = ZoneInfo(TZ_STR)
HORARIO_BACKUP = datetime.time(hour=4, minute=0, tzinfo=TZ)
# Limite de upload de arquivos para bots sem boost no servidor.
LIMITE_UPLOAD_BYTES = 10 * 1024 * 1024


def _fmt_tamanho(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / 1024:.0f} KB"


class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        proteger_loop(self.backup_diario, "backup_diario", lambda: self.bot)
        self.backup_diario.start()

    def cog_unload(self):
        self.backup_diario.cancel()

    async def executar_backup(self, origem: str) -> list[BackupResultado]:
        async with self._lock:
            resultados = await asyncio.to_thread(backup_todos)
        for item in resultados:
            log.info("Backup %s gerado: %s (%s)", item.nome, item.caminho, _fmt_tamanho(item.tamanho_bytes))
        await self._enviar_para_canal(resultados, origem)
        return resultados

    async def _enviar_para_canal(self, resultados: list[BackupResultado], origem: str) -> None:
        if not CANAL_BACKUP_ID or not resultados:
            return
        canal = self.bot.get_channel(CANAL_BACKUP_ID)
        if canal is None:
            canal = await self.bot.fetch_channel(CANAL_BACKUP_ID)

        arquivos = []
        linhas = []
        for item in resultados:
            if item.tamanho_bytes <= LIMITE_UPLOAD_BYTES:
                arquivos.append(discord.File(item.caminho, filename=item.caminho.name))
                linhas.append(f"✅ **{item.nome}** — {_fmt_tamanho(item.tamanho_bytes)}")
            else:
                linhas.append(
                    f"⚠️ **{item.nome}** — {_fmt_tamanho(item.tamanho_bytes)} "
                    "(acima do limite de upload; mantido só no servidor)"
                )

        embed = discord.Embed(
            title="💾 Backup dos bancos",
            description="\n".join(linhas),
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Morro do Mineiro — Sistema de Backup • {origem}")
        await canal.send(embed=embed, files=arquivos)

    @tasks.loop(time=HORARIO_BACKUP)
    async def backup_diario(self):
        await self.executar_backup("automático")

    @backup_diario.before_loop
    async def _antes_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="backup_agora", description="Gera e envia agora um backup dos bancos do bot.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_agora(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            resultados = await self.executar_backup(f"manual por {interaction.user}")
        except Exception as exc:
            await report_error(self.bot, "/backup_agora", exc)
            await interaction.followup.send("❌ Falha ao gerar o backup. Veja o log de erros.", ephemeral=True)
            return

        if not resultados:
            await interaction.followup.send("⚠️ Nenhum banco encontrado para backup.", ephemeral=True)
            return
        resumo = "\n".join(f"• **{r.nome}**: {_fmt_tamanho(r.tamanho_bytes)}" for r in resultados)
        destino = f"<#{CANAL_BACKUP_ID}>" if CANAL_BACKUP_ID else "o disco do servidor (CANAL_BACKUP_ID não configurado)"
        await interaction.followup.send(f"✅ Backup gerado e enviado para {destino}.\n{resumo}", ephemeral=True)

    @backup_agora.error
    async def _backup_agora_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            mensagem = "❌ Apenas administradores podem gerar backup."
        else:
            log.error("Erro em /backup_agora: %s", error, exc_info=True)
            mensagem = "❌ Erro inesperado."
        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
    log.info("BackupCog carregado com sucesso.")
