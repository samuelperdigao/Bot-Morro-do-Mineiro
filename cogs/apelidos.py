"""
cogs/apelidos.py - Mantem a tag do cargo no apelido dos membros.

O listener reage a qualquer troca de cargo (painel de hierarquia, promocao
automatica do farm, aprovacao de set) e reescreve o apelido com a tag certa.
"""

import asyncio
import contextlib

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from core.nickname import desired_nick, tag_for_member
from core.permissions import has_approver_permission
from services.db_service import db_get_approver_role_ids, db_get_guild_config

log = get_logger("apelidos", "bot.log")

DELAY_ENTRE_EDICOES = 1.0
LIMITE_PREVIEW      = 15

REASON_LISTENER = "Sincronizacao automatica da tag de cargo"
REASON_COMANDO  = "Sincronizacao manual das tags de cargo"

# user_ids cujo apelido esta sendo escrito por outro fluxo (ex: aprovacao de
# set); o listener nao deve gravar um nick intermediario nesse intervalo.
_suprimidos: set[int] = set()


@contextlib.contextmanager
def suppress(user_id: int):
    """Impede o listener de mexer no apelido deste usuario dentro do bloco."""
    _suprimidos.add(user_id)
    try:
        yield
    finally:
        _suprimidos.discard(user_id)


def is_suppressed(user_id: int) -> bool:
    return user_id in _suprimidos


def member_role_id_da_guild(guild_id) -> int | None:
    """Le o cargo '| Membro' configurado no guild_config (reforco para [MBR])."""
    try:
        cfg = db_get_guild_config(str(guild_id))
        valor = cfg["member_role_id"] if cfg else None
        return int(valor) if valor else None
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    except Exception as exc:
        log.warning("Nao foi possivel ler member_role_id da guild %s: %s", guild_id, exc)
        return None


def pode_editar(member: discord.Member) -> bool:
    if member.bot:
        return False
    guild = member.guild
    if guild is None or member.id == guild.owner_id:
        return False  # o Discord nao deixa renomear o dono do servidor
    me = guild.me
    if me is None or not me.guild_permissions.manage_nicknames:
        return False
    return me.top_role > member.top_role


def apelido_alvo(member: discord.Member, member_role_id: int | None) -> str | None:
    """Novo apelido, ou None quando nao ha tag ou nada muda."""
    tag = tag_for_member(member, member_role_id=member_role_id)
    novo = desired_nick(member, tag)
    if novo is None:
        return None
    atual = member.nick or member.display_name
    return None if novo == atual else novo


class ApelidosCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if set(before.roles) == set(after.roles):
            return  # evita loop com a propria edicao de apelido
        if is_suppressed(after.id):
            return
        await self.sincronizar_membro(after, reason=REASON_LISTENER)

    async def sincronizar_membro(self, member: discord.Member, *, reason: str) -> str:
        """Aplica a tag no apelido. Retorna 'pulado'/'sem_mudanca'/'alterado'/'sem_permissao'."""
        if not pode_editar(member):
            return "pulado"

        novo = apelido_alvo(member, member_role_id_da_guild(member.guild.id))
        if novo is None:
            return "sem_mudanca"

        try:
            await member.edit(nick=novo, reason=reason)
        except discord.Forbidden:
            log.warning("Sem permissao para alterar apelido de %s", member.id)
            return "sem_permissao"
        except discord.HTTPException as exc:
            log.error("Erro ao alterar apelido de %s: %s", member.id, exc)
            return "sem_permissao"

        log.info("Apelido de %s atualizado para '%s'", member.id, novo)
        return "alterado"

    @app_commands.command(
        name="sincronizar_apelidos",
        description="Aplica as tags de cargo ([LIDER], [VICE], [GRT], [MBR]) nos apelidos.",
    )
    @app_commands.describe(
        aplicar="True aplica as mudancas; por padrao mostra apenas a previa.",
    )
    async def sincronizar_apelidos(self, interaction: discord.Interaction, aplicar: bool = False):
        approver_role_ids = db_get_approver_role_ids(str(interaction.guild_id))
        if not has_approver_permission(interaction.user, approver_role_ids):
            await interaction.response.send_message(
                "❌ Sem permissão para sincronizar apelidos.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        member_role_id = member_role_id_da_guild(guild.id)

        pendentes: list[tuple[discord.Member, str]] = []
        pulados = 0
        sem_mudanca = 0

        for member in guild.members:
            if not pode_editar(member):
                pulados += 1
                continue
            novo = apelido_alvo(member, member_role_id)
            if novo is None:
                sem_mudanca += 1
                continue
            pendentes.append((member, novo))

        exemplos = "\n".join(
            f"`{member.nick or member.display_name}` → `{novo}`"
            for member, novo in pendentes[:LIMITE_PREVIEW]
        ) or "*(nenhum)*"

        if not aplicar:
            embed = discord.Embed(
                title="🔍 Prévia da sincronização de apelidos",
                description=(
                    f"**{len(pendentes)}** apelido(s) mudariam.\n"
                    f"Sem mudança: **{sem_mudanca}** • Pulados: **{pulados}**\n\n"
                    f"{exemplos}"
                ),
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            if len(pendentes) > LIMITE_PREVIEW:
                embed.set_footer(text=f"Mostrando {LIMITE_PREVIEW} de {len(pendentes)}.")
            else:
                embed.set_footer(text="Use aplicar:True para executar.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        alterados = 0
        sem_permissao = 0
        for indice, (member, novo) in enumerate(pendentes):
            try:
                await member.edit(nick=novo, reason=REASON_COMANDO)
                alterados += 1
            except discord.Forbidden:
                sem_permissao += 1
                log.warning("Sem permissao para alterar apelido de %s", member.id)
            except discord.HTTPException as exc:
                sem_permissao += 1
                log.error("Erro ao alterar apelido de %s: %s", member.id, exc)
            if indice + 1 < len(pendentes):
                await asyncio.sleep(DELAY_ENTRE_EDICOES)

        log.info(
            "sincronizar_apelidos executado por %s (guild %s): %s alterados, %s sem permissao",
            interaction.user.id, guild.id, alterados, sem_permissao,
        )

        embed = discord.Embed(
            title="✅ Apelidos sincronizados",
            description=(
                f"Alterados: **{alterados}**\n"
                f"Sem mudança: **{sem_mudanca}**\n"
                f"Sem permissão: **{sem_permissao}**\n"
                f"Pulados: **{pulados}**"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ApelidosCog(bot))
    log.info("ApelidosCog carregado com sucesso.")
