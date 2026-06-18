"""
cogs/set_views.py — SetModal, ApprovalView, SetPanelView e utilitários de rate-limit.

Extraído de main.py para desacoplar do ponto de entrada e permitir importação
segura por outros cogs (ex: cogs.paineis).
"""

import logging
import time

import discord

from core.permissions import has_approver_permission
from services.db_service import (
    db_get_guild_config,
    db_is_bot_configured,
    db_get_approver_role_ids,
    db_channel_map_get,
    db_channel_map_set,
)
from services.set_service import criar_pasta, safe_fetch_channel

log       = logging.getLogger("bot")
_audit_log = logging.getLogger("audit")

SET_COOLDOWN_SECONDS = 300
_pending_sets: dict[int, float] = {}


def _audit(action: str, executor_id: int, target_id: int | None = None, **kwargs):
    parts = [f"action={action}", f"executor={executor_id}"]
    if target_id:
        parts.append(f"target={target_id}")
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    _audit_log.info(" | ".join(parts))


def _check_rate_limit(user_id: int) -> tuple[bool, float]:
    last = _pending_sets.get(user_id)
    if last is None:
        return True, 0.0
    elapsed = time.monotonic() - last
    if elapsed >= SET_COOLDOWN_SECONDS:
        return True, 0.0
    return False, SET_COOLDOWN_SECONDS - elapsed


def _register_pending(user_id: int):
    _pending_sets[user_id] = time.monotonic()


def _clear_pending(user_id: int):
    _pending_sets.pop(user_id, None)


def _get_flanelinha_role(guild: discord.Guild, cfg) -> discord.Role | None:
    if cfg and cfg["flanelinha_role_id"]:
        role = guild.get_role(int(cfg["flanelinha_role_id"]))
        if role is not None:
            return role

    return (
        discord.utils.get(guild.roles, name="| Flanelinha")
        or discord.utils.get(guild.roles, name="Flanelinha")
    )


class SetModal(discord.ui.Modal, title="Solicitação de Set"):
    id_jogo     = discord.ui.TextInput(label="ID no Jogo", placeholder="Ex: 12345", min_length=1, max_length=20)
    membro_nome = discord.ui.TextInput(label="Nome do Membro", placeholder="Ex: João Silva", max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)

        if not db_is_bot_configured(guild_id):
            await interaction.followup.send(
                "❌ Este servidor ainda não foi configurado. Um administrador deve usar `/setup_bot`.",
                ephemeral=True,
            )
            return

        if not self.id_jogo.value.strip().isdigit():
            await interaction.followup.send("❌ O ID do jogo deve conter apenas números.", ephemeral=True)
            return

        pode, restante = _check_rate_limit(interaction.user.id)
        if not pode:
            mins = int(restante // 60)
            secs = int(restante % 60)
            await interaction.followup.send(f"⏳ Aguarde **{mins}m {secs}s** para enviar outra.", ephemeral=True)
            return

        _register_pending(interaction.user.id)

        cfg              = db_get_guild_config(guild_id)
        guild            = interaction.guild
        solicitante      = interaction.user
        approval_ch_id   = int(cfg["approval_channel_id"])
        approval_channel = guild.get_channel(approval_ch_id) or await guild.fetch_channel(approval_ch_id)

        embed = discord.Embed(
            title="📋 Nova Solicitação de Set",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=solicitante.display_avatar.url)
        embed.add_field(name="🎮 ID no Jogo",           value=f"`{self.id_jogo.value.strip()}`",            inline=True)
        embed.add_field(name="📝 Nome",                  value=self.membro_nome.value,                       inline=True)
        embed.add_field(name="📨 Solicitante (Discord)", value=f"{solicitante.mention}\n`{solicitante.id}`", inline=False)
        embed.set_footer(text="Aguardando decisão da liderança")

        view = ApprovalView(
            target_user_id=solicitante.id,
            target_name=self.membro_nome.value,
            requester=solicitante,
            id_jogo=self.id_jogo.value.strip(),
        )
        msg = await approval_channel.send(embed=embed, view=view)
        view.message = msg

        _audit("SET_SOLICITADO", solicitante.id, nome=self.membro_nome.value, id_jogo=self.id_jogo.value.strip())
        await interaction.followup.send(
            f"✅ Solicitação enviada com ID `{self.id_jogo.value.strip()}`! Aguarde aprovação.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"Erro no SetModal: {error}", exc_info=True)
        _clear_pending(interaction.user.id)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
        except Exception:
            pass


class SetPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Fazer Set", style=discord.ButtonStyle.primary, custom_id="set_panel:fazer_set")
    async def fazer_set(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetModal())


class ApprovalView(discord.ui.View):
    def __init__(self, target_user_id: int, target_name: str, requester: discord.Member, id_jogo: str = ""):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.target_name    = target_name
        self.requester      = requester
        self.id_jogo        = id_jogo
        self.message: discord.Message | None = None
        self._processando   = False

    def _check_permission(self, interaction: discord.Interaction) -> bool:
        approver_role_ids = db_get_approver_role_ids(str(interaction.guild_id))
        return has_approver_permission(interaction.user, approver_role_ids)

    @discord.ui.button(label="✅ Aprovar", style=discord.ButtonStyle.success, custom_id="approval:aprovar")
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Sem permissão para aprovar.", ephemeral=True)
            return
        if self._processando:
            await interaction.response.send_message("⏳ Já sendo processado...", ephemeral=True)
            return
        self._processando = True
        await interaction.response.defer()
        await self._processar(interaction, aprovado=True)

    @discord.ui.button(label="❌ Reprovar", style=discord.ButtonStyle.danger, custom_id="approval:reprovar")
    async def reprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Sem permissão para reprovar.", ephemeral=True)
            return
        if self._processando:
            await interaction.response.send_message("⏳ Já sendo processado...", ephemeral=True)
            return
        self._processando = True
        await interaction.response.defer()
        await self._processar(interaction, aprovado=False)

    async def _processar(self, interaction: discord.Interaction, aprovado: bool):
        guild    = interaction.guild
        guild_id = str(guild.id)
        approver = interaction.user

        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception as e:
                log.warning(f"Não foi possível remover view: {e}")

        _clear_pending(self.requester.id if self.requester else 0)

        if not aprovado:
            embed = discord.Embed(
                title="❌ Set Reprovado",
                description=f"**{self.target_name}**\nReprovado por {approver.mention}",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            _audit("SET_REPROVADO", approver.id, self.target_user_id)
            await interaction.followup.send(embed=embed)
            return

        try:
            member = guild.get_member(self.target_user_id) or await guild.fetch_member(self.target_user_id)
        except discord.NotFound:
            await interaction.followup.send(f"❌ Membro `{self.target_user_id}` não encontrado.", ephemeral=True)
            return
        except Exception as e:
            log.error(f"Erro ao buscar membro: {e}")
            await interaction.followup.send("❌ Erro ao buscar membro.", ephemeral=True)
            return

        cfg               = db_get_guild_config(guild_id)
        log_ch_id         = int(cfg["log_channel_id"]) if cfg and cfg["log_channel_id"] else None
        private_cat_id    = int(cfg["private_category_id"]) if cfg and cfg["private_category_id"] else None
        approver_role_ids = db_get_approver_role_ids(guild_id)

        flanelinha_role = _get_flanelinha_role(guild, cfg)
        if flanelinha_role and flanelinha_role not in member.roles:
            try:
                await member.add_roles(flanelinha_role, reason=f"Set aprovado por {approver}")
            except Exception as e:
                log.error(f"Erro ao aplicar cargo: {e}")
        elif flanelinha_role is None:
            log.warning("Cargo Flanelinha nao encontrado na guild %s ao aprovar set", guild_id)

        pedir_set_role = guild.get_role(1474869320659107853)
        if pedir_set_role and pedir_set_role in member.roles:
            try:
                await member.remove_roles(pedir_set_role, reason=f"Set aprovado por {approver}")
            except Exception as e:
                log.error(f"Erro ao remover cargo 'Pedir Set': {e}")

        # FIX: nome do canal duplicando ID do jogo
        # Canal privado criado ANTES de definir o apelido para que
        # member.display_name não contenha ainda o id_jogo ao montar o nome.
        existing_ch_id = db_channel_map_get(guild_id, str(self.target_user_id))
        pasta   = None
        created = False

        if existing_ch_id:
            pasta = guild.get_channel(existing_ch_id) or await safe_fetch_channel(guild, existing_ch_id)
            if pasta is None:
                pasta   = await criar_pasta(guild, member, approver, private_cat_id, approver_role_ids, self.id_jogo, self.target_name)
                created = True
                if pasta:
                    db_channel_map_set(guild_id, str(self.target_user_id), pasta.id)
        else:
            pasta   = await criar_pasta(guild, member, approver, private_cat_id, approver_role_ids, self.id_jogo, self.target_name)
            created = True
            if pasta:
                db_channel_map_set(guild_id, str(self.target_user_id), pasta.id)

        if self.id_jogo:
            novo_nick = f"{self.target_name} | {self.id_jogo}"[:32]
            try:
                await member.edit(nick=novo_nick, reason=f"Set aprovado por {approver}")
            except discord.Forbidden:
                log.warning(f"Sem permissão para alterar apelido de {member.id}")
            except Exception as e:
                log.error(f"Erro ao alterar apelido: {e}")

        log_channel = None
        if log_ch_id:
            log_channel = guild.get_channel(log_ch_id) or await safe_fetch_channel(guild, log_ch_id)

        if log_channel:
            log_embed = discord.Embed(title="✅ Set Aprovado", color=discord.Color.green(), timestamp=discord.utils.utcnow())
            log_embed.set_thumbnail(url=member.display_avatar.url)
            log_embed.add_field(name="👤 Membro",        value=f"{member.mention}\n`{member.id}`",     inline=True)
            log_embed.add_field(name="✅ Aprovado por",  value=f"{approver.mention}\n`{approver.id}`", inline=True)
            log_embed.add_field(name="🎮 ID no Jogo",    value=f"`{self.id_jogo}`" if self.id_jogo else "N/A", inline=True)
            log_embed.add_field(name="📁 Canal Privado", value=pasta.mention if pasta else "❌ Falha ao criar", inline=False)
            log_embed.set_footer(text=f"Canal {'criado' if created else 'já existia'}")
            await log_channel.send(embed=log_embed)

        if pasta:
            farm_embed = discord.Embed(
                title="🎉 Bem-vindo(a) à Família!",
                description=(
                    f"Olá, {member.mention}! Seu set foi aprovado por {approver.mention}.\n"
                    f"Este é o seu canal privado - guarde bem.\n\n"
                    f"Leia este tutorial antes de fazer seu primeiro **lançamento de farm**."
                ),
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            farm_embed.set_thumbnail(url=member.display_avatar.url)
            if self.id_jogo:
                farm_embed.add_field(name="🎮 ID no Jogo", value=f"`{self.id_jogo}`", inline=True)
            farm_embed.add_field(name="\u200b", value="\u200b", inline=False)
            farm_embed.add_field(
                name="1️⃣ Confira a meta da semana",
                value=(
                    "Consulte a meta ativa no painel. O mesmo ticket individual é usado para "
                    "Kit Desmanche, materiais de Colete ou dinheiro."
                ),
                inline=False,
            )
            farm_embed.add_field(
                name="2️⃣ Faça o lançamento",
                value=(
                    "Vá ao **Painel de Farm**, clique em **🎫 Abrir Ticket Semanal** e faça todos "
                    "os lançamentos exclusivamente no seu canal privado.\n"
                    "Use números inteiros nos itens. Para dinheiro, pode usar `50000` ou `R$ 50.000`."
                ),
                inline=False,
            )
            farm_embed.add_field(
                name="3️⃣ Envie o print obrigatório",
                value=(
                    "Depois de confirmar o modal do ticket, o bot vai pedir o print no mesmo canal. "
                    "Envie uma imagem em até **3 minutos**.\n"
                    "O farm só é registrado depois que o print é recebido. Se o tempo acabar, "
                    "nada será salvo e você precisará lançar novamente."
                ),
                inline=False,
            )
            farm_embed.add_field(
                name="📊 Acompanhar ou corrigir",
                value=(
                    "Use o painel do ticket, **📊 Ver Meu Farm** ou `/farm` para acompanhar sua "
                    "meta e porcentagem. Para corrigir um lançamento, solicite a revisão dentro "
                    "do próprio ticket."
                ),
                inline=False,
            )
            farm_embed.add_field(
                name="📅 Janela de lançamento",
                value="Os lançamentos são aceitos de **segunda 00:00 a domingo 23:59**.",
                inline=True,
            )
            farm_embed.add_field(
                name="⚠️ Atenção",
                value="Lance somente o que você produziu e mantenha o print separado antes de abrir o modal.",
                inline=False,
            )
            farm_embed.set_footer(text="Morro do Mineiro • Bom trabalho!")
            await pasta.send(embed=farm_embed)

        _audit("SET_APROVADO", approver.id, member.id, id_jogo=self.id_jogo, canal=pasta.id if pasta else "N/A")

        result_embed = discord.Embed(
            title="✅ Set Aprovado",
            description=f"{member.mention} aprovado por {approver.mention}.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        result_embed.set_thumbnail(url=member.display_avatar.url)
        if self.id_jogo:
            result_embed.add_field(name="🎮 ID no Jogo", value=f"`{self.id_jogo}`", inline=True)
        await interaction.followup.send(embed=result_embed)
