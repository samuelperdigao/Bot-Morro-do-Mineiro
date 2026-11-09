"""
Painel fixo de fabricacao de coletes (Components V2).

/colete publica o painel no canal em que o comando for executado.

Fluxo:
1. Painel fixo: atalhos de quantidade (1, 5, 10, 50) ou "Outra quantidade" (Modal).
2. Passo efemero com stepper (-10, -1, [qtd], +1, +10) que recalcula materiais e custo.
3. Confirmacao -> espera o print no canal -> registra no banco -> credita no
   Bau da Gerencia -> posta o log.

Se o credito no Bau falhar, a fabricacao fica pendente e uma tarefa tenta de
novo a cada minuto, sem duplicar a entrada (operation_id unico).

As interacoes sao roteadas por custom_id sem estado ("colete:acao:valor"),
entao os botoes continuam funcionando depois de reiniciar o bot. Nao ha limite
de quantidade por fabricacao.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import components_v2 as v2
from core.logger import get_logger
from core.error_reporting import proteger_loop
from features.farm.catalog import MATERIAIS_POR_COLETE
from infrastructure.repositories.bau import BauRepository, DuplicateOperationError, OperationResult
from services.bau_service import bau_service
from services.db_service import (
    db_get_fabricacoes_colete_pendentes,
    db_get_painel_colete,
    db_get_system_config,
    db_marcar_fabricacao_colete_sincronizada,
    db_registrar_fabricacao_colete,
    db_resumo_coletes,
    db_set_guild_config,
)

log = get_logger("colete", "colete.log")

CUSTO_POR_COLETE = 1000
ATALHOS = (1, 5, 10, 50)
PRINT_TIMEOUT_SECONDS = 180.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
LOG_FABRICACAO_CHANNEL_ID = 1506880362633236630
COR_DOURADO = 0xFFD700
COR_VERMELHO = 0xED4245
COR_VERDE = 0x57F287

PREFIXO = "colete"
CANCELADO = "cancelado"


# ── Regras de negocio ─────────────────────────────────────────────────────────

def calcular_fabricacao(quantidade: int) -> dict[str, int]:
    if not isinstance(quantidade, int) or quantidade < 1:
        raise ValueError("A quantidade deve ser um inteiro maior que zero.")
    materiais = {
        nome: valor * quantidade
        for nome, valor in MATERIAIS_POR_COLETE.items()
    }
    materiais["custo"] = CUSTO_POR_COLETE * quantidade
    return materiais


def interpretar_quantidade(valor: str) -> int | None:
    """Converte o texto digitado em quantidade valida. Aceita '1.000' e '1 000'."""
    limpo = valor.strip().replace(".", "").replace(",", "").replace(" ", "")
    if not limpo.isdigit():
        return None
    quantidade = int(limpo)
    return quantidade if quantidade >= 1 else None


def _fmt_money(valor: int) -> str:
    return "$" + f"{valor:,}".replace(",", ".")


def _fmt_num(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def _nome_colete(quantidade: int) -> str:
    return "colete" if quantidade == 1 else "coletes"


def _qtd_texto(quantidade: int) -> str:
    return f"{_fmt_num(quantidade)} {_nome_colete(quantidade)}"


def sincronizar_fabricacao_no_bau(
    fabricacao: dict,
    repository: BauRepository = bau_service.repository,
) -> OperationResult | None:
    """Credita uma fabricacao pendente uma unica vez no estoque do bau."""
    try:
        result = repository.apply_operation(
            "entrada",
            [("Colete", int(fabricacao["quantidade"]))],
            str(fabricacao["user_id"]),
            str(fabricacao["user_name"]),
            "fabricacao_colete",
            operation_id=str(fabricacao["bau_operation_id"]),
        )
    except DuplicateOperationError:
        result = None

    db_marcar_fabricacao_colete_sincronizada(int(fabricacao["id"]))
    return result


def _texto_estoque_bau(
    bau_sincronizado: bool, operacao_bau: OperationResult | None
) -> str:
    if operacao_bau is not None and operacao_bau.lines:
        linha = operacao_bau.lines[0]
        return (
            f"`{_fmt_num(linha.estoque_antes)}` → `{_fmt_num(linha.estoque_depois)}` "
            f"(+{_fmt_num(linha.quantidade)})"
        )
    if bau_sincronizado:
        return "Sincronizado anteriormente, sem duplicar a entrada."
    return "Pendente de sincronização automática."


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    if content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _linhas_materiais(materiais: dict[str, int], com_custo: bool) -> str:
    fmt = _fmt_num
    linha_1 = (
        f"Ferro `{fmt(materiais['ferro'])}` · "
        f"Plástico `{fmt(materiais['plastico'])}` · "
        f"Tecido `{fmt(materiais['tecido'])}`"
    )
    linha_2 = (
        f"Alumínio `{fmt(materiais['aluminio'])}` · "
        f"Borracha `{fmt(materiais['borracha'])}`"
    )
    if com_custo:
        linha_2 += f" · Custo `{_fmt_money(materiais['custo'])}`"
    return f"{linha_1}\n{linha_2}"


# ── Montagem das mensagens (Components V2) ────────────────────────────────────

def montar_painel(resumo: dict[str, int] | None = None) -> list[dict[str, Any]]:
    por_colete = calcular_fabricacao(1)
    filhos: list[dict[str, Any]] = [
        v2.texto(
            "## Fabricação de coletes\n"
            "Escolha a quantidade, confirme e envie o print da fabricação."
        ),
        v2.separador(),
        v2.texto(f"**Por colete**\n{_linhas_materiais(por_colete, com_custo=True)}"),
        v2.separador(),
        v2.linha(
            [
                v2.botao(str(q), f"{PREFIXO}:q:{q}", v2.PRIMARY)
                for q in ATALHOS
            ]
            + [v2.botao("Outra quantidade", f"{PREFIXO}:outra", v2.SECONDARY)]
        ),
    ]
    if resumo is not None:
        filhos.append(v2.separador())
        filhos.append(
            v2.texto(
                f"-# Hoje: **{_fmt_num(resumo['hoje_qtd'])}** · "
                f"Semana: **{_fmt_num(resumo['semana_qtd'])}** coletes · "
                f"Gasto da semana: **{_fmt_money(resumo['semana_custo'])}**"
            )
        )
    return [v2.container(filhos, COR_DOURADO)]


def montar_passo_quantidade(quantidade: int) -> list[dict[str, Any]]:
    materiais = calcular_fabricacao(quantidade)
    stepper = v2.linha(
        [
            v2.botao("-10", f"{PREFIXO}:step:{quantidade}:-10"),
            v2.botao("-1", f"{PREFIXO}:step:{quantidade}:-1"),
            v2.botao(_fmt_num(quantidade), f"{PREFIXO}:edit:{quantidade}", v2.PRIMARY),
            v2.botao("+1", f"{PREFIXO}:step:{quantidade}:1"),
            v2.botao("+10", f"{PREFIXO}:step:{quantidade}:10"),
        ]
    )
    return [
        v2.container(
            [
                v2.texto(
                    f"## Fabricar {_qtd_texto(quantidade)}\n"
                    "Ajuste a quantidade ou toque no número para digitar."
                ),
                stepper,
                v2.separador(),
                v2.texto(
                    f"**Materiais**\n{_linhas_materiais(materiais, com_custo=False)}\n\n"
                    f"**Custo total** `{_fmt_money(materiais['custo'])}`"
                ),
                v2.separador(),
                v2.linha(
                    [
                        v2.botao(
                            "Confirmar e enviar print",
                            f"{PREFIXO}:ok:{quantidade}",
                            v2.SUCCESS,
                        ),
                        v2.botao("Cancelar", f"{PREFIXO}:cancel", v2.DANGER),
                    ]
                ),
            ],
            COR_DOURADO,
        )
    ]


def montar_aguardando(quantidade: int, prazo_unix: int) -> list[dict[str, Any]]:
    return [
        v2.container(
            [
                v2.texto(
                    "## Aguardando o print\n"
                    f"Envie uma imagem **neste canal** <t:{prazo_unix}:R> para registrar "
                    f"**{_qtd_texto(quantidade)}**."
                ),
                v2.texto(
                    "-# A fabricação só é registrada depois do print. "
                    "Formatos: PNG, JPG, JPEG, WEBP ou GIF."
                ),
                v2.linha([v2.botao("Cancelar", f"{PREFIXO}:abort", v2.DANGER)]),
            ],
            COR_DOURADO,
        )
    ]


def montar_cancelado() -> list[dict[str, Any]]:
    return [
        v2.container(
            [v2.texto("## Fabricação cancelada\nNada foi registrado.")],
            COR_VERMELHO,
        )
    ]


def montar_timeout(quantidade: int) -> list[dict[str, Any]]:
    return [
        v2.container(
            [
                v2.texto(
                    "## Tempo esgotado\n"
                    f"Nenhum print chegou para **{_qtd_texto(quantidade)}**. "
                    "Nada foi registrado."
                )
            ],
            COR_VERMELHO,
        )
    ]


def montar_erro_print() -> list[dict[str, Any]]:
    return [
        v2.container(
            [
                v2.texto(
                    "## Não consegui ler o print\n"
                    "A imagem não pôde ser baixada. Nada foi registrado, "
                    "tente fabricar de novo."
                )
            ],
            COR_VERMELHO,
        )
    ]


def montar_sucesso(
    fabricacao_id: int,
    quantidade: int,
    custo: int,
    canal_log_id: int | None,
    bau_sincronizado: bool = True,
) -> list[dict[str, Any]]:
    detalhe_bau = (
        "Quantidade adicionada ao Baú da Gerência."
        if bau_sincronizado
        else "A atualização do Baú ficou pendente e será tentada novamente."
    )
    detalhe_log = (
        f"Log com o print enviado em <#{canal_log_id}>."
        if canal_log_id
        else "Salvo no banco, mas não consegui enviar o log."
    )
    return [
        v2.container(
            [
                v2.texto(
                    f"## Fabricação #{fabricacao_id} registrada\n"
                    f"**{_qtd_texto(quantidade)}** · `{_fmt_money(custo)}`"
                ),
                v2.texto(f"-# {detalhe_bau}\n-# {detalhe_log}"),
            ],
            COR_VERDE if canal_log_id and bau_sincronizado else COR_DOURADO,
        )
    ]


def montar_log(
    *,
    fabricacao_id: int,
    membro_id: int,
    avatar_url: str,
    quantidade: int,
    materiais: dict[str, int],
    canal_id: int,
    nome_arquivo: str,
    quando_unix: int,
    estoque_bau: str | None = None,
) -> list[dict[str, Any]]:
    materiais_texto = f"**Materiais**\n{_linhas_materiais(materiais, com_custo=False)}"
    if estoque_bau:
        materiais_texto += f"\n\n**Estoque do Baú** {estoque_bau}"
    return [
        v2.container(
            [
                v2.secao(
                    [
                        f"## Fabricação #{fabricacao_id}\n"
                        f"**Membro:** <@{membro_id}>\n"
                        f"**Quantidade:** `{_qtd_texto(quantidade)}`\n"
                        f"**Gasto total:** `{_fmt_money(materiais['custo'])}`"
                    ],
                    avatar_url,
                ),
                v2.texto(materiais_texto),
                v2.galeria([f"attachment://{nome_arquivo}"]),
                v2.separador(),
                v2.texto(
                    f"-# <t:{quando_unix}:f> · <#{canal_id}> · "
                    "Morro do Mineiro - Fabricação de Coletes"
                ),
            ],
            COR_DOURADO,
        )
    ]


# ── Modal ─────────────────────────────────────────────────────────────────────

class QuantidadeModal(discord.ui.Modal):
    """Pede uma quantidade livre. editar=True atualiza o passo ja aberto."""

    def __init__(self, editar: bool, padrao: int | None = None):
        super().__init__(title="Quantidade de coletes")
        self.editar = editar
        self.campo = discord.ui.TextInput(
            label="Quantos coletes?",
            placeholder="Ex.: 25",
            default=str(padrao) if padrao else None,
            min_length=1,
            max_length=7,
            required=True,
        )
        self.add_item(self.campo)

    async def on_submit(self, interaction: discord.Interaction):
        quantidade = interpretar_quantidade(self.campo.value)
        if quantidade is None:
            await interaction.response.send_message(
                "Digite um número inteiro maior que zero.", ephemeral=True
            )
            return
        await v2.responder(
            interaction, montar_passo_quantidade(quantidade), atualizar=self.editar
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no modal de quantidade: %s", error, exc_info=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class ColeteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id) -> Event que cancela a espera do print
        self._pendentes: dict[tuple[int, int], asyncio.Event] = {}
        self._bau_sync_lock = asyncio.Lock()

    async def cog_load(self):
        proteger_loop(self._bau_sync_task, "colete_sync_bau", lambda: self.bot)
        self._bau_sync_task.start()

    async def cog_unload(self):
        self._bau_sync_task.cancel()

    # Sincronizacao com o Bau ------------------------------------------------

    async def sincronizar_fabricacao(
        self,
        fabricacao: dict,
    ) -> tuple[bool, OperationResult | None]:
        async with self._bau_sync_lock:
            try:
                operacao = sincronizar_fabricacao_no_bau(fabricacao)
            except Exception:
                log.error(
                    "Falha ao sincronizar fabricacao %s com o bau",
                    fabricacao.get("id"),
                    exc_info=True,
                )
                return False, None

        bau_cog = self.bot.get_cog("BauCog")
        if bau_cog is not None:
            await bau_cog.atualizar_painel()
        return True, operacao

    @tasks.loop(minutes=1)
    async def _bau_sync_task(self):
        try:
            pendentes = db_get_fabricacoes_colete_pendentes()
        except Exception:
            log.error("Falha ao buscar fabricacoes pendentes", exc_info=True)
            return
        for fabricacao in pendentes:
            sincronizado, _ = await self.sincronizar_fabricacao(fabricacao)
            if not sincronizado:
                break

    @_bau_sync_task.before_loop
    async def _antes_de_sincronizar_bau(self):
        await self.bot.wait_until_ready()

    # Roteamento -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type is not discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith(f"{PREFIXO}:") or interaction.guild_id is None:
            return
        try:
            await self._rotear(interaction, custom_id.split(":"))
        except Exception as exc:
            log.error("Erro ao tratar %s: %s", custom_id, exc, exc_info=True)
            try:
                await interaction.response.send_message(
                    "Ocorreu um erro. Tente novamente.", ephemeral=True
                )
            except discord.HTTPException:
                pass

    async def _rotear(self, interaction: discord.Interaction, partes: list[str]):
        acao = partes[1] if len(partes) > 1 else ""

        if acao == "q":
            quantidade = int(partes[2])
            if quantidade >= 1:
                await v2.responder(interaction, montar_passo_quantidade(quantidade))
        elif acao == "outra":
            await interaction.response.send_modal(QuantidadeModal(editar=False))
        elif acao == "edit":
            await interaction.response.send_modal(
                QuantidadeModal(editar=True, padrao=int(partes[2]))
            )
        elif acao == "step":
            quantidade = max(1, int(partes[2]) + int(partes[3]))
            await v2.responder(
                interaction, montar_passo_quantidade(quantidade), atualizar=True
            )
        elif acao == "cancel":
            await v2.responder(interaction, montar_cancelado(), atualizar=True)
        elif acao == "abort":
            evento = self._pendentes.get((interaction.guild_id, interaction.user.id))
            if evento:
                evento.set()
            await v2.responder(interaction, montar_cancelado(), atualizar=True)
        elif acao == "ok":
            await self._confirmar(interaction, int(partes[2]))
        elif acao in ("select", "faixa"):
            # custom_id dos paineis anteriores (select de 1 a 10 e faixas ate 100)
            await interaction.response.send_message(
                "Esse painel está desatualizado. Peça para a liderança postar "
                "o painel novamente com `/colete`.",
                ephemeral=True,
            )

    # Fabricacao -------------------------------------------------------------

    async def _confirmar(self, interaction: discord.Interaction, quantidade: int):
        if quantidade < 1:
            return
        chave = (interaction.guild_id, interaction.user.id)
        if chave in self._pendentes:
            await interaction.response.send_message(
                "Você já tem uma fabricação aguardando print. "
                "Envie o print ou cancele a anterior.",
                ephemeral=True,
            )
            return

        cancelar = asyncio.Event()
        self._pendentes[chave] = cancelar
        try:
            prazo = int(time.time() + PRINT_TIMEOUT_SECONDS)
            await v2.responder(
                interaction, montar_aguardando(quantidade, prazo), atualizar=True
            )
            resultado = await self._aguardar_print(interaction, cancelar)
            if resultado == CANCELADO:
                return
            if resultado is None:
                await v2.editar_original(interaction, montar_timeout(quantidade))
                return
            await self._finalizar(interaction, quantidade, resultado)
        finally:
            self._pendentes.pop(chave, None)

    async def _aguardar_print(
        self, interaction: discord.Interaction, cancelar: asyncio.Event
    ) -> discord.Message | str | None:
        def check(message: discord.Message) -> bool:
            return (
                message.author.id == interaction.user.id
                and message.channel.id == interaction.channel_id
                and any(_is_image_attachment(att) for att in message.attachments)
            )

        espera_print = asyncio.create_task(
            self.bot.wait_for("message", check=check, timeout=PRINT_TIMEOUT_SECONDS)
        )
        espera_cancel = asyncio.create_task(cancelar.wait())
        feitas, pendentes = await asyncio.wait(
            {espera_print, espera_cancel}, return_when=asyncio.FIRST_COMPLETED
        )
        for tarefa in pendentes:
            tarefa.cancel()
        if espera_cancel in feitas:
            return CANCELADO
        try:
            return espera_print.result()
        except asyncio.TimeoutError:
            return None

    async def _finalizar(
        self,
        interaction: discord.Interaction,
        quantidade: int,
        mensagem: discord.Message,
    ):
        anexo = next(a for a in mensagem.attachments if _is_image_attachment(a))
        extensao = os.path.splitext(anexo.filename)[1].lower()
        if extensao not in IMAGE_EXTENSIONS:
            extensao = ".png"
        nome_arquivo = f"print{extensao}"

        try:
            arquivo = await anexo.to_file(filename=nome_arquivo, use_cached=True)
        except Exception:
            log.error("Erro ao baixar print de fabricacao de colete", exc_info=True)
            await v2.editar_original(interaction, montar_erro_print())
            return

        try:
            await mensagem.delete()
        except Exception:
            pass

        materiais = calcular_fabricacao(quantidade)
        fabricacao = db_registrar_fabricacao_colete(
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            quantidade=quantidade,
            ferro=materiais["ferro"],
            plastico=materiais["plastico"],
            tecido=materiais["tecido"],
            aluminio=materiais["aluminio"],
            borracha=materiais["borracha"],
            custo=materiais["custo"],
        )
        fabricacao_id = fabricacao["id"]
        bau_sincronizado, operacao_bau = await self.sincronizar_fabricacao(fabricacao)
        log.info(
            "Fabricacao #%s registrada: user=%s qtd=%s custo=%s print=%s bau=%s",
            fabricacao_id,
            interaction.user.id,
            quantidade,
            materiais["custo"],
            anexo.filename,
            "sincronizado" if bau_sincronizado else "pendente",
        )

        componentes_log = montar_log(
            fabricacao_id=fabricacao_id,
            membro_id=interaction.user.id,
            avatar_url=interaction.user.display_avatar.url,
            quantidade=quantidade,
            materiais=materiais,
            canal_id=interaction.channel_id,
            nome_arquivo=arquivo.filename,
            quando_unix=int(time.time()),
            estoque_bau=_texto_estoque_bau(bau_sincronizado, operacao_bau),
        )
        canal_log_id = await self._postar_log(
            interaction.guild_id, componentes_log, arquivo
        )

        try:
            await v2.editar_original(
                interaction,
                montar_sucesso(
                    fabricacao_id,
                    quantidade,
                    materiais["custo"],
                    canal_log_id,
                    bau_sincronizado,
                ),
            )
        except discord.HTTPException as exc:
            log.warning("Nao consegui editar a resposta de sucesso: %s", exc)

        await self._atualizar_painel(interaction.guild_id)

    async def _postar_log(
        self,
        guild_id: int,
        componentes: list[dict[str, Any]],
        arquivo: discord.File,
    ) -> int | None:
        """Posta o log no canal configurado e, se falhar, no canal de fallback."""
        canais: list[int] = []
        config = db_get_system_config(str(guild_id), "colete")
        if config and config["canal_log_id"]:
            canais.append(int(config["canal_log_id"]))
        if LOG_FABRICACAO_CHANNEL_ID not in canais:
            canais.append(LOG_FABRICACAO_CHANNEL_ID)

        for canal_id in canais:
            try:
                await v2.enviar_canal(self.bot.http, canal_id, componentes, [arquivo])
                return canal_id
            except discord.HTTPException as exc:
                log.error("Erro ao enviar log de colete (canal=%s): %s", canal_id, exc)
        return None

    async def _atualizar_painel(self, guild_id: int):
        """Atualiza a linha Hoje/Semana do painel fixo apos cada registro."""
        canal_id, mensagem_id = db_get_painel_colete(str(guild_id))
        if not (canal_id and mensagem_id):
            return
        try:
            await v2.editar_mensagem(
                self.bot.http,
                int(canal_id),
                int(mensagem_id),
                montar_painel(db_resumo_coletes(str(guild_id))),
            )
        except discord.HTTPException as exc:
            log.warning("Nao consegui atualizar o painel de coletes: %s", exc)

    # Comando ----------------------------------------------------------------

    @app_commands.command(
        name="colete",
        description="Posta o painel de fabricação de coletes neste canal.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def colete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        canal = interaction.channel

        old_channel_id, old_message_id = db_get_painel_colete(guild_id)
        old_message = None
        if old_channel_id and old_message_id:
            old_channel = interaction.guild.get_channel(int(old_channel_id))
            if old_channel is None:
                try:
                    old_channel = await interaction.guild.fetch_channel(
                        int(old_channel_id)
                    )
                except Exception:
                    old_channel = None
            if old_channel is not None:
                try:
                    old_message = await old_channel.fetch_message(int(old_message_id))
                except Exception:
                    old_message = None

        # O painel anterior so e removido depois que o novo foi postado e salvo.
        mensagem = await v2.enviar_canal(
            self.bot.http,
            canal.id,
            montar_painel(db_resumo_coletes(guild_id)),
        )
        try:
            db_set_guild_config(
                guild_id,
                painel_colete_channel_id=str(canal.id),
                painel_colete_message_id=str(mensagem["id"]),
            )
        except Exception:
            try:
                await self.bot.http.delete_message(canal.id, int(mensagem["id"]))
            except Exception:
                pass
            raise

        if old_message is not None:
            try:
                await old_message.delete()
            except Exception:
                log.warning(
                    "Novo painel publicado, mas o painel anterior nao foi removido: %s",
                    old_message_id,
                    exc_info=True,
                )
        await interaction.followup.send(
            f"Painel de coletes postado em {canal.mention}!",
            ephemeral=True,
        )
        log.info(
            "Painel de coletes postado: message_id=%s (guild %s)",
            mensagem["id"],
            guild_id,
        )

    @colete.error
    async def colete_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            mensagem = "Sem permissao para usar este comando."
        else:
            original = getattr(error, "original", error)
            if isinstance(original, discord.HTTPException):
                log.error(
                    "Erro HTTP no /colete: status=%s code=%s resposta=%s",
                    original.status,
                    original.code,
                    original.text,
                    exc_info=True,
                )
            else:
                log.error("Erro no /colete: %s", error, exc_info=True)
            mensagem = "Ocorreu um erro ao publicar o painel."

        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ColeteCog(bot))
    log.info("ColeteCog carregado.")
