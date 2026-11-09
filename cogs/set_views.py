"""
cogs/set_views.py — SetModal, botões de aprovação, SetPanelView e rate-limit.

Cada solicitação de set é gravada em set_solicitacoes (services/
set_request_service.py). Os botões Aprovar/Reprovar são DynamicItems com o
id da solicitação no custom_id ("set:ap:<id>" / "set:rp:<id>"), então
continuam funcionando depois de qualquer restart do bot.

Mensagens antigas (custom_id "approval:aprovar"/"approval:reprovar") são
atendidas por LegacyApprovalView, que reconstrói o pedido a partir do embed.
"""

import logging
import re
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
from services import set_request_service as pedidos
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

        pendente = pedidos.pendente_do_usuario(guild_id, str(interaction.user.id))
        if pendente:
            await interaction.followup.send(
                "⏳ Você já tem uma solicitação de set aguardando decisão da liderança.",
                ephemeral=True,
            )
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

        solicitacao_id = pedidos.criar_solicitacao(
            guild_id, str(solicitante.id), self.membro_nome.value.strip(), self.id_jogo.value.strip()
        )
        try:
            msg = await approval_channel.send(embed=embed, view=build_approval_view(solicitacao_id))
        except Exception:
            pedidos.excluir_solicitacao(solicitacao_id)
            raise
        pedidos.salvar_mensagem(solicitacao_id, str(approval_channel.id), str(msg.id))

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


class SetDecisaoButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"set:(?P<acao>ap|rp):(?P<sid>[0-9]+)",
):
    """Botão Aprovar/Reprovar persistente: o id da solicitação vai no custom_id."""

    def __init__(self, acao: str, solicitacao_id: int) -> None:
        aprovar = acao == "ap"
        super().__init__(
            discord.ui.Button(
                label="✅ Aprovar" if aprovar else "❌ Reprovar",
                style=discord.ButtonStyle.success if aprovar else discord.ButtonStyle.danger,
                custom_id=f"set:{acao}:{solicitacao_id}",
            )
        )
        self.acao = acao
        self.solicitacao_id = solicitacao_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["acao"], int(match["sid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await decidir_set(interaction, self.solicitacao_id, aprovado=self.acao == "ap")


def build_approval_view(solicitacao_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(SetDecisaoButton("ap", solicitacao_id))
    view.add_item(SetDecisaoButton("rp", solicitacao_id))
    return view


def _check_permission(interaction: discord.Interaction) -> bool:
    approver_role_ids = db_get_approver_role_ids(str(interaction.guild_id))
    return has_approver_permission(interaction.user, approver_role_ids)


def _dados_do_embed_legado(message: discord.Message | None) -> dict | None:
    """Extrai solicitante, nome e ID do jogo do embed de um pedido antigo."""
    if message is None or not message.embeds:
        return None
    dados = {}
    for field in message.embeds[0].fields:
        nome = field.name or ""
        valor = (field.value or "").strip()
        if "ID no Jogo" in nome:
            dados["id_jogo"] = valor.strip("`").strip()
        elif "Nome" in nome:
            dados["nome"] = valor
        elif "Solicitante" in nome:
            ids = re.findall(r"[0-9]{15,22}", valor)
            if ids:
                dados["user_id"] = ids[-1]
    if {"id_jogo", "nome", "user_id"} <= dados.keys():
        return dados
    return None


class LegacyApprovalView(discord.ui.View):
    """Atende pedidos criados antes da persistência (custom_id fixo)."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _decidir(self, interaction: discord.Interaction, aprovado: bool) -> None:
        guild_id = str(interaction.guild_id)
        solicitacao = pedidos.get_por_mensagem(guild_id, str(interaction.message.id))
        if solicitacao is None:
            dados = _dados_do_embed_legado(interaction.message)
            if dados is None:
                await interaction.response.send_message(
                    "❌ Não consegui ler os dados desta solicitação antiga. Peça para o membro refazer o set.",
                    ephemeral=True,
                )
                return
            sid = pedidos.criar_solicitacao(guild_id, dados["user_id"], dados["nome"], dados["id_jogo"])
            pedidos.salvar_mensagem(sid, str(interaction.channel_id), str(interaction.message.id))
        else:
            sid = solicitacao["id"]
        await decidir_set(interaction, sid, aprovado)

    @discord.ui.button(label="✅ Aprovar", style=discord.ButtonStyle.success, custom_id="approval:aprovar")
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _check_permission(interaction):
            await interaction.response.send_message("❌ Sem permissão para aprovar.", ephemeral=True)
            return
        await self._decidir(interaction, aprovado=True)

    @discord.ui.button(label="❌ Reprovar", style=discord.ButtonStyle.danger, custom_id="approval:reprovar")
    async def reprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _check_permission(interaction):
            await interaction.response.send_message("❌ Sem permissão para reprovar.", ephemeral=True)
            return
        await self._decidir(interaction, aprovado=False)


async def decidir_set(interaction: discord.Interaction, solicitacao_id: int, aprovado: bool) -> None:
    acao = "aprovar" if aprovado else "reprovar"
    if not _check_permission(interaction):
        await interaction.response.send_message(f"❌ Sem permissão para {acao}.", ephemeral=True)
        return

    solicitacao = pedidos.get_solicitacao(solicitacao_id)
    if solicitacao is None or solicitacao["guild_id"] != str(interaction.guild_id):
        await interaction.response.send_message("❌ Solicitação não encontrada.", ephemeral=True)
        return
    if solicitacao["status"] != pedidos.PENDENTE:
        quem = f" por <@{solicitacao['decidido_por']}>" if solicitacao["decidido_por"] else ""
        await interaction.response.send_message(
            f"⚠️ Esta solicitação já está **{solicitacao['status']}**{quem}.", ephemeral=True
        )
        return
    if not pedidos.reservar(solicitacao_id, str(interaction.user.id)):
        await interaction.response.send_message("⏳ Já está sendo processada por outra pessoa.", ephemeral=True)
        return

    await interaction.response.defer()
    try:
        await _processar_set(interaction, solicitacao, aprovado)
    except Exception:
        pedidos.liberar(solicitacao_id)
        raise


async def _processar_set(interaction: discord.Interaction, solicitacao, aprovado: bool) -> None:
    guild    = interaction.guild
    guild_id = str(guild.id)
    approver = interaction.user
    target_user_id = int(solicitacao["user_id"])
    target_name    = solicitacao["nome"]
    id_jogo        = solicitacao["id_jogo"]

    try:
        await interaction.edit_original_response(view=None)
    except Exception as e:
        log.warning(f"Não foi possível remover view: {e}")

    _clear_pending(target_user_id)

    if not aprovado:
        embed = discord.Embed(
            title="❌ Set Reprovado",
            description=f"**{target_name}**\nReprovado por {approver.mention}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        pedidos.concluir(solicitacao["id"], pedidos.REPROVADO, str(approver.id))
        _audit("SET_REPROVADO", approver.id, target_user_id)
        await interaction.followup.send(embed=embed)
        return

    try:
        member = guild.get_member(target_user_id) or await guild.fetch_member(target_user_id)
    except discord.NotFound:
        pedidos.concluir(solicitacao["id"], pedidos.REPROVADO, str(approver.id))
        await interaction.followup.send(
            f"❌ Membro `{target_user_id}` não está mais no servidor. Solicitação encerrada.",
            ephemeral=True,
        )
        return
    except Exception as e:
        log.error(f"Erro ao buscar membro: {e}")
        pedidos.liberar(solicitacao["id"])
        await interaction.followup.send("❌ Erro ao buscar membro. Tente novamente.", ephemeral=True)
        return

    cfg               = db_get_guild_config(guild_id)
    member_role_id    = int(cfg["member_role_id"]) if cfg and cfg["member_role_id"] else None
    log_ch_id         = int(cfg["log_channel_id"]) if cfg and cfg["log_channel_id"] else None
    private_cat_id    = int(cfg["private_category_id"]) if cfg and cfg["private_category_id"] else None
    approver_role_ids = db_get_approver_role_ids(guild_id)

    member_role = guild.get_role(member_role_id) if member_role_id else None
    if member_role and member_role not in member.roles:
        try:
            await member.add_roles(member_role, reason=f"Set aprovado por {approver}")
        except Exception as e:
            log.error(f"Erro ao aplicar cargo: {e}")

    pedir_set_role = guild.get_role(1474869320659107853)
    if pedir_set_role and pedir_set_role in member.roles:
        try:
            await member.remove_roles(pedir_set_role, reason=f"Set aprovado por {approver}")
        except Exception as e:
            log.error(f"Erro ao remover cargo 'Pedir Set': {e}")

    # FIX: nome do canal duplicando ID do jogo
    # Canal privado criado ANTES de definir o apelido para que
    # member.display_name não contenha ainda o id_jogo ao montar o nome.
    existing_ch_id = db_channel_map_get(guild_id, str(target_user_id))
    pasta   = None
    created = False

    if existing_ch_id:
        pasta = guild.get_channel(existing_ch_id) or await safe_fetch_channel(guild, existing_ch_id)
        if pasta is None:
            pasta   = await criar_pasta(guild, member, approver, private_cat_id, approver_role_ids, id_jogo, target_name)
            created = True
            if pasta:
                db_channel_map_set(guild_id, str(target_user_id), pasta.id)
    else:
        pasta   = await criar_pasta(guild, member, approver, private_cat_id, approver_role_ids, id_jogo, target_name)
        created = True
        if pasta:
            db_channel_map_set(guild_id, str(target_user_id), pasta.id)

    if id_jogo:
        novo_nick = f"{target_name} | {id_jogo}"[:32]
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
        log_embed.add_field(name="🎮 ID no Jogo",    value=f"`{id_jogo}`" if id_jogo else "N/A", inline=True)
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
        if id_jogo:
            farm_embed.add_field(name="🎮 ID no Jogo", value=f"`{id_jogo}`", inline=True)
        farm_embed.add_field(name="\u200b", value="\u200b", inline=False)
        farm_embed.add_field(
            name="1️⃣ Escolha o tipo certo",
            value=(
                "**🚜 Lançar Farm:** use quando a meta for o Kit Desmanche "
                "com Borracha, Aluminio, Cobre ou Plastico.\n"
                "**💵 Lançar Dinheiro:** use quando a meta da semana for em dinheiro "
                "sujo, dinheiro limpo ou os dois."
            ),
            inline=False,
        )
        farm_embed.add_field(
            name="2️⃣ Faça o lançamento",
            value=(
                "Vá ao canal do **Painel de Farm/Painel de Operações**, clique no botão correto "
                "e preencha apenas os campos que você realmente entregou.\n"
                "Use números inteiros nos itens. Para dinheiro, pode usar `50000` ou `R$ 50.000`."
            ),
            inline=False,
        )
        farm_embed.add_field(
            name="3️⃣ Envie o print obrigatório",
            value=(
                "Depois de confirmar o modal, o bot vai pedir o print no mesmo canal. "
                "Envie uma imagem em até **3 minutos**.\n"
                "O farm só é registrado depois que o print é recebido. Se o tempo acabar, "
                "nada será salvo e você precisará lançar novamente."
            ),
            inline=False,
        )
        farm_embed.add_field(
            name="📊 Conferir ou corrigir",
            value=(
                "Use **📊 Ver Meu Farm** ou o comando `/farm` para acompanhar sua meta, "
                "porcentagem e último lançamento.\n"
                "Se lançar errado, abra `/farm` e use **✏️ Editar último**. "
                "Se precisar alterar um lançamento antigo, chame a liderança."
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

    pedidos.concluir(solicitacao["id"], pedidos.APROVADO, str(approver.id))
    _audit("SET_APROVADO", approver.id, member.id, id_jogo=id_jogo, canal=pasta.id if pasta else "N/A")

    result_embed = discord.Embed(
        title="✅ Set Aprovado",
        description=f"{member.mention} aprovado por {approver.mention}.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    result_embed.set_thumbnail(url=member.display_avatar.url)
    if id_jogo:
        result_embed.add_field(name="🎮 ID no Jogo", value=f"`{id_jogo}`", inline=True)
    await interaction.followup.send(embed=result_embed)
