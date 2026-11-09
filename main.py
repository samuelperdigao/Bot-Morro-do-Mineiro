"""Entrada principal do bot Discord Morro do Mineiro."""

import logging
import sys
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.set_views import SetPanelView
from core.config import APPLICATION_ID, TOKEN
from core.error_reporting import (
    contexto_interacao,
    instalar_handlers_ui,
    report_error,
    responder_erro,
)
from core.extensions import COG_EXTENSIONS
from core.logger import console_handler, get_logger
from services.db_service import init_db

logging.basicConfig(level=logging.INFO, handlers=[console_handler])
log = get_logger("bot", "bot.log")


class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, application_id=APPLICATION_ID)
        self.start_time = datetime.now(timezone.utc)
        self.extensoes_com_falha: list[str] = []
        self.tree.on_error = self._on_app_command_error

    async def setup_hook(self):
        log.info("setup_hook iniciado...")
        init_db()
        instalar_handlers_ui(self)
        self.add_view(SetPanelView())

        for ext in COG_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Extensao '%s' carregada.", ext)
            except Exception as exc:
                log.error("Falha ao carregar '%s': %s", ext, exc, exc_info=True)
                self.extensoes_com_falha.append(ext)

        # Se alguma extensao falhou, NAO sincroniza: o sync global apagaria os
        # comandos dela em todos os servidores. Mantem os comandos ja registrados.
        if self.extensoes_com_falha:
            log.error(
                "Sync de comandos pulado: extensoes com falha %s.", self.extensoes_com_falha
            )
            return

        synced = await self.tree.sync()
        log.info("Comandos sincronizados globalmente: %s", [cmd.name for cmd in synced])

    async def on_ready(self):
        if self.user is None:
            return

        log.info("Bot online: %s (ID: %s) | Servidores: %s", self.user, self.user.id, len(self.guilds))
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="o servidor")
        )

        if self.extensoes_com_falha and not getattr(self, "_falha_reportada", False):
            self._falha_reportada = True
            await report_error(
                self,
                "inicializacao",
                RuntimeError(f"Extensoes nao carregadas: {', '.join(self.extensoes_com_falha)}"),
                "O sync de comandos foi pulado para nao apagar comandos existentes.",
            )

        if not getattr(self, "_guilds_limpos", False):
            self._guilds_limpos = True
            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            log.info("Comandos por guild removidos; apenas comandos globais ativos.")

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handler global de slash commands.

        O discord.py chama este handler mesmo quando o comando tem o seu
        proprio .error; por isso so responde se ninguem respondeu ainda.
        """
        if isinstance(error, app_commands.MissingPermissions):
            await self._responder_se_pendente(interaction, "❌ Você não tem permissão para usar este comando.")
            return
        if isinstance(error, app_commands.BotMissingPermissions):
            await self._responder_se_pendente(interaction, "❌ O bot não tem as permissões necessárias para isso.")
            return
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._responder_se_pendente(
                interaction, f"⏳ Aguarde {error.retry_after:.0f}s para usar este comando de novo."
            )
            return
        if isinstance(error, app_commands.CheckFailure):
            await self._responder_se_pendente(interaction, "❌ Você não pode usar este comando aqui.")
            return

        original = getattr(error, "original", error)
        await report_error(self, f"/{interaction.command.qualified_name if interaction.command else '?'}",
                           original, contexto_interacao(interaction))
        await self._responder_se_pendente(interaction, None)

    @staticmethod
    async def _responder_se_pendente(interaction: discord.Interaction, mensagem: str | None) -> None:
        if interaction.response.is_done():
            return
        if mensagem is None:
            await responder_erro(interaction)
        else:
            await responder_erro(interaction, mensagem)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Erros nao tratados em eventos (on_member_remove, on_message, etc.)."""
        error = sys.exc_info()[1]
        if error is None:
            log.error("Erro desconhecido no evento %s", event_method)
            return
        await report_error(self, f"evento {event_method}", error)


bot = MyBot()


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
