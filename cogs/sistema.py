"""Comandos gerais de saude e status do bot."""

import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.config import DB_PATH


class SistemaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Verifica a latencia do bot.")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        if latency_ms < 100:
            color, status = discord.Color.green(), "Excelente"
        elif latency_ms < 200:
            color, status = discord.Color.yellow(), "Normal"
        else:
            color, status = discord.Color.red(), "Alta"

        embed = discord.Embed(title="Pong!", color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="Latencia WebSocket", value=f"`{latency_ms}ms` - {status}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Informacoes sobre o bot.")
    async def status(self, interaction: discord.Interaction):
        start_time = getattr(self.bot, "start_time", datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        uptime = now - start_time
        total_seconds = int(uptime.total_seconds())
        horas = total_seconds // 3600
        minutos = (total_seconds % 3600) // 60
        segundos = total_seconds % 60

        try:
            if DB_PATH.exists():
                with sqlite3.connect(DB_PATH) as conn:
                    semanas = conn.execute("SELECT COUNT(DISTINCT week_id) FROM metas").fetchone()[0]
                    participantes = conn.execute("SELECT COUNT(DISTINCT user_id) FROM progresso").fetchone()[0]
                    eventos = conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
                db_info = f"`{semanas}` semanas | `{participantes}` participantes | `{eventos}` eventos"
            else:
                db_info = "Banco ainda nao inicializado"
        except Exception:
            db_info = "N/A"

        embed = discord.Embed(title="Status do Bot", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.add_field(name="Bot", value=f"`{self.bot.user}`", inline=True)
        embed.add_field(name="Latencia", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Online ha", value=f"`{horas}h {minutos}m {segundos}s`", inline=False)
        embed.add_field(name="Servidores", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="FARM", value=db_info, inline=False)
        embed.set_footer(text="Iniciado em")
        embed.timestamp = start_time
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SistemaCog(bot))
