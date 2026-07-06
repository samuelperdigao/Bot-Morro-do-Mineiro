"""Entrada principal do bot Discord Morro do Mineiro."""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from cogs.set_views import SetPanelView
from core.config import APPLICATION_ID, TOKEN
from core.extensions import COG_EXTENSIONS
from core.logger import console_handler, get_logger
from services.db_service import db_get_approver_role_ids, db_get_guild_config, init_db
from services.set_service import sync_member_folder_manager_overwrites

logging.basicConfig(level=logging.INFO, handlers=[console_handler])
log = get_logger("bot", "bot.log")


class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, application_id=APPLICATION_ID)
        self.start_time = datetime.now(timezone.utc)

    async def setup_hook(self):
        log.info("setup_hook iniciado...")
        init_db()
        self.add_view(SetPanelView())

        for ext in COG_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Extensao '%s' carregada.", ext)
            except Exception as exc:
                log.error("Falha ao carregar '%s': %s", ext, exc, exc_info=True)

        synced = await self.tree.sync()
        log.info("Comandos sincronizados globalmente: %s", [cmd.name for cmd in synced])

    async def on_ready(self):
        if self.user is None:
            return

        log.info("Bot online: %s (ID: %s) | Servidores: %s", self.user, self.user.id, len(self.guilds))
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="o servidor")
        )

        if not getattr(self, "_member_folder_roles_synced", False):
            self._member_folder_roles_synced = True
            for guild in self.guilds:
                guild_id = str(guild.id)
                cfg = db_get_guild_config(guild_id)
                if not cfg or not cfg["private_category_id"]:
                    continue
                try:
                    result = await sync_member_folder_manager_overwrites(
                        guild,
                        int(cfg["private_category_id"]),
                        db_get_approver_role_ids(guild_id),
                    )
                except Exception as exc:
                    log.error(
                        "Falha ao sincronizar gerentes nas pastas da guild %s: %s",
                        guild.id,
                        exc,
                        exc_info=True,
                    )
                    continue
                log.info(
                    "Pastas sincronizadas na guild %s: canais=%s atualizados=%s "
                    "removidos=%s garantidos=%s falhas=%s",
                    guild.id,
                    result.checked_channels,
                    result.updated_channels,
                    result.removed_overwrites,
                    result.ensured_overwrites,
                    len(result.failed_channels),
                )

        if not getattr(self, "_guilds_limpos", False):
            self._guilds_limpos = True
            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            log.info("Comandos por guild removidos; apenas comandos globais ativos.")


bot = MyBot()


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
