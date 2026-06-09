"""
Painel fixo de fabricacao de coletes.

/colete publica o painel no canal em que o comando for executado.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import (
    db_get_painel_colete,
    db_registrar_fabricacao_colete,
    db_set_guild_config,
)
from services.log_service import send_log

log = get_logger("colete", "colete.log")

QUANTIDADES = range(1, 11)
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
        raise ValueError("A quantidade deve estar entre 1 e 10.")
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
            "O limite e de **10 coletes por vez**.\n\n"
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


def _criar_embed_sucesso(quantidade: int, log_enviado: bool) -> discord.Embed:
    nome = _nome_colete(quantidade)
    registrado = "registrado" if quantidade == 1 else "registrados"
    detalhe_log = (
        "O log com o print foi enviado ao canal de fabricacao."
        if log_enviado
        else "A fabricacao foi salva, mas nao foi possivel enviar o log."
    )
    return discord.Embed(
        title="Fabricacao registrada",
        description=(
            f"**{quantidade} {nome}** {registrado} com sucesso!\n{detalhe_log}"
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
        db_registrar_fabricacao_colete(
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
        log.info(
            "Fabricacao registrada: user=%s qtd=%s custo=%s print=%s",
            interaction.user.id,
            self.quantidade,
            materiais["custo"],
            print_attachment.filename,
        )

        log_embed = discord.Embed(
            title="Fabricacao de Colete Registrada",
            color=0xF1C40F,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(
            name="Membro",
            value=(
                f"{interaction.user.mention}\n"
                f"{interaction.user.display_name}\n"
                f"`{interaction.user.id}`"
            ),
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
            embed=_criar_embed_sucesso(self.quantidade, log_enviado),
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


class ColetePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        options = []
        for quantidade in QUANTIDADES:
            materiais = calcular_fabricacao(quantidade)
            nome = _nome_colete(quantidade)
            options.append(
                discord.SelectOption(
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
            )

        select = discord.ui.Select(
            placeholder="Selecione de 1 a 10 coletes...",
            options=options,
            custom_id="colete:select",
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        quantidade = int(interaction.data["values"][0])
        materiais = calcular_fabricacao(quantidade)
        await interaction.response.send_message(
            embed=_criar_embed_confirmacao(quantidade, materiais),
            view=ColeteConfirmView(quantidade, materiais),
            ephemeral=True,
        )


class ColeteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ColetePanelView())

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
                    await old_message.delete()
                except Exception:
                    pass

        message = await canal.send(embed=_criar_embed_painel(), view=ColetePanelView())
        db_set_guild_config(
            guild_id,
            painel_colete_channel_id=str(canal.id),
            painel_colete_message_id=str(message.id),
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
            log.error("Erro no /colete: %s", error, exc_info=True)
            mensagem = "Ocorreu um erro ao publicar o painel."

        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ColeteCog(bot))
    log.info("ColeteCog carregado.")
