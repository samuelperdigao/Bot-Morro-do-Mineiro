"""Container (Components V2) com o passo a passo para limpar o cache do FiveM.

O discord.py 2.3.2 ainda não tem classes para Components V2, então a mensagem é
enviada como payload bruto (flag IS_COMPONENTS_V2). O botão é um botão comum e
continua sendo tratado por uma View persistente.

Ao carregar o cog, o bot garante que o painel existe no canal: se já houver
uma mensagem dele lá, atualiza no lugar; se não houver, posta e renomeia o canal.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route

from core.logger import get_logger

log = get_logger("cache_fivem", "cache_fivem.log")

CANAL_CACHE_FIVEM_ID = 1565661678857879562
NOME_CANAL = "┃🧹-limpar-cache"
COR_CACHE = 0xFFD700

CUSTOM_ID_COPIAR = "cache_fivem:copiar"
FLAG_COMPONENTS_V2 = 1 << 15

COMANDO_LIMPAR_CACHE = r'''powershell -NoProfile -Command "Get-Process FiveM*,CitizenFX* -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2; $d = Join-Path $env:LOCALAPPDATA 'FiveM\FiveM.app\data'; 'cache\browser','cache\subprocess','server-cache-priv','nui-storage' | ForEach-Object { Remove-Item (Join-Path $d $_) -Recurse -Force -ErrorAction SilentlyContinue }; Get-ChildItem (Join-Path $d 'server-cache') -ErrorAction SilentlyContinue | Where-Object Name -ne 'game' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; 'Cache do FiveM limpo.'"'''


def montar_payload() -> dict:
    """Monta o corpo da mensagem (Container V2) para criar ou editar o painel."""
    return {
        "flags": FLAG_COMPONENTS_V2,
        "components": [
            {
                "type": 17,  # Container
                "accent_color": COR_CACHE,
                "components": [
                    {
                        "type": 10,  # Text Display
                        "content": (
                            "## 🧹 Como limpar o cache do FiveM\n"
                            "Resolve travada, textura bugada e loading infinito."
                        ),
                    },
                    {"type": 14, "divider": True, "spacing": 1},  # Separator
                    {
                        "type": 10,
                        "content": (
                            "### Passo a passo\n"
                            "**1.** Aperte `Win + R`, digite `cmd` e dê Enter "
                            "(use o **CMD**, não o PowerShell)\n"
                            "**2.** Clique em **Copiar comando** abaixo, cole no CMD e dê Enter\n"
                            "**3.** Abra o FiveM. A primeira abertura demora 2–3 min (normal)"
                        ),
                    },
                    {"type": 10, "content": f"```\n{COMANDO_LIMPAR_CACHE}\n```"},
                    {
                        "type": 1,  # Action Row
                        "components": [
                            {
                                "type": 2,  # Button
                                "style": 3,  # Success
                                "label": "Copiar comando",
                                "emoji": {"name": "📋"},
                                "custom_id": CUSTOM_ID_COPIAR,
                            }
                        ],
                    },
                    {"type": 14, "divider": True, "spacing": 1},
                    {
                        "type": 10,
                        "content": (
                            "-# ⚠️ O comando fecha o FiveM sozinho. Salve o que estiver "
                            "fazendo antes. Só Windows, com FiveM instalado no local padrão."
                        ),
                    },
                ],
            }
        ],
    }


class CopiarComandoView(discord.ui.View):
    """View persistente: responde ao botão com o comando pronto para copiar."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Copiar comando",
        emoji="📋",
        style=discord.ButtonStyle.success,
        custom_id=CUSTOM_ID_COPIAR,
    )
    async def copiar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"```\n{COMANDO_LIMPAR_CACHE}\n```\n"
            "Copie o bloco acima (no celular, segure o texto; no PC, use o ícone de copiar "
            "do bloco), cole no **CMD** e dê Enter.",
            ephemeral=True,
        )


def _mensagem_e_painel(msg: dict, bot_id: int) -> bool:
    if int(msg.get("author", {}).get("id", 0)) != bot_id:
        return False
    if not int(msg.get("flags", 0)) & FLAG_COMPONENTS_V2:
        return False
    return CUSTOM_ID_COPIAR in str(msg.get("components", ""))


class CacheFivemCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self._tarefa: asyncio.Task | None = None

    async def cog_load(self):
        self.bot.add_view(CopiarComandoView())
        self._tarefa = asyncio.create_task(self._garantir_painel_no_start())

    async def cog_unload(self):
        if self._tarefa and not self._tarefa.done():
            self._tarefa.cancel()

    async def _garantir_painel_no_start(self):
        try:
            await self.bot.wait_until_ready()
            resultado = await self.garantir_painel()
            log.info("Painel de cache FiveM: %s", resultado)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Falha ao garantir painel de cache FiveM: %s", exc, exc_info=True)

    async def garantir_painel(self) -> str:
        """Edita o painel existente ou cria um novo. Retorna 'editado' ou 'criado'."""
        async with self._lock:
            http = self.bot.http
            canal_id = CANAL_CACHE_FIVEM_ID
            payload = montar_payload()

            recentes = await http.logs_from(canal_id, 50)
            existente = next(
                (m for m in recentes if _mensagem_e_painel(m, self.bot.user.id)), None
            )

            if existente:
                await http.request(
                    Route(
                        "PATCH",
                        "/channels/{channel_id}/messages/{message_id}",
                        channel_id=canal_id,
                        message_id=int(existente["id"]),
                    ),
                    json=payload,
                )
                return "editado"

            await http.request(
                Route("POST", "/channels/{channel_id}/messages", channel_id=canal_id),
                json=payload,
            )
            await self._renomear_canal()
            return "criado"

    async def _renomear_canal(self):
        try:
            canal = self.bot.get_channel(CANAL_CACHE_FIVEM_ID) or await self.bot.fetch_channel(
                CANAL_CACHE_FIVEM_ID
            )
            if canal.name != NOME_CANAL:
                await canal.edit(name=NOME_CANAL, reason="Painel de cache do FiveM")
        except discord.HTTPException as exc:
            log.warning("Não consegui renomear o canal: %s", exc)

    @app_commands.command(
        name="postar_cache_fivem",
        description="Posta ou atualiza o painel de limpeza de cache do FiveM.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def postar_cache_fivem(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            resultado = await self.garantir_painel()
        except discord.HTTPException as exc:
            log.error("Erro ao postar painel de cache FiveM: %s", exc, exc_info=True)
            await interaction.followup.send(
                "❌ Não consegui postar no canal. Confira se o bot pode ver e enviar mensagens nele.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"✅ Painel {resultado} em <#{CANAL_CACHE_FIVEM_ID}>.", ephemeral=True
        )

    @postar_cache_fivem.error
    async def _erro_postar(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa de permissão de gerenciar servidor.", ephemeral=True
            )
        else:
            log.error("Erro em postar_cache_fivem: %s", error, exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CacheFivemCog(bot))
