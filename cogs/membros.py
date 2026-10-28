"""Eventos de entrada/saida de membros e reconciliacao de pastas."""

import asyncio

import discord
from discord.ext import commands

from core.date_utils import format_datetime_br
from core.discord_helpers import fetch_channel_safe
from core.nickname import strip_tag
from core.role_sync import find_role_by_names
from core.logger import get_logger
from core.settings import get_legacy_channel_id
from services.db_service import (
    db_channel_map_all,
    db_channel_map_get,
    db_channel_map_set,
    db_get_approver_role_ids,
    db_get_guild_config,
    db_pending_member_folder_delete,
    db_pending_member_folder_exists,
    db_pending_member_folders_all,
    db_pending_member_folder_set,
)
from services.set_service import criar_pasta, is_manager_role, liberar_pasta

log = get_logger("bot", "bot.log")

CANAL_LOG_ENTRADA_ID = get_legacy_channel_id("entry_log")
CANAL_LOG_PD_ID = get_legacy_channel_id("pd_log")


def _format_delta(delta) -> str:
    dias = delta.days
    horas = delta.seconds // 3600
    minutos = (delta.seconds % 3600) // 60

    if dias >= 365:
        return f"{dias // 365}a {dias % 365}d"
    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"
    if horas > 0:
        return f"{horas}h {minutos}m"
    return f"{minutos}m"


class MembrosCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pastas_reconciliadas = False
        self._locks_pastas_membro: dict[tuple[int, int], asyncio.Lock] = {}

    @staticmethod
    def _is_manager(member: discord.Member) -> bool:
        return any(is_manager_role(role) for role in getattr(member, "roles", []))

    @staticmethod
    def _has_member_role(member: discord.Member, cfg) -> bool:
        roles = getattr(member, "roles", [])
        member_role_id = cfg["member_role_id"] if cfg and "member_role_id" in cfg.keys() else None
        if member_role_id:
            try:
                if any(role.id == int(member_role_id) for role in roles):
                    return True
            except (TypeError, ValueError):
                pass
        member_role = find_role_by_names(member.guild, ("| Membro", "Membro"))
        return member_role is not None and member_role in roles

    @staticmethod
    def _farm_identity_from_nickname(member: discord.Member) -> tuple[str, str] | None:
        nickname = getattr(member, "nick", None) or getattr(member, "display_name", "")
        name_and_id = strip_tag(nickname)
        name, separator, game_id = name_and_id.rpartition(" | ")
        name = name.strip()
        game_id = game_id.strip()
        if not separator or not name or not game_id.isdigit():
            return None
        return name, game_id

    def _folder_lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        key = (guild_id, user_id)
        if key not in self._locks_pastas_membro:
            self._locks_pastas_membro[key] = asyncio.Lock()
        return self._locks_pastas_membro[key]

    async def _atribuir_ou_adiar_pasta_membro(self, member: discord.Member) -> bool:
        guild = member.guild
        guild_id = str(guild.id)
        user_id = str(member.id)
        async with self._folder_lock(guild.id, member.id):
            if self._is_manager(member):
                db_pending_member_folder_delete(guild_id, user_id)
                return False

            if db_channel_map_get(guild_id, user_id):
                db_pending_member_folder_delete(guild_id, user_id)
                return False

            cfg = db_get_guild_config(guild_id)
            if not self._has_member_role(member, cfg):
                return False

            identity = self._farm_identity_from_nickname(member)
            if identity is None:
                log.warning(
                    "Pasta de membro pendente para %s (%s): apelido sem ID de jogo valido.",
                    member,
                    member.id,
                )
                return False

            category_id = cfg["private_category_id"] if cfg and "private_category_id" in cfg.keys() else None
            if not category_id:
                log.error(
                    "Pasta de membro pendente para %s (%s): categoria privada nao configurada.",
                    member,
                    member.id,
                )
                return False

            folder = await criar_pasta(
                guild,
                member,
                member,
                int(category_id),
                db_get_approver_role_ids(guild_id),
                id_jogo=identity[1],
                membro_nome=identity[0],
                reason="Pasta de membro atribuida apos rebaixamento de gerente",
            )
            if folder is None:
                log.error(
                    "Nao foi possivel atribuir pasta de membro a %s (%s); pendencia mantida.",
                    member,
                    member.id,
                )
                return False

            db_channel_map_set(guild_id, user_id, folder.id)
            db_pending_member_folder_delete(guild_id, user_id)
            log.info("Pasta de membro %s atribuida a %s (%s).", folder.name, member, member.id)
            return True

    @commands.Cog.listener()
    async def on_ready(self):
        if self._pastas_reconciliadas:
            return

        self._pastas_reconciliadas = True
        self.bot.loop.create_task(self._reconciliar_pastas())

    async def _reconciliar_pastas(self):
        await asyncio.sleep(5)
        liberadas = 0
        atribuidas = 0
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            for user_id_str, _ in db_channel_map_all(guild_id):
                member = guild.get_member(int(user_id_str))
                if member is None:
                    liberado = await liberar_pasta(guild, None, guild_id, user_id=user_id_str)
                elif self._is_manager(member):
                    db_pending_member_folder_delete(guild_id, user_id_str)
                    liberado = await liberar_pasta(guild, member, guild_id)
                else:
                    liberado = False
                if liberado:
                    liberadas += 1

            for user_id_str in db_pending_member_folders_all(guild_id):
                member = guild.get_member(int(user_id_str))
                if member is None:
                    continue
                if await self._atribuir_ou_adiar_pasta_membro(member):
                    atribuidas += 1

        if liberadas or atribuidas:
            log.info(
                "Reconciliacao de pastas: %s liberada(s), %s atribuida(s).",
                liberadas,
                atribuidas,
            )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild_id = str(after.guild.id)
        user_id = str(after.id)
        was_manager = self._is_manager(before)
        is_manager = self._is_manager(after)

        if not was_manager and is_manager:
            db_pending_member_folder_delete(guild_id, user_id)
            released = await liberar_pasta(after.guild, after, guild_id)
            if released:
                log.info("Pasta de membro liberada ao promover %s (%s) a gerente.", after, after.id)
            return

        if was_manager and not is_manager:
            db_pending_member_folder_set(guild_id, user_id)

        pending = db_pending_member_folder_exists(guild_id, user_id)
        nickname_changed = getattr(before, "nick", None) != getattr(after, "nick", None)
        roles_changed = set(getattr(before, "roles", [])) != set(getattr(after, "roles", []))
        if pending and not is_manager and (was_manager or nickname_changed or roles_changed):
            await self._atribuir_ou_adiar_pasta_membro(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        db_pending_member_folder_delete(guild_id, str(member.id))
        await liberar_pasta(member.guild, member, guild_id)

        motivo = "Saiu voluntariamente"
        responsavel = None
        agora = discord.utils.utcnow()

        if member.guild.me and member.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target.id == member.id and (agora - entry.created_at).total_seconds() < 10:
                        motivo = "Expulso (Kick)"
                        responsavel = entry.user
                        break

                if motivo == "Saiu voluntariamente":
                    async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                        if entry.target.id == member.id and (agora - entry.created_at).total_seconds() < 10:
                            motivo = "Banido"
                            responsavel = entry.user
                            break
            except discord.Forbidden:
                pass
            except Exception as exc:
                log.warning("Erro ao verificar audit log para %s: %s", member.id, exc)

        if member.joined_at:
            tempo_str = _format_delta(agora - member.joined_at)
            entrou_str = f"`{format_datetime_br(member.joined_at)}`"
        else:
            tempo_str = "Desconhecido"
            entrou_str = "Desconhecido"

        cargos = [role.mention for role in member.roles if role != member.guild.default_role]
        cargos_txt = " ".join(cargos)[:1024] if cargos else "*(nenhum)*"

        embed = discord.Embed(
            title="Membro saiu do servidor",
            color=discord.Color.from_rgb(255, 76, 76),
            timestamp=agora,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{member.display_name}\n`{member}`", inline=True)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Entrou em", value=entrou_str, inline=True)
        embed.add_field(name="Saiu em", value=f"`{format_datetime_br(agora)}`", inline=True)
        embed.add_field(name="Tempo no servidor", value=tempo_str, inline=True)
        embed.add_field(name="Motivo da saida", value=motivo, inline=True)
        embed.add_field(name="Responsavel", value=responsavel.mention if responsavel else "-", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Cargos que tinha", value=cargos_txt, inline=False)
        embed.set_footer(text=f"ID: {member.id}")

        cfg = db_get_guild_config(guild_id)
        log_saida_id = cfg["canal_log_saida_id"] if cfg else None
        canal_log = await fetch_channel_safe(member.guild, log_saida_id)
        if canal_log:
            try:
                await canal_log.send(embed=embed)
            except discord.Forbidden:
                log.warning("Sem permissao para postar log de saida no canal %s (guild %s)", log_saida_id, guild_id)
            except Exception as exc:
                log.error("Erro ao enviar log de saida para %s: %s", member.id, exc)

        canal_pd = await fetch_channel_safe(self.bot, CANAL_LOG_PD_ID)
        if canal_pd:
            try:
                await canal_pd.send(
                    content="Lembre-se de remover o membro do **painel do morro**!",
                    embed=embed,
                )
            except discord.Forbidden:
                log.warning("Sem permissao para postar log PD no canal %s", CANAL_LOG_PD_ID)
            except Exception as exc:
                log.error("Erro ao enviar log PD para %s: %s", member.id, exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cargo = discord.utils.get(member.guild.roles, name="| Pedir Set")
        if cargo is None:
            cargo = discord.utils.get(member.guild.roles, name="Pedir Set")

        if cargo is not None:
            try:
                await member.add_roles(cargo, reason="Cargo automatico ao entrar no servidor")
                log.info("[on_member_join] Cargo '%s' atribuido a %s (ID: %s)", cargo.name, member, member.id)
            except discord.Forbidden:
                log.error("[on_member_join] Sem permissao para atribuir cargo a %s", member)
            except Exception as exc:
                log.error("[on_member_join] Erro ao atribuir cargo a %s: %s", member, exc, exc_info=True)
        else:
            log.warning("[on_member_join] Cargo 'Pedir Set' nao encontrado em '%s'", member.guild.name)

        canal_log = await fetch_channel_safe(self.bot, CANAL_LOG_ENTRADA_ID)
        if canal_log is None:
            log.warning("[on_member_join] Canal de log de entrada %s nao encontrado.", CANAL_LOG_ENTRADA_ID)
            return

        agora = discord.utils.utcnow()
        criado_em = member.created_at
        idade_conta = _format_delta(agora - criado_em)
        alerta_nova = "\n**CONTA NOVA**" if (agora - criado_em).days < 7 else ""

        embed = discord.Embed(
            title="Novo membro entrou no servidor",
            color=0x2ECC71,
            timestamp=agora,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{member.mention}\n`{member.display_name}`\n`{member}`", inline=True)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(
            name="Conta criada em",
            value=f"`{format_datetime_br(criado_em)}`\n`{idade_conta} atras`{alerta_nova}",
            inline=True,
        )
        embed.add_field(name="Entrou em", value=f"`{format_datetime_br(agora)}`", inline=True)
        embed.add_field(name="Membros no servidor", value=f"`{member.guild.member_count}`", inline=True)
        embed.set_footer(text=f"ID: {member.id}")

        try:
            await canal_log.send(embed=embed)
        except discord.Forbidden:
            log.warning("[on_member_join] Sem permissao para postar no canal %s", CANAL_LOG_ENTRADA_ID)
        except Exception as exc:
            log.error("[on_member_join] Erro ao enviar log de entrada: %s", exc, exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MembrosCog(bot))
