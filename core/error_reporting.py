"""
core/error_reporting.py - Tratamento central de erros do bot.

- report_error: registra no log e avisa num canal de erros (opcional).
- proteger_loop: impede que uma task agendada morra para sempre após uma
  exceção; registra, avisa e reinicia a task depois de um intervalo.
- instalar_handlers_ui: tratamento padrão de erros para Views e Modals que
  não definem o próprio on_error (o usuário recebe uma resposta em vez de
  "Esta interação falhou").

O canal de erros é definido pela variável de ambiente CANAL_ERROS_ID.
Sem ela, os erros vão apenas para o arquivo de log.
"""

from __future__ import annotations

import asyncio
import time
import traceback

import discord
from discord.ext import tasks

from core.config import CANAL_ERROS_ID
from core.logger import get_logger

log = get_logger("erros", "bot.log")

# Evita inundar o canal com o mesmo erro: no máximo 1 aviso por assinatura
# a cada JANELA_AVISO_SEGUNDOS.
JANELA_AVISO_SEGUNDOS = 600
_ultimos_avisos: dict[str, float] = {}

MENSAGEM_ERRO_USUARIO = "❌ Ocorreu um erro inesperado. A liderança já foi avisada."


def _assinatura(origem: str, error: BaseException) -> str:
    return f"{origem}|{type(error).__name__}|{str(error)[:120]}"


def _deve_avisar(assinatura: str, agora: float | None = None) -> bool:
    agora = time.monotonic() if agora is None else agora
    ultimo = _ultimos_avisos.get(assinatura)
    if ultimo is not None and agora - ultimo < JANELA_AVISO_SEGUNDOS:
        return False
    _ultimos_avisos[assinatura] = agora
    return True


def _resumo_traceback(error: BaseException, limite: int = 1500) -> str:
    texto = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    if len(texto) > limite:
        texto = "…" + texto[-limite:]
    return texto


async def report_error(
    client: discord.Client | None,
    origem: str,
    error: BaseException,
    contexto: str | None = None,
) -> None:
    """Loga o erro e, se configurado, envia um resumo para o canal de erros."""
    log.error("Erro em %s%s", origem, f" ({contexto})" if contexto else "", exc_info=error)

    if client is None or not CANAL_ERROS_ID:
        return
    if not _deve_avisar(_assinatura(origem, error)):
        return

    try:
        canal = client.get_channel(CANAL_ERROS_ID)
        if canal is None:
            canal = await client.fetch_channel(CANAL_ERROS_ID)
        embed = discord.Embed(
            title=f"⚠️ Erro em {origem}"[:256],
            description=f"```py\n{_resumo_traceback(error)}\n```",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow(),
        )
        if contexto:
            embed.add_field(name="Contexto", value=contexto[:1024], inline=False)
        embed.set_footer(text="Morro do Mineiro — Monitoramento")
        await canal.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        log.error("Falha ao enviar aviso de erro para o canal %s.", CANAL_ERROS_ID, exc_info=True)


def contexto_interacao(interaction: discord.Interaction) -> str:
    comando = interaction.command.qualified_name if interaction.command else None
    custom_id = (interaction.data or {}).get("custom_id") if interaction.data else None
    partes = [f"Usuário: {interaction.user} (`{interaction.user.id}`)"]
    if comando:
        partes.append(f"Comando: /{comando}")
    if custom_id:
        partes.append(f"Componente: `{custom_id}`")
    if interaction.channel_id:
        partes.append(f"Canal: <#{interaction.channel_id}>")
    return "\n".join(partes)


async def responder_erro(interaction: discord.Interaction, mensagem: str = MENSAGEM_ERRO_USUARIO) -> None:
    """Responde ao usuário sem lançar exceção, haja ou não resposta anterior."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)
    except Exception:
        log.debug("Não foi possível responder ao usuário sobre o erro.", exc_info=True)


def proteger_loop(
    loop: tasks.Loop,
    nome: str,
    client_getter=None,
    atraso_reinicio: float = 60.0,
) -> None:
    """Registra um handler de erro que avisa e reinicia a task.

    `loop` deve ser a instância ligada ao cog (ex.: self._minha_task).
    `client_getter` é uma função sem argumentos que devolve o bot.
    """

    async def _on_error(*args) -> None:
        error = args[-1]
        client = client_getter() if client_getter else None
        await report_error(client, f"task {nome}", error, "A task será reiniciada automaticamente.")

        async def _reiniciar() -> None:
            await asyncio.sleep(atraso_reinicio)
            if not loop.is_running():
                try:
                    loop.start()
                    log.info("Task %s reiniciada após erro.", nome)
                except RuntimeError:
                    log.warning("Task %s já estava em execução.", nome)

        asyncio.get_running_loop().create_task(_reiniciar())

    loop.error(_on_error)


def instalar_handlers_ui(client: discord.Client) -> None:
    """Define on_error padrão para Views e Modals que não têm o seu."""

    async def _view_on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_error(
            client,
            f"view {type(self).__name__}",
            error,
            contexto_interacao(interaction),
        )
        await responder_erro(interaction)

    async def _modal_on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(
            client,
            f"modal {type(self).__name__}",
            error,
            contexto_interacao(interaction),
        )
        await responder_erro(interaction)

    discord.ui.View.on_error = _view_on_error  # type: ignore[method-assign]
    discord.ui.Modal.on_error = _modal_on_error  # type: ignore[method-assign]
