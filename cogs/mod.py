"""
cogs/mod.py - Comandos de moderação.

/clear → apaga mensagens do canal atual (requer manage_messages)
/organizar_canais → adiciona o separador visual nos canais de texto
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("mod", "mod.log")

SEPARADOR_CANAIS = "┃"
ICONE_PASTA = "📁"
MAX_CHANNEL_NAME_LENGTH = 100


def _nome_com_separador(nome: str) -> str | None:
    if SEPARADOR_CANAIS in nome:
        return None

    nome_limpo = nome.lstrip("-")
    numero = nome_limpo.split("-", 1)[0]
    if numero.isdigit():
        return f"{SEPARADOR_CANAIS}{ICONE_PASTA}-{nome_limpo}"[:MAX_CHANNEL_NAME_LENGTH]
    return f"{SEPARADOR_CANAIS}{nome}"[:MAX_CHANNEL_NAME_LENGTH]


class ModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="clear", description="Apaga mensagens do canal atual.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(quantidade="Número de mensagens a apagar (1–100)")
    async def clear(
        self,
        interaction: discord.Interaction,
        quantidade: app_commands.Range[int, 1, 100],
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            deletadas = await interaction.channel.purge(limit=quantidade)
            await interaction.followup.send(
                f"✅ {len(deletadas)} mensagem(ns) apagada(s).", ephemeral=True
            )
            log.info(
                f"/clear: {len(deletadas)} msgs apagadas em #{interaction.channel} "
                f"por {interaction.user} (guild {interaction.guild_id})"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Sem permissão para apagar mensagens neste canal.", ephemeral=True
            )
        except Exception as e:
            log.error(f"Erro em /clear: {e}", exc_info=True)
            await interaction.followup.send("❌ Erro ao apagar mensagens.", ephemeral=True)

    @clear.error
    async def clear_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Mensagens** para usar este comando.",
                ephemeral=True,
            )
        else:
            log.error(f"Erro em /clear: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    @app_commands.command(
        name="organizar_canais",
        description="Adiciona o separador visual nos canais de texto que ainda não têm.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        categoria="Categoria que será organizada. Se vazio, usa a categoria atual.",
        todos="Organizar todos os canais de texto do servidor.",
    )
    async def organizar_canais(
        self,
        interaction: discord.Interaction,
        categoria: discord.CategoryChannel = None,
        todos: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ Este comando só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        if todos:
            canais = list(guild.text_channels)
            escopo = "servidor inteiro"
        else:
            categoria_alvo = categoria or getattr(interaction.channel, "category", None)
            if categoria_alvo is None:
                await interaction.followup.send(
                    "❌ Informe uma categoria ou use `todos: True`.",
                    ephemeral=True,
                )
                return
            canais = list(categoria_alvo.text_channels)
            escopo = f"categoria **{categoria_alvo.name}**"

        renomeados: list[str] = []
        ignorados = 0
        falhas: list[str] = []

        for canal in sorted(canais, key=lambda ch: ch.position):
            novo_nome = _nome_com_separador(canal.name)
            if novo_nome is None:
                ignorados += 1
                continue

            nome_antigo = canal.name
            try:
                await canal.edit(
                    name=novo_nome,
                    reason=f"Organização de canais solicitada por {interaction.user}",
                )
                renomeados.append(f"`#{nome_antigo}` → `#{novo_nome}`")
            except discord.Forbidden:
                falhas.append(f"`#{nome_antigo}` (sem permissão)")
            except Exception as exc:
                falhas.append(f"`#{nome_antigo}` ({exc})")

        descricao = (
            f"Escopo: {escopo}\n"
            f"Renomeados: `{len(renomeados)}`\n"
            f"Já tinham `{SEPARADOR_CANAIS}`: `{ignorados}`\n"
            f"Falhas: `{len(falhas)}`"
        )

        embed = discord.Embed(
            title="Canais organizados",
            description=descricao,
            color=discord.Color.green() if not falhas else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        if renomeados:
            embed.add_field(
                name="Alterados",
                value="\n".join(renomeados[:10]),
                inline=False,
            )
        if len(renomeados) > 10:
            embed.add_field(
                name="Mais alterações",
                value=f"`{len(renomeados) - 10}` canal(is) além dos listados.",
                inline=False,
            )
        if falhas:
            embed.add_field(
                name="Falhas",
                value="\n".join(falhas[:10]),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info(
            "/organizar_canais: %s renomeado(s), %s ignorado(s), %s falha(s) em %s por %s (guild %s)",
            len(renomeados),
            ignorados,
            len(falhas),
            escopo,
            interaction.user,
            interaction.guild_id,
        )

    @organizar_canais.error
    async def organizar_canais_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Canais** para usar este comando.",
                ephemeral=True,
            )
        else:
            log.error(f"Erro em /organizar_canais: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCog(bot))
    log.info("ModCog carregado.")
