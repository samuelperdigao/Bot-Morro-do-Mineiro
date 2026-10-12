"""
Painel fixo de fabricacao de coletes.

/colete publica o painel no canal em que o comando for executado.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.bau import repo as bau_repo
from cogs.bau_core import BauRepository, DuplicateOperationError, OperationResult
from core.logger import get_logger
from services.db_service import (
    db_get_fabricacoes_colete_pendentes,
    db_get_painel_colete,
    db_marcar_fabricacao_colete_sincronizada,
    db_registrar_fabricacao_colete,
    db_set_guild_config,
)
from services.log_service import send_log

log = get_logger("colete", "colete.log")

MAX_QUANTIDADE = 100
QUANTIDADES = range(1, MAX_QUANTIDADE + 1)
QUANTIDADES_POR_SELETOR = 25
FAIXAS_QUANTIDADE = tuple(
    (
        inicio,
        min(inicio + QUANTIDADES_POR_SELETOR - 1, MAX_QUANTIDADE),
    )
    for inicio in range(1, MAX_QUANTIDADE + 1, QUANTIDADES_POR_SELETOR)
)
MATERIAIS_POR_COLETE = {
    "ferro": 20,
    "plastico": 10,
    "tecido": 1,
    "aluminio": 20,
    "borracha": 10,
}
CUSTO_POR_COLETE = 1000
PRINT_TIMEOUT_SECONDS = 180.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
LOG_FABRICACAO_CHANNEL_ID = 1506880362633236630


def calcular_fabricacao(quantidade: int) -> dict[str, int]:
    if quantidade not in QUANTIDADES:
        raise ValueError(f"A quantidade deve estar entre 1 e {MAX_QUANTIDADE}.")
    materiais = {
        nome: valor * quantidade
        for nome, valor in MATERIAIS_POR_COLETE.items()
    }
    materiais["custo"] = CUSTO_POR_COLETE * quantidade
    return materiais


def _fmt_money(valor: int) -> str:
    return f"${valor:,.0f}"


def _nome_colete(quantidade: int) -> str:
    return "colete" if quantidade == 1 else "coletes"


def _criar_opcao_quantidade(quantidade: int) -> discord.SelectOption:
    materiais = calcular_fabricacao(quantidade)
    nome = _nome_colete(quantidade)
    return discord.SelectOption(
        label=(
            f"{quantidade} {nome.title()} - "
            f"{_fmt_money(materiais['custo'])}"
        ),
        description=(
            f"Ferro: {materiais['ferro']} | Plastico: {materiais['plastico']} "
            f"| Tecido: {materiais['tecido']} | Aluminio: {materiais['aluminio']} "
            f"| Borracha: {materiais['borracha']}"
        ),
        value=str(quantidade),
    )


def sincronizar_fabricacao_no_bau(
    fabricacao: dict,
    repository: BauRepository = bau_repo,
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


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    if content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _criar_embed_painel() -> discord.Embed:
    embed = discord.Embed(
        title="FABRICACAO DE COLETES",
        description=(
            "Selecione abaixo a quantidade que deseja fabricar.\n"
            f"O limite e de **{MAX_QUANTIDADE} coletes por vez**.\n\n"
            "**Materiais por colete:**\n"
            "Ferro: `20` | Plastico: `10` | Tecido: `1`\n"
            "Aluminio: `20` | Borracha: `10`\n"
            f"Custo: `{_fmt_money(CUSTO_POR_COLETE)}`"
        ),
        color=0x34495E,
    )
    embed.set_footer(text="Morro do Mineiro")
    return embed


def _criar_embed_confirmacao(quantidade: int, materiais: dict[str, int]) -> discord.Embed:
    nome = _nome_colete(quantidade)
    embed = discord.Embed(
        title=f"Fabricacao - {quantidade} {nome.title()}",
        description=(
            "Confira os materiais necessarios e confirme a fabricacao.\n"
            "Depois da confirmacao, voce precisara enviar o print da fabricacao."
        ),
        color=0xF1C40F,
    )
    embed.add_field(name="Ferro", value=str(materiais["ferro"]), inline=True)
    embed.add_field(name="Plastico", value=str(materiais["plastico"]), inline=True)
    embed.add_field(name="Tecido", value=str(materiais["tecido"]), inline=True)
    embed.add_field(name="Aluminio", value=str(materiais["aluminio"]), inline=True)
    embed.add_field(name="Borracha", value=str(materiais["borracha"]), inline=True)
    embed.add_field(name="Custo", value=_fmt_money(materiais["custo"]), inline=True)
    embed.set_footer(text="Confirme ou cancele abaixo.")
    return embed


def _criar_embed_aguardando_print(quantidade: int) -> discord.Embed:
    nome = _nome_colete(quantidade)
    embed = discord.Embed(
        title="Aguardando print da fabricacao",
        description=(
            f"Envie uma imagem neste canal em ate **{int(PRINT_TIMEOUT_SECONDS / 60)} minutos** "
            f"para confirmar a fabricacao de **{quantidade} {nome}**.\n\n"
            "A fabricacao so sera registrada depois que o print for recebido."
        ),
        color=0xF1C40F,
    )
    embed.set_footer(text="Formatos aceitos: PNG, JPG, JPEG, WEBP ou GIF.")
    return embed


def _criar_embed_timeout(quantidade: int) -> discord.Embed:
    nome = _nome_colete(quantidade)
    return discord.Embed(
        title="Tempo esgotado",
        description=(
            f"Nenhum print foi recebido para a fabricacao de **{quantidade} {nome}**. "
            "Nada foi registrado."
        ),
        color=discord.Color.red(),
    )


def _criar_embed_sucesso(
    quantidade: int,
    log_enviado: bool,
    bau_sincronizado: bool,
) -> discord.Embed:
    nome = _nome_colete(quantidade)
    registrado = "registrado" if quantidade == 1 else "registrados"
    detalhe_log = (
        "O log com o print foi enviado ao canal de fabricacao."
        if log_enviado
        else "A fabricacao foi salva, mas nao foi possivel enviar o log."
    )
    detalhe_bau = (
        "A quantidade foi adicionada ao Bau da Gerencia."
        if bau_sincronizado
        else "A atualizacao do Bau ficou pendente e sera tentada novamente."
    )
    return discord.Embed(
        title="Fabricacao registrada",
        description=(
            f"**{quantidade} {nome}** {registrado} com sucesso!\n"
            f"{detalhe_bau}\n{detalhe_log}"
        ),
        color=discord.Color.green(),
    )


class ColeteConfirmView(discord.ui.View):
    def __init__(self, quantidade: int, materiais: dict[str, int]):
        super().__init__(timeout=180)
        self.quantidade = quantidade
        self.materiais = materiais

    @discord.ui.button(label="CONFIRMAR FABRICACAO", style=discord.ButtonStyle.success)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._desativar()
        await interaction.response.edit_message(
            embed=_criar_embed_aguardando_print(self.quantidade),
            view=self,
        )

        def check(message: discord.Message) -> bool:
            return (
                message.author.id == interaction.user.id
                and message.channel.id == interaction.channel_id
                and any(_is_image_attachment(att) for att in message.attachments)
            )

        try:
            message = await interaction.client.wait_for(
                "message",
                check=check,
                timeout=PRINT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await interaction.edit_original_response(
                embed=_criar_embed_timeout(self.quantidade),
                view=self,
            )
            return

        print_attachment = next(
            att for att in message.attachments if _is_image_attachment(att)
        )
        try:
            print_file = await print_attachment.to_file(use_cached=True)
        except Exception:
            log.error("Erro ao baixar print de fabricacao de colete", exc_info=True)
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Erro ao ler o print",
                    description=(
                        "Nao consegui baixar a imagem enviada. "
                        "Tente registrar a fabricacao novamente."
                    ),
                    color=discord.Color.red(),
                ),
                view=self,
            )
            return

        try:
            await message.delete()
        except Exception:
            pass

        materiais = self.materiais
        fabricacao = db_registrar_fabricacao_colete(
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            quantidade=self.quantidade,
            ferro=materiais["ferro"],
            plastico=materiais["plastico"],
            tecido=materiais["tecido"],
            aluminio=materiais["aluminio"],
            borracha=materiais["borracha"],
            custo=materiais["custo"],
        )
        cog = interaction.client.get_cog("ColeteCog")
        bau_sincronizado = False
        operacao_bau = None
        if cog is not None:
            bau_sincronizado, operacao_bau = await cog.sincronizar_fabricacao(
                fabricacao
            )
        log.info(
            "Fabricacao registrada: user=%s qtd=%s custo=%s print=%s bau=%s",
            interaction.user.id,
            self.quantidade,
            materiais["custo"],
            print_attachment.filename,
            "sincronizado" if bau_sincronizado else "pendente",
        )

        log_embed = discord.Embed(
            title="Fabricacao de Colete Registrada",
            color=0xF1C40F,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(
            name="Membro",
            value=interaction.user.mention,
            inline=True,
        )
        log_embed.add_field(name="Produto", value="Colete", inline=True)
        log_embed.add_field(name="Quantidade", value=str(self.quantidade), inline=True)
        log_embed.add_field(
            name="Gasto total",
            value=_fmt_money(materiais["custo"]),
            inline=True,
        )
        log_embed.add_field(
            name="Materiais gastos",
            value=(
                f"Ferro: `{materiais['ferro']}`\n"
                f"Plastico: `{materiais['plastico']}`\n"
                f"Tecido: `{materiais['tecido']}`\n"
                f"Aluminio: `{materiais['aluminio']}`\n"
                f"Borracha: `{materiais['borracha']}`"
            ),
            inline=True,
        )
        log_embed.add_field(name="Canal", value=interaction.channel.mention, inline=True)
        if operacao_bau is not None and operacao_bau.lines:
            linha = operacao_bau.lines[0]
            estoque_bau = (
                f"`{linha.estoque_antes}` -> `{linha.estoque_depois}` "
                f"(+{linha.quantidade})"
            )
        elif bau_sincronizado:
            estoque_bau = "Sincronizado anteriormente, sem duplicar a entrada."
        else:
            estoque_bau = "Pendente de sincronizacao automatica."
        log_embed.add_field(
            name="Estoque do Bau",
            value=estoque_bau,
            inline=False,
        )
        log_embed.set_image(url=f"attachment://{print_file.filename}")
        log_embed.set_footer(text="Morro do Mineiro - Fabricacao de Coletes")

        log_enviado = await send_log(
            interaction.client,
            interaction.guild,
            "colete",
            log_embed,
            files=[print_file],
            fallback_channel_id=LOG_FABRICACAO_CHANNEL_ID,
        )
        await interaction.edit_original_response(
            embed=_criar_embed_sucesso(
                self.quantidade,
                log_enviado,
                bau_sincronizado,
            ),
            view=self,
        )

    @discord.ui.button(label="CANCELAR", style=discord.ButtonStyle.danger)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._desativar()
        embed = discord.Embed(
            title="Fabricacao cancelada",
            description="Nenhuma fabricacao foi registrada.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def _desativar(self):
        for item in self.children:
            item.disabled = True
        self.stop()


class ColeteQuantityView(discord.ui.View):
    def __init__(self, inicio: int, fim: int):
        super().__init__(timeout=180)
        if (inicio, fim) not in FAIXAS_QUANTIDADE:
            raise ValueError("Faixa de quantidades invalida.")

        select = discord.ui.Select(
            placeholder=f"Selecione de {inicio} a {fim} coletes...",
            options=[
                _criar_opcao_quantidade(quantidade)
                for quantidade in range(inicio, fim + 1)
            ],
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        quantidade = int(interaction.data["values"][0])
        materiais = calcular_fabricacao(quantidade)
        await interaction.response.edit_message(
            embed=_criar_embed_confirmacao(quantidade, materiais),
            view=ColeteConfirmView(quantidade, materiais),
        )


class ColetePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(
                label=f"{inicio} a {fim} coletes",
                description=f"Escolher uma quantidade entre {inicio} e {fim}",
                value=f"{inicio}:{fim}",
            )
            for inicio, fim in FAIXAS_QUANTIDADE
        ]
        select = discord.ui.Select(
            placeholder="Selecione uma faixa de quantidade...",
            options=options,
            custom_id="colete:faixa",
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        inicio, fim = map(int, interaction.data["values"][0].split(":"))
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Escolha a quantidade",
                description=f"Selecione de **{inicio} a {fim} coletes** abaixo.",
                color=0x34495E,
            ),
            view=ColeteQuantityView(inicio, fim),
            ephemeral=True,
        )


class ColeteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bau_sync_lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(ColetePanelView())
        self._bau_sync_task.start()

    async def cog_unload(self):
        self._bau_sync_task.cancel()

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

    @app_commands.command(
        name="colete",
        description="Posta o painel de fabricacao de coletes neste canal.",
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

        message = await canal.send(embed=_criar_embed_painel(), view=ColetePanelView())
        try:
            db_set_guild_config(
                guild_id,
                painel_colete_channel_id=str(canal.id),
                painel_colete_message_id=str(message.id),
            )
        except Exception:
            try:
                await message.delete()
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
            message.id,
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
