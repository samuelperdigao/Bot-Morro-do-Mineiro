"""
cogs/heroina.py - Painel fixo de producao de heroina.

/setup_heroina_painel posta o painel no canal_interacao_id configurado pelo dashboard.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import (
    db_get_painel_heroina,
    db_registrar_producao_heroina,
    db_set_guild_config,
    db_get_system_config,
)
from services.log_service import send_log

log = get_logger("heroina", "heroina.log")

QUANTIDADES = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
PRINT_TIMEOUT_SECONDS = 180.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
DEFAULT_HEROINA_LOG_CHANNEL_ID = 1506880362633236630


def _calcular(qtd: int) -> dict:
    base = qtd / 100
    return {
        "opio": base * 50,
        "folha": base * 50,
        "agulha": base * 20,
        "seringa": base * 20,
        "custo": base * 3000,
    }


def _fmt_money(valor: float) -> str:
    return f"${valor:,.0f}"


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    if content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _criar_embed_painel() -> discord.Embed:
    embed = discord.Embed(
        title="PRODUCAO DE HEROINA",
        description=(
            "Selecione abaixo a quantidade que deseja produzir.\n"
            "Os materiais necessarios e o custo serao exibidos antes da confirmacao."
        ),
        color=0x6A0DAD,
    )
    embed.set_footer(text="Morro do Mineiro")
    return embed


def _criar_embed_confirmacao(qtd: int, m: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Producao - {qtd} Heroinas",
        description=(
            "Confira os materiais necessarios e confirme a producao.\n"
            "Depois da confirmacao, voce precisara enviar o print da producao."
        ),
        color=0xFFD700,
    )
    embed.add_field(name="Opio", value=str(int(m["opio"])), inline=True)
    embed.add_field(name="Agulha", value=str(int(m["agulha"])), inline=True)
    embed.add_field(name="Folha", value=str(int(m["folha"])), inline=True)
    embed.add_field(name="Seringa", value=str(int(m["seringa"])), inline=True)
    embed.add_field(name="Custo", value=_fmt_money(m["custo"]), inline=True)
    embed.set_footer(text="Confirme ou cancele abaixo.")
    return embed


def _criar_embed_aguardando_print(qtd: int) -> discord.Embed:
    embed = discord.Embed(
        title="Aguardando print da producao",
        description=(
            f"Envie uma imagem neste canal em ate **{int(PRINT_TIMEOUT_SECONDS / 60)} minutos** "
            f"para confirmar a producao de **{qtd} heroinas**.\n\n"
            "A producao so sera registrada depois que o print for recebido."
        ),
        color=0xFFD700,
    )
    embed.set_footer(text="Formatos aceitos: PNG, JPG, JPEG, WEBP ou GIF.")
    return embed


def _criar_embed_timeout(qtd: int) -> discord.Embed:
    return discord.Embed(
        title="Tempo esgotado",
        description=(
            f"Nenhum print foi recebido para a producao de **{qtd} heroinas**. "
            "Nada foi registrado."
        ),
        color=discord.Color.red(),
    )


def _criar_embed_sucesso(qtd: int, log_enviado: bool) -> discord.Embed:
    detalhe_log = (
        "O log com print foi enviado no canal configurado."
        if log_enviado
        else "A producao foi salva, mas o canal de log de heroina nao foi encontrado ou falhou."
    )
    return discord.Embed(
        title="Producao registrada",
        description=f"**{qtd} heroinas** registradas com sucesso!\n{detalhe_log}",
        color=discord.Color.green(),
    )


class HeroinaConfirmView(discord.ui.View):
    """View efemera com botoes de confirmacao/cancelamento."""

    def __init__(self, qtd: int, materiais: dict):
        super().__init__(timeout=180)
        self.qtd = qtd
        self.materiais = materiais

    @discord.ui.button(label="CONFIRMAR PRODUCAO", style=discord.ButtonStyle.success)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        m = self.materiais
        self._desativar()
        await interaction.response.edit_message(
            embed=_criar_embed_aguardando_print(self.qtd),
            view=self,
        )

        def check(msg: discord.Message) -> bool:
            return (
                msg.author.id == interaction.user.id
                and msg.channel.id == interaction.channel_id
                and any(_is_image_attachment(att) for att in msg.attachments)
            )

        try:
            msg = await interaction.client.wait_for(
                "message",
                check=check,
                timeout=PRINT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await interaction.edit_original_response(
                embed=_criar_embed_timeout(self.qtd),
                view=self,
            )
            return

        print_attachment = next(att for att in msg.attachments if _is_image_attachment(att))
        try:
            print_file = await print_attachment.to_file(use_cached=True)
        except Exception:
            log.error("Erro ao baixar print de heroina", exc_info=True)
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Erro ao ler o print",
                    description="Nao consegui baixar a imagem enviada. Tente registrar a producao novamente.",
                    color=discord.Color.red(),
                ),
                view=self,
            )
            return

        try:
            await msg.delete()
        except Exception:
            pass

        db_registrar_producao_heroina(
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            quantidade=self.qtd,
            opio=m["opio"],
            agulha=m["agulha"],
            folha=m["folha"],
            seringa=m["seringa"],
            custo=m["custo"],
        )
        log.info(
            "Producao registrada: user=%s qtd=%s custo=%.0f print=%s",
            interaction.user.id,
            self.qtd,
            m["custo"],
            print_attachment.filename,
        )

        log_embed = discord.Embed(
            title="Producao de Heroina Registrada",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(
            name="Membro",
            value=f"{interaction.user.mention}\n{interaction.user.display_name}\n`{interaction.user.id}`",
            inline=True,
        )
        log_embed.add_field(name="Produto", value="Heroina", inline=True)
        log_embed.add_field(name="Quantidade", value=str(self.qtd), inline=True)
        log_embed.add_field(name="Gasto total", value=_fmt_money(m["custo"]), inline=True)
        log_embed.add_field(
            name="Materiais gastos",
            value=(
                f"Opio: `{int(m['opio'])}`\n"
                f"Folha: `{int(m['folha'])}`\n"
                f"Agulha: `{int(m['agulha'])}`\n"
                f"Seringa: `{int(m['seringa'])}`"
            ),
            inline=True,
        )
        log_embed.add_field(name="Canal", value=interaction.channel.mention, inline=True)
        log_embed.set_image(url=f"attachment://{print_file.filename}")
        log_embed.set_footer(text="Morro do Mineiro - Sistema de Heroina")

        log_enviado = await send_log(
            interaction.client,
            interaction.guild,
            "heroina",
            log_embed,
            files=[print_file],
            fallback_channel_id=DEFAULT_HEROINA_LOG_CHANNEL_ID,
        )
        await interaction.edit_original_response(
            embed=_criar_embed_sucesso(self.qtd, log_enviado),
            view=self,
        )

    @discord.ui.button(label="CANCELAR", style=discord.ButtonStyle.danger)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._desativar()
        embed = discord.Embed(
            title="Producao cancelada",
            description="Nenhuma producao foi registrada.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def _desativar(self):
        for item in self.children:
            item.disabled = True
        self.stop()


class HeroinaPanelView(discord.ui.View):
    """View persistente do painel de heroina."""

    def __init__(self):
        super().__init__(timeout=None)

        options = []
        for qtd in QUANTIDADES:
            m = _calcular(qtd)
            options.append(
                discord.SelectOption(
                    label=f"{qtd} Heroinas - {_fmt_money(m['custo'])}",
                    description=(
                        f"Opio: {int(m['opio'])} | Agulha: {int(m['agulha'])} "
                        f"| Folha: {int(m['folha'])} | Seringa: {int(m['seringa'])}"
                    ),
                    value=str(qtd),
                )
            )

        select = discord.ui.Select(
            placeholder="Selecione a quantidade...",
            options=options,
            custom_id="heroina:select",
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        qtd = int(interaction.data["values"][0])
        m = _calcular(qtd)
        await interaction.response.send_message(
            embed=_criar_embed_confirmacao(qtd, m),
            view=HeroinaConfirmView(qtd, m),
            ephemeral=True,
        )


class HeroinaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(HeroinaPanelView())

    @app_commands.command(
        name="setup_heroina_painel",
        description="Posta o painel de producao de heroina no canal configurado pelo dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_heroina_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        row = db_get_system_config(guild_id, "heroina")

        if not row or not row["canal_interacao_id"]:
            await interaction.response.send_message(
                "Canal de heroina nao configurado.\n"
                "Configure o sistema **heroina** pelo **dashboard** primeiro.",
                ephemeral=True,
            )
            return

        canal_id = int(row["canal_interacao_id"])
        canal = interaction.guild.get_channel(canal_id)
        if canal is None:
            try:
                canal = await interaction.guild.fetch_channel(canal_id)
            except Exception:
                await interaction.response.send_message("Canal nao encontrado.", ephemeral=True)
                return

        _, old_msg_id = db_get_painel_heroina(guild_id)
        if old_msg_id:
            try:
                old_msg = await canal.fetch_message(int(old_msg_id))
                await old_msg.delete()
            except Exception:
                pass

        msg = await canal.send(embed=_criar_embed_painel(), view=HeroinaPanelView())
        db_set_guild_config(
            guild_id,
            painel_heroina_channel_id=str(canal.id),
            painel_heroina_message_id=str(msg.id),
        )
        await interaction.response.send_message(
            f"Painel de heroina postado em {canal.mention}!", ephemeral=True
        )
        log.info("Painel heroina postado: message_id=%s (guild %s)", msg.id, guild_id)

    @setup_heroina_painel.error
    async def setup_heroina_painel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Sem permissao para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_heroina_painel: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HeroinaCog(bot))
    log.info("HeroinaCog carregado.")
