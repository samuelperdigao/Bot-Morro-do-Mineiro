"""
cogs/encomenda.py - Sistema de Encomendas (fluxo Registro → Pedidos → Entregues).

EncomendaPainelView      → painel fixo com botão "📦 Registrar Encomenda"
PedidoView               → embed vivo em #pedidos com botões de status (persistente)
/setup_encomenda_painel  → posta o painel no canal de encomendas configurado
/setup_encomenda_canais  → define os canais #pedidos e #entregues
/encomenda               → abre o modal diretamente (legado)

As regras (validação, numeração, transições) ficam em services/encomenda_core.py.
O pedido é localizado pelo ID da mensagem em #pedidos, nunca pelo custom_id.
Quem pode mudar o status é definido pelo acesso ao canal #pedidos no Discord.
"""

from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from services.db_service import (
    db_get_encomenda_canais,
    db_get_guild_config,
    db_get_system_config,
    db_set_encomenda_canais,
    get_conn,
)
from services.encomenda_core import (
    STATUS_FINAIS,
    STATUS_LABEL,
    EncomendaDesatualizadaError,
    EncomendaNaoEncontradaError,
    EncomendaRepository,
    TransicaoInvalidaError,
    format_brl,
    formatar_numero,
    parse_quantidade,
    parse_valor_centavos,
    status_com_emoji,
    transicao_permitida,
)
from services.log_service import send_log

log = get_logger("encomenda", "encomenda.log")

COR_ENCOMENDA = discord.Color.from_rgb(230, 126, 34)
CORES_STATUS = {
    "pendente": discord.Color.from_rgb(230, 126, 34),
    "em_producao": discord.Color.from_rgb(52, 152, 219),
    "pronta": discord.Color.from_rgb(241, 196, 15),
    "entregue": discord.Color.from_rgb(46, 204, 113),
    "cancelada": discord.Color.from_rgb(231, 76, 60),
}

PEDIDO_CUSTOM_ID_PREFIXO = "encomenda_pedido:"
ACOES_PEDIDO = {
    "producao": "em_producao",
    "pronta": "pronta",
    "entregue": "entregue",
    "cancelar": "cancelada",
}

FOOTER_ENCOMENDAS = "Morro do Mineiro — Encomendas"
MSG_CANAIS_NAO_CONFIGURADOS = "❌ Canais não configurados. Use `/setup_encomenda_canais`."
MSG_DESATUALIZADA = "⚠️ Alguém já atualizou esta encomenda. Atualize a tela."
MSG_NAO_ENCONTRADA = "❌ Encomenda não encontrada no banco."

MENCOES_USUARIOS = discord.AllowedMentions(users=True, roles=False, everyone=False)


def _repo() -> EncomendaRepository:
    return EncomendaRepository(get_conn())


# ── Helpers de canal e permissão ──────────────────────────────────────────────

async def _resolver_canal(guild: discord.Guild, channel_id: str | int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    canal = guild.get_channel(int(channel_id))
    if canal is None:
        try:
            canal = await guild.fetch_channel(int(channel_id))
        except Exception:
            return None
    return canal if isinstance(canal, discord.TextChannel) else None


def _permissoes_faltando(canal: discord.TextChannel) -> list[str]:
    perms = canal.permissions_for(canal.guild.me)
    faltando = []
    if not perms.view_channel:
        faltando.append("ver o canal")
    if not perms.send_messages:
        faltando.append("enviar mensagens")
    if not perms.embed_links:
        faltando.append("inserir links (embeds)")
    return faltando


async def _canal_pedidos(guild: discord.Guild) -> tuple[discord.TextChannel | None, str | None]:
    pedidos_id, _ = db_get_encomenda_canais(str(guild.id))
    canal = await _resolver_canal(guild, pedidos_id)
    if canal is None:
        return None, MSG_CANAIS_NAO_CONFIGURADOS
    faltando = _permissoes_faltando(canal)
    if faltando:
        return None, f"❌ O bot não tem permissão para {', '.join(faltando)} em {canal.mention}."
    return canal, None


async def _canal_entregues(guild: discord.Guild) -> tuple[discord.TextChannel | None, str | None]:
    _, entregues_id = db_get_encomenda_canais(str(guild.id))
    canal = await _resolver_canal(guild, entregues_id)
    if canal is None:
        return None, (
            "❌ O canal de entregues não está configurado ou não foi encontrado. "
            "Nada foi alterado. Use `/setup_encomenda_canais`."
        )
    faltando = _permissoes_faltando(canal)
    if faltando:
        return None, (
            f"❌ O bot não tem permissão para {', '.join(faltando)} em {canal.mention}. "
            "Nada foi alterado."
        )
    return canal, None


async def _get_encomenda_channel(guild: discord.Guild, guild_id: str) -> discord.TextChannel | None:
    """Canal do painel de registro: prioriza system_config, depois guild_config."""
    row = db_get_system_config(guild_id, "encomenda")
    if row and row["canal_interacao_id"]:
        canal = await _resolver_canal(guild, row["canal_interacao_id"])
        if canal:
            return canal

    cfg = db_get_guild_config(guild_id)
    if cfg and cfg["canal_encomendas_id"]:
        return await _resolver_canal(guild, cfg["canal_encomendas_id"])
    return None


def _pedidos_configurado(guild_id: str) -> bool:
    pedidos_id, _ = db_get_encomenda_canais(guild_id)
    return bool(pedidos_id)


async def _mensagem_pedido(guild: discord.Guild, row) -> discord.PartialMessage | None:
    if not row["pedidos_channel_id"] or not row["pedidos_message_id"]:
        return None
    canal = await _resolver_canal(guild, row["pedidos_channel_id"])
    if canal is None:
        return None
    return canal.get_partial_message(int(row["pedidos_message_id"]))


# ── Embed ─────────────────────────────────────────────────────────────────────

def _parse_iso(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def build_embed(row, guild: discord.Guild | None, *, finalizado_por_id: str | None = None) -> discord.Embed:
    """Embed da encomenda, usado em #pedidos e em #entregues."""
    status = row["status"]
    embed = discord.Embed(
        title=f"📦 Encomenda {formatar_numero(row['numero'])}",
        color=CORES_STATUS.get(status, COR_ENCOMENDA),
        timestamp=_parse_iso(row["atualizado_em"]),
    )
    if guild is not None:
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.add_field(name="👨‍👩‍👧‍👦 Família", value=row["familia"], inline=False)
    embed.add_field(name="📊 Quantidade", value=f"`{row['quantidade']}`", inline=True)
    embed.add_field(name="💰 Valor", value=f"`{format_brl(row['valor_centavos'])}`", inline=True)
    embed.add_field(name="📅 Data", value=f"`{row['data']}`", inline=True)
    embed.add_field(name="📌 Status", value=status_com_emoji(status), inline=True)
    embed.add_field(name="🙋 Solicitante", value=f"<@{row['solicitante_id']}>", inline=True)
    responsavel = f"<@{row['responsavel_id']}>" if row["responsavel_id"] else "—"
    embed.add_field(name="🛠️ Responsável", value=responsavel, inline=True)
    if finalizado_por_id and status in STATUS_FINAIS:
        rotulo = "❌ Cancelada por" if status == "cancelada" else "✅ Entregue por"
        embed.add_field(name=rotulo, value=f"<@{finalizado_por_id}>", inline=True)
    if row["observacao"]:
        embed.add_field(name="📝 Observação", value=row["observacao"], inline=False)
    embed.set_footer(text=FOOTER_ENCOMENDAS)
    return embed


# ── Notificações e logs ───────────────────────────────────────────────────────

async def _notificar_solicitante(client: discord.Client, guild: discord.Guild, row) -> bool:
    """Tenta avisar o solicitante por DM. Nunca levanta exceção."""
    try:
        user_id = int(row["solicitante_id"])
        destino = guild.get_member(user_id) or await client.fetch_user(user_id)
        embed = discord.Embed(
            title=f"📦 Encomenda {formatar_numero(row['numero'])} — {STATUS_LABEL[row['status']]}",
            description=(
                f"Sua encomenda da família **{row['familia']}** em **{guild.name}** "
                f"mudou para **{status_com_emoji(row['status'])}**."
            ),
            color=CORES_STATUS.get(row["status"], COR_ENCOMENDA),
        )
        embed.set_footer(text=FOOTER_ENCOMENDAS)
        await destino.send(embed=embed)
        return True
    except Exception as exc:
        log.info("DM ao solicitante da encomenda %s não enviada: %s", row["id"], exc)
        return False


async def _log_encomenda(client, guild: discord.Guild, titulo: str, row, autor: discord.abc.User, extra: str | None = None):
    try:
        embed = discord.Embed(
            title=titulo,
            color=CORES_STATUS.get(row["status"], COR_ENCOMENDA),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📦 Encomenda", value=formatar_numero(row["numero"]), inline=True)
        embed.add_field(name="👨‍👩‍👧‍👦 Família", value=row["familia"], inline=True)
        embed.add_field(name="📌 Status", value=extra or status_com_emoji(row["status"]), inline=True)
        embed.add_field(name="👤 Por", value=f"{autor.mention}\n`{autor.id}`", inline=True)
        embed.set_footer(text="Morro do Mineiro — Sistema de Encomenda")
        await send_log(client, guild, "encomenda", embed)
    except Exception as exc:
        log.warning("Falha ao enviar log da encomenda %s: %s", row["id"], exc)


async def _ressincronizar_pedido(guild: discord.Guild, row) -> None:
    """Reescreve a mensagem em #pedidos com o estado atual do banco."""
    if row is None:
        return
    mensagem = await _mensagem_pedido(guild, row)
    if mensagem is None:
        return
    try:
        await mensagem.edit(embed=build_embed(row, guild), view=PedidoView(row["status"]))
    except discord.NotFound:
        pass
    except Exception as exc:
        log.warning("Falha ao ressincronizar encomenda %s: %s", row["id"], exc)


async def _responder_ephemeral(interaction: discord.Interaction, texto: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(texto, ephemeral=True)
    else:
        await interaction.response.send_message(texto, ephemeral=True)


# ── Modal ─────────────────────────────────────────────────────────────────────

class EncomendaModal(discord.ui.Modal, title="📦 Registrar Encomenda"):
    familia = discord.ui.TextInput(
        label="Família",
        placeholder="Ex: Família Silva",
        max_length=100,
    )
    quantidade = discord.ui.TextInput(
        label="Quantidade",
        placeholder="Ex: 50",
        max_length=20,
    )
    valor = discord.ui.TextInput(
        label="Valor (R$)",
        placeholder="Ex: 1.500,00",
        max_length=30,
    )
    data = discord.ui.TextInput(
        label="Data da Encomenda",
        placeholder=f"Ex: {DATE_BR_EXAMPLE}",
        max_length=10,
    )
    observacao = discord.ui.TextInput(
        label="Observação (opcional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            familia = self.familia.value.strip()
            if not familia:
                raise ValueError("Informe a família.")
            quantidade = parse_quantidade(self.quantidade.value)
            valor_centavos = parse_valor_centavos(self.valor.value)
            data_val = normalize_date_br(self.data.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        observacao = (self.observacao.value or "").strip() or None

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        canal, erro = await _canal_pedidos(guild)
        if erro:
            await interaction.followup.send(erro, ephemeral=True)
            return

        repo = _repo()
        row = repo.criar(
            str(guild.id), familia, quantidade, valor_centavos, data_val,
            observacao, str(interaction.user.id),
        )
        numero = formatar_numero(row["numero"])

        try:
            mensagem = await canal.send(embed=build_embed(row, guild), view=PedidoView(row["status"]))
        except Exception as exc:
            repo.excluir(row["id"])
            log.error("Falha ao postar encomenda %s em #%s: %s", numero, canal.id, exc, exc_info=True)
            await interaction.followup.send(
                f"❌ Não consegui postar o pedido em {canal.mention}. Nada foi registrado. "
                "Verifique as permissões do bot e tente novamente.",
                ephemeral=True,
            )
            return

        try:
            repo.salvar_mensagem_pedidos(row["id"], canal.id, mensagem.id)
        except Exception as exc:
            log.error("Falha ao vincular mensagem da encomenda %s: %s", numero, exc, exc_info=True)
            try:
                await mensagem.delete()
            except Exception:
                pass
            repo.excluir(row["id"])
            await interaction.followup.send("❌ Erro ao salvar a encomenda. Nada foi registrado.", ephemeral=True)
            return

        log.info(
            "Encomenda %s registrada por %s (%s) — guild %s",
            numero, interaction.user, interaction.user.id, guild.id,
        )
        await interaction.followup.send(f"✅ Encomenda {numero} registrada em {canal.mention}", ephemeral=True)
        await _log_encomenda(interaction.client, guild, "📦 Encomenda Registrada", row, interaction.user)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no EncomendaModal: %s", error, exc_info=True)
        try:
            await _responder_ephemeral(interaction, "❌ Erro interno. Tente novamente.")
        except Exception:
            pass


# ── View do pedido (persistente) ──────────────────────────────────────────────

class PedidoView(discord.ui.View):
    """Botões de status do pedido. `status=None` registra a view persistente."""

    def __init__(self, status: str | None = None):
        super().__init__(timeout=None)
        if status is not None:
            for item in self.children:
                acao = item.custom_id.removeprefix(PEDIDO_CUSTOM_ID_PREFIXO)
                item.disabled = not transicao_permitida(status, ACOES_PEDIDO[acao])

    @discord.ui.button(
        label="Em produção", emoji="🔨",
        style=discord.ButtonStyle.primary,
        custom_id="encomenda_pedido:producao",
    )
    async def producao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _tratar_botao_pedido(interaction, "producao")

    @discord.ui.button(
        label="Pronta", emoji="📦",
        style=discord.ButtonStyle.secondary,
        custom_id="encomenda_pedido:pronta",
    )
    async def pronta(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _tratar_botao_pedido(interaction, "pronta")

    @discord.ui.button(
        label="Entregue", emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="encomenda_pedido:entregue",
    )
    async def entregue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _tratar_botao_pedido(interaction, "entregue")

    @discord.ui.button(
        label="Cancelar", emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="encomenda_pedido:cancelar",
    )
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _tratar_botao_pedido(interaction, "cancelar")

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        log.error("Erro no botão %s da encomenda: %s", getattr(item, "custom_id", "?"), error, exc_info=True)
        try:
            await _responder_ephemeral(interaction, "❌ Erro interno. Tente novamente.")
        except Exception:
            pass


async def _tratar_botao_pedido(interaction: discord.Interaction, acao: str) -> None:
    novo_status = ACOES_PEDIDO[acao]
    repo = _repo()
    row = repo.obter_por_mensagem_pedidos(interaction.message.id)
    if row is None:
        await interaction.response.send_message(MSG_NAO_ENCONTRADA, ephemeral=True)
        return

    guild = interaction.guild
    status_atual = row["status"]
    if not transicao_permitida(status_atual, novo_status):
        await interaction.response.send_message(MSG_DESATUALIZADA, ephemeral=True)
        await _ressincronizar_pedido(guild, row)
        return

    if novo_status in STATUS_FINAIS:
        _, erro = await _canal_entregues(guild)
        if erro:
            await interaction.response.send_message(erro, ephemeral=True)
            return
        view = ConfirmarFinalizacaoView(row["id"], novo_status, status_atual, interaction.user.id)
        verbo = "**entregue**" if novo_status == "entregue" else "**cancelada**"
        await interaction.response.send_message(
            f"Confirmar que a encomenda {formatar_numero(row['numero'])} "
            f"({row['familia']}) foi {verbo}? Esta ação não pode ser desfeita.",
            view=view,
            ephemeral=True,
        )
        view.interacao_origem = interaction
        return

    try:
        atualizado = repo.transitar(
            row["id"], novo_status, str(interaction.user.id), status_esperado=status_atual,
        )
    except (EncomendaDesatualizadaError, TransicaoInvalidaError):
        await interaction.response.send_message(MSG_DESATUALIZADA, ephemeral=True)
        await _ressincronizar_pedido(guild, repo.obter(row["id"]))
        return
    except EncomendaNaoEncontradaError:
        await interaction.response.send_message(MSG_NAO_ENCONTRADA, ephemeral=True)
        return

    await interaction.response.edit_message(
        embed=build_embed(atualizado, guild), view=PedidoView(atualizado["status"]),
    )
    log.info(
        "Encomenda %s: %s → %s por %s",
        formatar_numero(atualizado["numero"]), status_atual, novo_status, interaction.user.id,
    )
    await _notificar_solicitante(interaction.client, guild, atualizado)
    await _log_encomenda(
        interaction.client, guild, "📦 Encomenda Atualizada", atualizado, interaction.user,
        extra=f"{status_com_emoji(status_atual)} → {status_com_emoji(novo_status)}",
    )


# ── Confirmação de Entregue / Cancelar ────────────────────────────────────────

class ConfirmarFinalizacaoView(discord.ui.View):
    def __init__(self, encomenda_id: int, novo_status: str, status_esperado: str, autor_id: int):
        super().__init__(timeout=60)
        self.encomenda_id = encomenda_id
        self.novo_status = novo_status
        self.status_esperado = status_esperado
        self.autor_id = autor_id
        self.interacao_origem: discord.Interaction | None = None
        self._usada = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Só quem iniciou pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._usada:
            await interaction.response.defer()
            return
        self._usada = True
        self.stop()
        await interaction.response.edit_message(content="⏳ Finalizando encomenda...", view=None)
        resultado = await _finalizar_encomenda(
            interaction, self.encomenda_id, self.novo_status, self.status_esperado,
        )
        await interaction.edit_original_response(content=resultado)

    @discord.ui.button(label="Voltar", style=discord.ButtonStyle.secondary)
    async def voltar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._usada = True
        self.stop()
        await interaction.response.edit_message(content="↩️ Operação cancelada. Nada foi alterado.", view=None)

    async def on_timeout(self):
        if self._usada or self.interacao_origem is None:
            return
        try:
            await self.interacao_origem.edit_original_response(
                content="⏱️ Confirmação expirada. Nada foi alterado.", view=None,
            )
        except Exception:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        log.error("Erro na confirmação da encomenda %s: %s", self.encomenda_id, error, exc_info=True)
        try:
            await _responder_ephemeral(interaction, "❌ Erro interno. Confira o estado da encomenda.")
        except Exception:
            pass


async def _finalizar_encomenda(
    interaction: discord.Interaction,
    encomenda_id: int,
    novo_status: str,
    status_esperado: str,
) -> str:
    """Finaliza (entregue/cancelada), arquiva em #entregues e apaga de #pedidos."""
    guild = interaction.guild
    user_id = str(interaction.user.id)

    canal_entregues, erro = await _canal_entregues(guild)
    if erro:
        return erro

    repo = _repo()
    try:
        row = repo.transitar(encomenda_id, novo_status, user_id, status_esperado=status_esperado)
    except (EncomendaDesatualizadaError, TransicaoInvalidaError):
        await _ressincronizar_pedido(guild, repo.obter(encomenda_id))
        return MSG_DESATUALIZADA
    except EncomendaNaoEncontradaError:
        return MSG_NAO_ENCONTRADA

    numero = formatar_numero(row["numero"])
    rotulo = STATUS_LABEL[novo_status]
    log.info("Encomenda %s: %s → %s por %s", numero, status_esperado, novo_status, user_id)

    dm_enviada = await _notificar_solicitante(interaction.client, guild, row)
    try:
        arquivo = await canal_entregues.send(
            content=None if dm_enviada else f"<@{row['solicitante_id']}>",
            embed=build_embed(row, guild, finalizado_por_id=user_id),
            allowed_mentions=MENCOES_USUARIOS,
        )
    except Exception as exc:
        log.error("Falha ao arquivar encomenda %s em #%s: %s", numero, canal_entregues.id, exc, exc_info=True)
        repo.registrar_erro(row["id"], user_id, f"Falha ao postar em #entregues: {exc}")
        # O pedido fica em #pedidos já com o status final e sem ações.
        await _ressincronizar_pedido(guild, row)
        await _log_encomenda(
            interaction.client, guild, f"⚠️ Encomenda {rotulo} sem arquivo", row, interaction.user,
        )
        return (
            f"⚠️ Encomenda {numero} marcada como **{rotulo}**, mas não consegui postar em "
            f"{canal_entregues.mention}. O pedido ficou em #pedidos sem botões."
        )

    repo.salvar_mensagem_arquivo(row["id"], canal_entregues.id, arquivo.id)

    mensagem_pedido = await _mensagem_pedido(guild, row)
    if mensagem_pedido is not None:
        try:
            await mensagem_pedido.delete()
        except discord.NotFound:
            pass
        except Exception as exc:
            log.warning("Falha ao apagar pedido %s de #pedidos: %s", numero, exc)
            repo.registrar_erro(row["id"], user_id, f"Falha ao apagar mensagem em #pedidos: {exc}")
            await _ressincronizar_pedido(guild, row)

    await _log_encomenda(
        interaction.client, guild, f"📦 Encomenda {rotulo}", row, interaction.user,
        extra=f"{status_com_emoji(status_esperado)} → {status_com_emoji(novo_status)}",
    )
    return f"✅ Encomenda {numero} marcada como **{rotulo}** e arquivada em {canal_entregues.mention}."


# ── View (painel fixo) ────────────────────────────────────────────────────────

class EncomendaPainelView(discord.ui.View):
    """View persistente do painel de encomendas."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📦 Registrar Encomenda",
        style=discord.ButtonStyle.primary,
        custom_id="encomenda_painel:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _pedidos_configurado(str(interaction.guild_id)):
            await interaction.response.send_message(MSG_CANAIS_NAO_CONFIGURADOS, ephemeral=True)
            return
        await interaction.response.send_modal(EncomendaModal())


def build_painel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📦 Painel de Encomendas",
        description=(
            "Clique no botão abaixo para registrar uma nova encomenda.\n\n"
            "**Como funciona:**\n"
            "1️⃣ Preencha família, quantidade, valor, data e observação.\n"
            "2️⃣ A encomenda recebe um número (#001, #002…) e aparece em **#pedidos**.\n"
            "3️⃣ A liderança atualiza o status: Em produção → Pronta → Entregue.\n"
            "4️⃣ Ao ser entregue ou cancelada, ela é arquivada em **#entregues**.\n\n"
            "Você recebe um aviso por DM a cada mudança de status."
        ),
        color=COR_ENCOMENDA,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Morro do Mineiro — Sistema de Encomendas")
    return embed


# ── Cog ───────────────────────────────────────────────────────────────────────

class EncomendaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(EncomendaPainelView())
        bot.add_view(PedidoView())
        log.info("EncomendaCog inicializado.")

    @app_commands.command(
        name="setup_encomenda_painel",
        description="Posta o painel de encomendas no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_encomenda_painel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        canal = await _get_encomenda_channel(interaction.guild, guild_id)
        if canal is None:
            await interaction.response.send_message(
                "❌ Canal de encomendas não configurado ou não encontrado.\n"
                "Use `/setup_encomenda_canais` para escolher o canal do painel.",
                ephemeral=True,
            )
            return

        await canal.send(embed=build_painel_embed(), view=EncomendaPainelView())
        aviso = ""
        if not _pedidos_configurado(guild_id):
            aviso = "\n⚠️ Os canais #pedidos/#entregues ainda não foram definidos. Use `/setup_encomenda_canais`."
        await interaction.response.send_message(
            f"✅ Painel de encomendas postado em {canal.mention}!{aviso}", ephemeral=True
        )
        log.info("Painel de encomendas postado em #%s (guild %s) por %s", canal.name, guild_id, interaction.user)

    @setup_encomenda_painel.error
    async def setup_encomenda_painel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_encomenda_painel: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)

    @app_commands.command(
        name="setup_encomenda_canais",
        description="Define os canais do painel, dos pedidos ativos e das encomendas entregues.",
    )
    @app_commands.describe(
        painel="Canal do painel fixo com o botão Registrar Encomenda",
        pedidos="Canal onde ficam as encomendas em andamento (com botões de status)",
        entregues="Canal de arquivo das encomendas entregues ou canceladas",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_encomenda_canais(
        self,
        interaction: discord.Interaction,
        painel: discord.TextChannel,
        pedidos: discord.TextChannel,
        entregues: discord.TextChannel,
    ):
        if pedidos.id == entregues.id:
            await interaction.response.send_message(
                "❌ Os canais de pedidos e de entregues precisam ser diferentes.", ephemeral=True
            )
            return

        problemas = []
        for canal in {painel.id: painel, pedidos.id: pedidos, entregues.id: entregues}.values():
            faltando = _permissoes_faltando(canal)
            if faltando:
                problemas.append(f"{canal.mention}: {', '.join(faltando)}")
        if problemas:
            await interaction.response.send_message(
                "❌ O bot não tem as permissões necessárias:\n" + "\n".join(problemas),
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)
        db_set_encomenda_canais(guild_id, str(pedidos.id), str(entregues.id), str(painel.id))
        log.info(
            "Canais de encomenda definidos (painel=%s, pedidos=%s, entregues=%s) — guild %s por %s",
            painel.id, pedidos.id, entregues.id, guild_id, interaction.user,
        )

        embed = discord.Embed(
            title="✅ Canais de Encomendas Configurados",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="🧾 Painel", value=painel.mention, inline=True)
        embed.add_field(name="📋 Pedidos", value=pedidos.mention, inline=True)
        embed.add_field(name="📦 Entregues", value=entregues.mention, inline=True)
        embed.add_field(
            name="Próximo passo",
            value="Use `/setup_encomenda_painel` para postar o painel no canal escolhido.",
            inline=False,
        )
        embed.set_footer(text=f"Configurado por {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_encomenda_canais.error
    async def setup_encomenda_canais_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error("Erro no /setup_encomenda_canais: %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro.", ephemeral=True)

    @app_commands.command(
        name="encomenda",
        description="Registra uma nova encomenda no canal configurado.",
    )
    async def cmd_encomenda(self, interaction: discord.Interaction):
        if not _pedidos_configurado(str(interaction.guild_id)):
            await interaction.response.send_message(MSG_CANAIS_NAO_CONFIGURADOS, ephemeral=True)
            return
        await interaction.response.send_modal(EncomendaModal())

    @cmd_encomenda.error
    async def cmd_encomenda_error(self, interaction: discord.Interaction, error):
        log.error("Erro em /encomenda: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EncomendaCog(bot))
    log.info("EncomendaCog adicionado ao bot.")
