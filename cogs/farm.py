"""
cogs/farm.py - Extensão FARM: metas semanais, lançamentos e aprovações.
"""

import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.date_utils import format_date_br, format_week_range_br, week_id_from_date_br
from core.farm_policy import FARM_TICKET_ONLY_MESSAGE
from core.logger import get_logger
from core.permissions import is_lideranca, is_permitido_farm
from core.role_promotion import promote_role
from core.command_config import is_enabled as _cmd_enabled
from cogs.colete import MATERIAIS_POR_COLETE
from services.log_service import send_log
from services.set_service import MemberFolderError, resolve_member_folder
from services.db_service import (
    DINHEIRO_ITEMS, DINHEIRO_LIMPO_ITEM, DINHEIRO_SUJO_ITEM,
    init_db, current_week_id, now_tz, janela_valida, fmt_dt,
    db_meta_dinheiro_ativo, db_meta_dinheiro_itens_ativos, db_meta_itens_ativos,
    db_meta_tipo_efetivo, db_prog_itens, db_evento_itens, db_get_ultimo_evento,
    db_get_meta, db_set_meta, db_set_meta_dinheiro,
    db_get_progresso, db_ensure_progresso, db_lancar,
    db_editar_evento, db_editar_ultimo_evento, db_verificar_conclusao,
    db_salvar_painel, db_limpar_painel, db_aprovar,
    db_lista_progresso, db_eventos_usuario, db_ranking_semana,
    db_get_guild_config,
    db_is_farm_configured,
    db_get_lideranca_role_ids,
    db_get_permitidos_role_ids,
    db_all_configured_guilds,
    classificar_resultado,
)

log       = get_logger("farm", "farm.log")
audit_log = logging.getLogger("audit")
META_AVISOS_CHANNEL_ID = 1474869321506488447
EVERYONE_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=True,
    users=False,
    roles=False,
    replied_user=False,
)
FARM_PRINT_TIMEOUT_SECONDS = 180.0
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

BASE_DIR = Path(__file__).resolve().parent.parent
# A primeira imagem existente é usada; o logo das advertências serve de reserva
# para o aviso nunca sair sem a marca do Morro.
META_APROVADA_IMAGE_PATHS = (
    BASE_DIR / "assets" / "farm" / "meta-aprovada.png",
    BASE_DIR / "assets" / "farm" / "meta-aprovada.jpg",
    BASE_DIR / "assets" / "farm_advertencias" / "logo.jpg",
)
FARM_EXTRA_ITEM = "Ferro"
COLETE_MATERIAL_EMOJIS = {
    "ferro": "🔩",
    "plastico": "🧴",
    "tecido": "🧵",
    "aluminio": "⚙️",
    "borracha": "🛞",
}
COLETE_PRODUTOS = [
    (nome.title(), COLETE_MATERIAL_EMOJIS[nome])
    for nome in MATERIAIS_POR_COLETE
]
COLETE_PLACEHOLDERS = {
    nome.title(): f"{quantidade} por colete"
    for nome, quantidade in MATERIAIS_POR_COLETE.items()
}


def _parse_money(raw: str) -> float:
    raw = (raw or "0").strip()
    raw = raw.replace("R$", "").replace(".", "").replace(",", ".").strip()
    return float(raw or 0)


def _fmt_money(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def _fmt_qtd(valor: int | float) -> str:
    return f"{valor:g}" if isinstance(valor, float) else str(valor)


def _week_id_consulta(semana: str | None) -> str:
    if not semana or not semana.strip():
        return current_week_id()
    return week_id_from_date_br(semana)


def _format_entregas_separadas(
    prog_itens: dict,
    meta_itens: dict | None = None,
    *,
    dinheiro: bool = False,
) -> str:
    meta_itens = meta_itens or {}
    nomes = list(meta_itens.keys())
    nomes.extend(nome for nome in prog_itens if nome not in nomes and (prog_itens.get(nome, 0) or 0) > 0)
    if not nomes and dinheiro:
        nomes = [nome for nome in DINHEIRO_ITEMS if (prog_itens.get(nome, 0) or 0) > 0]

    linhas = []
    for nome in nomes:
        entregue = prog_itens.get(nome, 0) or 0
        meta = meta_itens.get(nome, 0) or 0
        if entregue <= 0 and meta <= 0:
            continue

        entregue_txt = _fmt_money(entregue) if dinheiro else _fmt_qtd(entregue)
        if meta > 0:
            meta_txt = _fmt_money(meta) if dinheiro else _fmt_qtd(meta)
            pct = entregue / meta * 100
            linhas.append(f"**{nome}**: `{entregue_txt}` / `{meta_txt}` ({pct:.0f}%)")
        else:
            linhas.append(f"**{nome}**: `{entregue_txt}`")

    texto = "\n".join(linhas) or "_nenhuma entrega registrada_"
    if len(texto) <= 1024:
        return texto
    return texto[:1000].rsplit("\n", 1)[0] + "\n*...*"


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    if content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


async def _aguardar_print_farm(
    interaction: discord.Interaction,
    descricao: str,
) -> tuple[discord.Message | None, discord.File | None]:
    await interaction.response.send_message(
        f"Envie o print do {descricao} neste canal em ate "
        f"**{int(FARM_PRINT_TIMEOUT_SECONDS / 60)} minutos**.\n"
        "O lancamento so sera registrado depois que a imagem for recebida.",
        ephemeral=True,
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
            timeout=FARM_PRINT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        await interaction.followup.send(
            "Tempo esgotado. Nenhum print foi recebido e nada foi registrado.",
            ephemeral=True,
        )
        return None, None

    print_attachment = next(att for att in msg.attachments if _is_image_attachment(att))
    try:
        return msg, await print_attachment.to_file(use_cached=True)
    except Exception:
        log.error("Erro ao baixar print de farm", exc_info=True)
        await interaction.followup.send(
            "Nao consegui baixar a imagem enviada. Tente lancar o farm novamente.",
            ephemeral=True,
        )
        return None, None

def _farm_audit(action: str, executor_id: int, target_id: int | None = None, **kwargs):
    parts = [f"action={action}", f"executor={executor_id}"]
    if target_id:
        parts.append(f"target={target_id}")
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    audit_log.info(" | ".join(parts))


from cogs.farm_embeds import FARM_PRODUTOS, build_farm_embed, build_meta_embed, build_ranking_embed


class DefinirMetasModal(discord.ui.Modal):
    """
    Modal com campos fixos para cada produto definido em FARM_PRODUTOS.
    Pré-preenche com os valores atuais da meta.
    """

    def __init__(
        self,
        cog: "FarmCog",
        week_id: str,
        guild_id: str,
        meta=None,
        *,
        produtos=None,
        meta_tipo: str = "itens",
        titulo: str = "Kit Desmanche",
        placeholders: dict[str, str] | None = None,
    ):
        super().__init__(title=titulo)
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        self.produtos = produtos or FARM_PRODUTOS
        self.meta_tipo = meta_tipo
        self.titulo = titulo
        self.placeholders = placeholders or {}

        itens_atuais = (
            db_meta_itens_ativos(meta)
            if meta and db_meta_tipo_efetivo(meta) == self.meta_tipo
            else {}
        )
        self._inputs: list[tuple[str, discord.ui.TextInput]] = []

        for nome, emoji in self.produtos:
            val_atual = itens_atuais.get(nome, 0)
            ti = discord.ui.TextInput(
                label=f"{emoji} {nome}",
                style=discord.TextStyle.short,
                placeholder=self.placeholders.get(nome, "0"),
                default=str(val_atual) if val_atual else None,
                required=False,
                max_length=10,
            )
            self.add_item(ti)
            self._inputs.append((nome, ti))

    async def on_submit(self, interaction: discord.Interaction):
        valores: dict[str, int] = {}
        for nome, ti in self._inputs:
            raw = (ti.value or "0").strip()
            try:
                qtd = int(raw)
                if qtd < 0:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    f"❌ Quantidade inválida para **{nome}**: `{raw}`. Use apenas inteiros positivos.",
                    ephemeral=True,
                )
                return
            if qtd > 0:
                valores[nome] = qtd

        if not valores:
            await interaction.response.send_message(
                "❌ Defina pelo menos um produto com quantidade > 0.", ephemeral=True
            )
            return

        db_set_meta(
            self.guild_id,
            self.week_id,
            valores,
            str(interaction.user.id),
            meta_tipo=self.meta_tipo,
        )
        _farm_audit(
            "META_DEFINIDA",
            interaction.user.id,
            week_id=self.week_id,
            meta_tipo=self.meta_tipo,
        )

        resumo = "\n".join(
            f"• {emoji} **{nome}**: `{valores.get(nome, 0)}`"
            for nome, emoji in self.produtos
            if nome in valores
        )
        await interaction.response.send_message(
            f"✅ Metas da semana `{format_date_br(self.week_id)}` definidas:\n{resumo}", ephemeral=True
        )
        await self.cog._atualizar_ranking_fixo(self.guild_id)
        ticket_cog = interaction.client.get_cog("FarmTicketsCog")
        if ticket_cog:
            await ticket_cog.refresh_week(self.guild_id, self.week_id)
        await self.cog._enviar_aviso_meta_atualizada(
            interaction.guild,
            self.guild_id,
            self.week_id,
            self.titulo,
            [
                f"{emoji} **{nome}**: `{valores.get(nome, 0)}`"
                for nome, emoji in self.produtos
                if nome in valores
            ],
            interaction.user,
        )

    async def on_error(self, interaction, error):
        log.error(f"Erro no DefinirMetasModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao definir metas.")


class DefinirMetasDinheiroModal(discord.ui.Modal, title="Definir Meta — Dinheiro"):
    """Modal para definir metas separadas de dinheiro sujo e limpo."""

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str, meta=None):
        super().__init__()
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        metas_atuais = db_meta_dinheiro_itens_ativos(meta) if meta else {}
        if not metas_atuais and db_meta_dinheiro_ativo(meta) > 0:
            metas_atuais = {DINHEIRO_SUJO_ITEM: db_meta_dinheiro_ativo(meta)}
        self._inputs: list[tuple[str, discord.ui.TextInput]] = []

        for nome in DINHEIRO_ITEMS:
            valor_atual = metas_atuais.get(nome, 0)
            ti = discord.ui.TextInput(
                label=f"Valor do {nome} (R$)",
                style=discord.TextStyle.short,
                placeholder="Ex: 50000 ou R$ 50.000",
                default=str(int(valor_atual)) if valor_atual else None,
                required=False,
                max_length=20,
            )
            self.add_item(ti)
            self._inputs.append((nome, ti))

    async def on_submit(self, interaction: discord.Interaction):
        valores: dict[str, float] = {}
        for nome, ti in self._inputs:
            raw = (ti.value or "0").strip()
            try:
                valor = _parse_money(raw)
                if valor < 0:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    f"❌ Valor inválido para **{nome}**. Use `50000` ou `R$ 50.000`.",
                    ephemeral=True,
                )
                return
            if valor > 0:
                valores[nome] = valor

        if not valores:
            await interaction.response.send_message(
                "❌ Defina pelo menos uma meta de dinheiro acima de zero.",
                ephemeral=True,
            )
            return

        db_set_meta_dinheiro(self.guild_id, self.week_id, valores, str(interaction.user.id))
        _farm_audit("META_DINHEIRO_DEFINIDA", interaction.user.id, week_id=self.week_id, valores=str(valores))

        resumo = "\n".join(
            f"• **{nome}**: `{_fmt_money(valor)}`"
            for nome, valor in valores.items()
        )
        await interaction.response.send_message(
            f"✅ Meta de dinheiro da semana `{format_date_br(self.week_id)}` definida:\n{resumo}",
            ephemeral=True,
        )
        await self.cog._atualizar_ranking_fixo(self.guild_id)
        ticket_cog = interaction.client.get_cog("FarmTicketsCog")
        if ticket_cog:
            await ticket_cog.refresh_week(self.guild_id, self.week_id)
        await self.cog._enviar_aviso_meta_atualizada(
            interaction.guild,
            self.guild_id,
            self.week_id,
            "Dinheiro",
            [
                f"💵 **{nome}**: `{_fmt_money(valor)}`"
                for nome, valor in valores.items()
            ],
            interaction.user,
        )

    async def on_error(self, interaction, error):
        log.error(f"Erro no DefinirMetasDinheiroModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao definir meta de dinheiro.")


class LancarModal(discord.ui.Modal):
    """Modal dinâmico gerado a partir dos itens definidos na meta da semana."""

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str, user_id: str, itens: dict):
        meta = db_get_meta(guild_id, week_id)
        self.meta_tipo = db_meta_tipo_efetivo(meta)
        titulo = "Lançar Meta Colete" if self.meta_tipo == "colete" else "Lançar Kit Desmanche"
        super().__init__(title=titulo)
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        self.user_id = user_id
        self.item_names = list(itens.keys())
        if (
            self.meta_tipo == "itens"
            and FARM_EXTRA_ITEM not in self.item_names
            and len(self.item_names) < 5
        ):
            self.item_names.append(FARM_EXTRA_ITEM)
        self._inputs: list[discord.ui.TextInput] = []
        for nome in self.item_names:
            ti = discord.ui.TextInput(label=nome, placeholder="0", required=False, default="0")
            self.add_item(ti)
            self._inputs.append(ti)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)
        return

        if not janela_valida():
            await interaction.response.send_message(
                "❌ Fora da janela de lançamento (Segunda 00:00 a Domingo 23:59).", ephemeral=True
            )
            return
        try:
            valores = {}
            for nome, ti in zip(self.item_names, self._inputs):
                v = int(ti.value or 0)
                if v < 0:
                    raise ValueError
                if v > 0:
                    valores[nome] = v
        except ValueError:
            await interaction.response.send_message("❌ Valores inválidos.", ephemeral=True)
            return
        if not valores:
            await interaction.response.send_message(
                "❌ Informe pelo menos um valor acima de zero.", ephemeral=True
            )
            return

        print_msg, print_file = await _aguardar_print_farm(interaction, "farm")
        if print_file is None:
            return

        prog_antes   = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        status_antes = prog_antes["status"] if prog_antes else "em_andamento"

        db_lancar(self.guild_id, self.week_id, self.user_id, valores)
        db_verificar_conclusao(self.guild_id, self.week_id, self.user_id)
        prog_depois = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        executor_id = str(interaction.user.id)
        _farm_audit("LANCAMENTO", interaction.user.id, int(self.user_id), valores=str(valores))

        await self.cog._atualizar_painel(self.guild_id, self.week_id, self.user_id)
        await self.cog._atualizar_ranking_fixo(self.guild_id)

        if status_antes != "concluida" and prog_depois and prog_depois["status"] == "concluida":
            await self.cog._notificar_conclusao(interaction.guild, self.user_id, self.week_id)

        log_embed = discord.Embed(
            title="🚜 Farm Lançado",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        alvo = interaction.guild.get_member(int(self.user_id)) if interaction.guild else None
        alvo_mention = alvo.mention if alvo else f"<@{self.user_id}>"
        log_embed.add_field(name="👤 Membro", value=f"{alvo_mention}\n`{self.user_id}`", inline=True)
        if executor_id != self.user_id:
            log_embed.add_field(
                name="Lançado por",
                value=f"{interaction.user.mention}\n`{executor_id}`",
                inline=True,
            )
        itens_str = "\n".join(f"`{n}`: {v}" for n, v in valores.items() if v > 0)
        log_embed.add_field(name="🌾 Itens lançados", value=itens_str or "_nenhum_", inline=True)
        log_embed.add_field(name="📅 Semana", value=f"`{format_date_br(self.week_id)}`", inline=True)
        log_embed.set_image(url=f"attachment://{print_file.filename}")
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Farm")
        log_enviado = await send_log(interaction.client, interaction.guild, "farm", log_embed, files=[print_file])

        if log_enviado and print_msg:
            try:
                await print_msg.delete()
            except Exception:
                pass

        aviso_log = "" if log_enviado else "\nAviso: nao consegui enviar o log; deixei o print no canal."
        alvo_msg = f" para {alvo_mention}" if executor_id != self.user_id else ""
        await interaction.followup.send(f"✅ Produção lançada com sucesso{alvo_msg}!{aviso_log}", ephemeral=True)

    async def on_error(self, interaction, error):
        log.error(f"Erro no LancarModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao lançar produção.")


class LancarDinheiroModal(discord.ui.Modal, title="💵 Lançar Dinheiro"):
    """Modal para lançar dinheiro sujo e limpo quando a meta da semana é dinheiro."""

    _sujo_input = discord.ui.TextInput(
        label="Valor do Dinheiro Sujo (R$)",
        style=discord.TextStyle.short,
        placeholder="Ex: 50000 ou R$ 50.000",
        required=False,
        max_length=20,
    )
    _limpo_input = discord.ui.TextInput(
        label="Valor do Dinheiro Limpo (R$)",
        style=discord.TextStyle.short,
        placeholder="Ex: 50000 ou R$ 50.000",
        required=False,
        max_length=20,
    )

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str, user_id: str):
        super().__init__()
        self.cog      = cog
        self.week_id  = week_id
        self.guild_id = guild_id
        self.user_id  = user_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(FARM_TICKET_ONLY_MESSAGE, ephemeral=True)
        return

        if not janela_valida():
            await interaction.response.send_message(
                "❌ Fora da janela de lançamento (Segunda 00:00 a Domingo 23:59).", ephemeral=True
            )
            return
        try:
            sujo = _parse_money(self._sujo_input.value)
            limpo = _parse_money(self._limpo_input.value)
            if sujo < 0 or limpo < 0 or (sujo == 0 and limpo == 0):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valor inválido. Informe dinheiro sujo, dinheiro limpo ou os dois.",
                ephemeral=True,
            )
            return

        print_msg, print_file = await _aguardar_print_farm(interaction, "farm em dinheiro")
        if print_file is None:
            return

        prog_antes   = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        status_antes = prog_antes["status"] if prog_antes else "em_andamento"

        valores = {}
        if sujo > 0:
            valores[DINHEIRO_SUJO_ITEM] = sujo
        if limpo > 0:
            valores[DINHEIRO_LIMPO_ITEM] = limpo
        db_lancar(self.guild_id, self.week_id, self.user_id, valores)
        db_verificar_conclusao(self.guild_id, self.week_id, self.user_id)
        prog_depois = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        executor_id = str(interaction.user.id)
        _farm_audit("LANCAMENTO_DINHEIRO", interaction.user.id, int(self.user_id), week_id=self.week_id, sujo=sujo, limpo=limpo)

        total_fmt = _fmt_money(sujo + limpo)
        sujo_fmt = _fmt_money(sujo)
        limpo_fmt = _fmt_money(limpo)
        await self.cog._atualizar_painel(self.guild_id, self.week_id, self.user_id)
        await self.cog._atualizar_ranking_fixo(self.guild_id)

        if status_antes != "concluida" and prog_depois and prog_depois["status"] == "concluida":
            await self.cog._notificar_conclusao(interaction.guild, self.user_id, self.week_id)

        log_embed = discord.Embed(
            title="💵 Dinheiro Lançado",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        alvo = interaction.guild.get_member(int(self.user_id)) if interaction.guild else None
        alvo_mention = alvo.mention if alvo else f"<@{self.user_id}>"
        log_embed.add_field(name="👤 Membro", value=f"{alvo_mention}\n`{self.user_id}`", inline=True)
        if executor_id != self.user_id:
            log_embed.add_field(
                name="Lançado por",
                value=f"{interaction.user.mention}\n`{executor_id}`",
                inline=True,
            )
        log_embed.add_field(name="💰 Valor lançado", value=f"Sujo: {sujo_fmt}\nLimpo: {limpo_fmt}\nTotal: {total_fmt}", inline=True)
        log_embed.add_field(name="📅 Semana", value=f"`{format_date_br(self.week_id)}`", inline=True)
        log_embed.set_image(url=f"attachment://{print_file.filename}")
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Farm")
        log_enviado = await send_log(interaction.client, interaction.guild, "farm", log_embed, files=[print_file])

        if log_enviado and print_msg:
            try:
                await print_msg.delete()
            except Exception:
                pass

        aviso_log = "" if log_enviado else "\nAviso: nao consegui enviar o log; deixei o print no canal."
        await interaction.followup.send(
            f"✅ Dinheiro lançado"
            f"{f' para {alvo_mention}' if executor_id != self.user_id else ''}: **{total_fmt}** "
            f"(Sujo: `{sujo_fmt}` | Limpo: `{limpo_fmt}`){aviso_log}",
            ephemeral=True,
        )

    async def on_error(self, interaction, error):
        log.error(f"Erro no LancarDinheiroModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao lançar dinheiro sujo.")


class EditarUltimoModal(discord.ui.Modal, title="Editar Último Lançamento"):
    """
    Modal dinâmico para editar o último lançamento.
    Pré-preenchido com os valores atuais do evento para facilitar a correção.
    """

    def __init__(
        self,
        cog: "FarmCog",
        week_id: str,
        guild_id: str,
        user_id: str,
        itens: dict,
        event_id: int | None = None,
    ):
        super().__init__()
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        self.user_id = user_id
        self.event_id = event_id
        self.item_names = list(itens.keys())
        self._inputs: list[discord.ui.TextInput] = []
        for nome, val in itens.items():
            ti = discord.ui.TextInput(
                label=nome,
                placeholder="Novo valor total",
                required=False,
                default=str(val) if val else "0",
            )
            self.add_item(ti)
            self._inputs.append(ti)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valores = {}
            for nome, ti in zip(self.item_names, self._inputs):
                v = _parse_money(ti.value) if nome in DINHEIRO_ITEMS else int(ti.value or 0)
                if v < 0:
                    raise ValueError
                valores[nome] = v
        except ValueError:
            await interaction.response.send_message("❌ Valores inválidos.", ephemeral=True)
            return
        prog_antes = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        if self.event_id is None:
            ok = db_editar_ultimo_evento(self.guild_id, self.week_id, self.user_id, valores)
        else:
            ok = db_editar_evento(self.guild_id, self.week_id, self.user_id, self.event_id, valores)
        if not ok:
            await interaction.response.send_message(
                "❌ Nenhum lançamento encontrado para editar.", ephemeral=True
            )
            return
        db_verificar_conclusao(self.guild_id, self.week_id, self.user_id)
        prog_depois = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        _farm_audit("EDICAO", interaction.user.id, int(self.user_id), event_id=self.event_id, valores=str(valores))
        alvo_msg = "" if str(interaction.user.id) == self.user_id else f" de <@{self.user_id}>"
        await interaction.response.send_message(f"✅ Lançamento{alvo_msg} editado!", ephemeral=True)
        await self.cog._atualizar_painel(self.guild_id, self.week_id, self.user_id)
        await self.cog._atualizar_ranking_fixo(self.guild_id)
        status_antes = prog_antes["status"] if prog_antes else "em_andamento"
        if status_antes != "concluida" and prog_depois and prog_depois["status"] == "concluida":
            await self.cog._notificar_conclusao(interaction.guild, self.user_id, self.week_id)

    async def on_error(self, interaction, error):
        log.error(f"Erro no EditarUltimoModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao editar lançamento.")


# ══════════════════════════════════════════════════════════════════════════════
# VIEWS
# ══════════════════════════════════════════════════════════════════════════════

VIEW_TIMEOUT = 900

class MetaView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog; self.guild_id = guild_id; self.week_id = week_id

    async def on_timeout(self):
        for item in self.children: item.disabled = True

    @discord.ui.button(label="📝 Definir Metas", style=discord.ButtonStyle.primary)
    async def definir_metas(self, interaction: discord.Interaction, button: discord.ui.Button):
        lideranca_ids = db_get_lideranca_role_ids(str(interaction.guild_id))
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode definir metas.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Escolha o tipo de meta para esta semana:",
            view=EscolherTipoMetaView(self.cog, self.week_id, self.guild_id),
            ephemeral=True,
        )

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary)
    async def atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        meta = db_get_meta(self.guild_id, self.week_id)
        embed = build_meta_embed(meta, self.week_id)
        await interaction.edit_original_response(embed=embed, view=MetaView(self.cog, self.guild_id, self.week_id))


class EscolherTipoMetaView(discord.ui.View):
    """View efêmera que permite escolher o tipo de meta antes de abrir o modal."""

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="📦 Kit Desmanche", style=discord.ButtonStyle.primary)
    async def btn_itens(self, interaction: discord.Interaction, button: discord.ui.Button):
        meta = db_get_meta(self.guild_id, self.week_id)
        await _safe_send_modal(interaction, DefinirMetasModal(self.cog, self.week_id, self.guild_id, meta))

    @discord.ui.button(label="🦺 Colete", style=discord.ButtonStyle.secondary)
    async def btn_colete(self, interaction: discord.Interaction, button: discord.ui.Button):
        meta = db_get_meta(self.guild_id, self.week_id)
        await _safe_send_modal(
            interaction,
            DefinirMetasModal(
                self.cog,
                self.week_id,
                self.guild_id,
                meta,
                produtos=COLETE_PRODUTOS,
                meta_tipo="colete",
                titulo="Meta Colete",
                placeholders=COLETE_PLACEHOLDERS,
            ),
        )

    @discord.ui.button(label="💵 Dinheiro", style=discord.ButtonStyle.success)
    async def btn_dinheiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        meta = db_get_meta(self.guild_id, self.week_id)
        await _safe_send_modal(interaction, DefinirMetasDinheiroModal(self.cog, self.week_id, self.guild_id, meta))


class FarmView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, user_id: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog; self.guild_id = guild_id; self.week_id = week_id; self.user_id = user_id

    async def on_timeout(self):
        for item in self.children: item.disabled = True

    def _owns(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="🎫 Abrir Ticket de Farm", style=discord.ButtonStyle.success)
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owns(interaction):
            await interaction.response.send_message("❌ Este painel não é seu.", ephemeral=True)
            return
        ticket_cog = interaction.client.get_cog("FarmTicketsCog")
        if not ticket_cog:
            await interaction.response.send_message(
                "❌ Sistema de tickets indisponível.", ephemeral=True
            )
            return
        await ticket_cog.open_ticket(interaction)

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary)
    async def atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        meta  = db_get_meta(self.guild_id, self.week_id)
        prog  = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        embed = build_farm_embed(meta, prog, interaction.user, self.week_id)
        await interaction.edit_original_response(embed=embed, view=FarmView(self.cog, self.guild_id, self.week_id, self.user_id))


class ResultadoView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, participantes: list, guild: discord.Guild = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog; self.guild_id = guild_id; self.week_id = week_id

        options = []
        for p in participantes:
            nome = f"ID: {p['user_id']}"
            if guild:
                member = guild.get_member(int(p["user_id"]))
                if member: nome = member.display_name
            emoji = "✅" if p["status"] == "concluida" else "🔄"
            aprov = "Aprovado" if p["aprovada"] else "Pendente"
            options.append(discord.SelectOption(
                label=nome[:100], value=p["user_id"],
                description=f"{emoji} {p['status'].replace('_', ' ').title()} | {aprov}",
            ))

        if not options:
            options = [discord.SelectOption(label="Nenhum participante", value="none")]

        self.select = discord.ui.Select(placeholder="Selecione um membro para ver detalhes", options=options[:25])
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        user_id = self.select.values[0]
        if user_id == "none":
            await interaction.response.send_message("Nenhum participante.", ephemeral=True)
            return
        await interaction.response.defer()
        db_verificar_conclusao(self.guild_id, self.week_id, user_id)
        prog   = db_get_progresso(self.guild_id, self.week_id, user_id)
        meta   = db_get_meta(self.guild_id, self.week_id)
        member = interaction.guild.get_member(int(user_id)) or await _safe_fetch_member(interaction.guild, int(user_id))
        embed  = build_farm_embed(meta, prog, member or interaction.user, self.week_id)
        embed.title = f"📊 Resultado — {member.display_name if member else user_id}"

        pode_aprovar = bool(prog and not prog["aprovada"])
        antecipada   = bool(prog and prog["status"] != "concluida")
        view = DetalheResultadoView(self.cog, self.guild_id, self.week_id, user_id, pode_aprovar, antecipada)
        await interaction.edit_original_response(embed=embed, view=view)


class DetalheResultadoView(discord.ui.View):
    def __init__(
        self, cog: "FarmCog", guild_id: str, week_id: str,
        user_id: str, pode_aprovar: bool, antecipada: bool = False,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog; self.guild_id = guild_id; self.week_id = week_id
        self.user_id = user_id; self.antecipada = antecipada

        if antecipada:
            label_aprovar = "⚡ Aprovar Antecipadamente"
            style_aprovar = discord.ButtonStyle.danger
        else:
            label_aprovar = "✅ Aprovar Meta"
            style_aprovar = discord.ButtonStyle.success

        btn_aprovar = discord.ui.Button(
            label=label_aprovar, style=style_aprovar, disabled=not pode_aprovar
        )
        btn_aprovar.callback = self._aprovar
        self.add_item(btn_aprovar)

        btn_voltar = discord.ui.Button(label="⬅️ Voltar", style=discord.ButtonStyle.secondary)
        btn_voltar.callback = self._voltar
        self.add_item(btn_voltar)

    async def _aprovar(self, interaction: discord.Interaction):
        lideranca_ids = db_get_lideranca_role_ids(str(interaction.guild_id))
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode aprovar.", ephemeral=True)
            return
        prog = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        if prog and prog["aprovada"]:
            await interaction.response.send_message("⚠️ Esta meta já foi aprovada.", ephemeral=True)
            return
        antecipada = bool(prog and prog["status"] != "concluida")
        if antecipada:
            # Exibe escolha de nível antes de confirmar aprovação antecipada
            member = interaction.guild.get_member(int(self.user_id))
            nome   = member.display_name if member else self.user_id
            view   = AprovarNivelView(self.cog, self.guild_id, self.week_id, self.user_id, interaction.user)
            await interaction.response.send_message(
                f"⚡ **Aprovação antecipada** — {nome}\nEscolha o nível de desempenho:",
                view=view,
                ephemeral=True,
            )
        else:
            db_aprovar(self.guild_id, self.week_id, self.user_id, str(interaction.user.id))
            _farm_audit("META_APROVADA", interaction.user.id, int(self.user_id), antecipada=False)
            await interaction.response.send_message("✅ Meta aprovada!", ephemeral=True)
            await self.cog._notificar_aprovacao(interaction.guild, self.user_id, interaction.user, antecipada=False)
            await self.cog._atualizar_ranking_fixo(self.guild_id)

    async def _voltar(self, interaction: discord.Interaction):
        await interaction.response.defer()
        participantes = db_lista_progresso(self.guild_id, self.week_id)
        view  = ResultadoView(self.cog, self.guild_id, self.week_id, participantes, interaction.guild)
        embed = discord.Embed(
            title="📊 Resultados da Semana",
            description=f"📅 Semana: `{format_date_br(self.week_id)}` — {len(participantes)} participante(s)",
            color=discord.Color.blue(), timestamp=discord.utils.utcnow(),
        )
        await interaction.edit_original_response(embed=embed, view=view)


class AprovarNivelView(discord.ui.View):
    """View para a liderança escolher o nível de desempenho na aprovação antecipada."""

    _NIVEIS = [
        ("elite",       "🥇 Elite (130%+)",       discord.ButtonStyle.danger),
        ("meta_batida", "✅ Meta Batida (100%)",   discord.ButtonStyle.success),
        ("parcial",     "⚠️ Parcial (60%)",        discord.ButtonStyle.secondary),
    ]

    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, user_id: str, aprovador: discord.Member):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog; self.guild_id = guild_id; self.week_id = week_id
        self.user_id = user_id; self.aprovador = aprovador

        for nivel, label, style in self._NIVEIS:
            btn = discord.ui.Button(label=label, style=style)
            btn.callback = self._fazer_callback(nivel, label)
            self.add_item(btn)

    def _fazer_callback(self, nivel: str, label: str):
        async def _cb(interaction: discord.Interaction):
            db_aprovar(
                self.guild_id, self.week_id, self.user_id,
                str(self.aprovador.id), antecipada=True, nivel=nivel,
            )
            _farm_audit("META_APROVADA_ANTECIPADA", self.aprovador.id, int(self.user_id), nivel=nivel)
            await interaction.response.send_message(
                f"⚡ Aprovação antecipada registrada! Nível: **{label}**", ephemeral=True
            )
            await self.cog._notificar_aprovacao(
                interaction.guild, self.user_id, self.aprovador, antecipada=True
            )
            await self.cog._atualizar_ranking_fixo(self.guild_id)
        return _cb

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _safe_send_modal(interaction: discord.Interaction, modal: discord.ui.Modal):
    try:
        await interaction.response.send_modal(modal)
    except discord.InteractionResponded:
        await interaction.followup.send("⚠️ Sessão expirada. Use o comando novamente.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro ao enviar modal: {e}", exc_info=True)

async def _safe_respond(interaction: discord.Interaction, msg: str):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass

def _meta_aprovada_asset() -> Path | None:
    """Caminho da arte usada na parabenização da meta, se estiver no disco."""
    for caminho in META_APROVADA_IMAGE_PATHS:
        if caminho.exists():
            return caminho
    return None


def _meta_aprovada_filename() -> str | None:
    """Nome do anexo referenciado pelo embed, sem abrir o arquivo."""
    caminho = _meta_aprovada_asset()
    return f"mdm-meta{caminho.suffix.lower()}" if caminho else None


def _meta_aprovada_anexo() -> discord.File | None:
    """Cria um anexo novo a cada tentativa de envio (o arquivo é consumido)."""
    caminho = _meta_aprovada_asset()
    if not caminho:
        return None
    try:
        return discord.File(caminho, filename=f"mdm-meta{caminho.suffix.lower()}")
    except OSError as e:
        log.warning("Falha ao abrir a arte da meta aprovada: %s", e)
        return None


async def _safe_fetch_member(guild: discord.Guild, member_id: int):
    try:
        return await guild.fetch_member(member_id)
    except Exception:
        return None

async def _safe_fetch_channel(guild: discord.Guild, channel_id: int):
    try:
        return await guild.fetch_channel(channel_id)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class FarmCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()
        self._ranking_task.start()
        self._abertura_semana.start()
        self._aviso_quarta.start()
        self._aviso_quinta.start()
        self._fechamento_semana.start()
        log.info("FarmCog inicializado.")

    def cog_unload(self):
        self._ranking_task.cancel()
        self._abertura_semana.cancel()
        self._aviso_quarta.cancel()
        self._aviso_quinta.cancel()
        self._fechamento_semana.cancel()

    async def _atualizar_painel(self, guild_id: str, week_id: str, user_id: str):
        prog = db_get_progresso(guild_id, week_id, user_id)
        if not prog or not prog["painel_channel_id"] or not prog["painel_message_id"]:
            return
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        try:
            channel = guild.get_channel(int(prog["painel_channel_id"])) or \
                      await guild.fetch_channel(int(prog["painel_channel_id"]))
            message = await channel.fetch_message(int(prog["painel_message_id"]))
            member  = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            meta    = db_get_meta(guild_id, week_id)
            prog    = db_get_progresso(guild_id, week_id, user_id)
            embed   = build_farm_embed(meta, prog, member, week_id)
            await message.edit(embed=embed, view=FarmView(self, guild_id, week_id, user_id))
        except discord.NotFound:
            db_limpar_painel(guild_id, week_id, user_id)
            log.info(f"Painel órfão removido para user {user_id}")
        except Exception as e:
            log.warning(f"Falha ao atualizar painel {user_id}: {e}")

    async def _atualizar_ranking_fixo(self, guild_id: str):
        cog = self.bot.get_cog("RankingPainelCog")
        if not cog:
            return
        try:
            await cog.atualizar_ranking_fixo(guild_id)
        except Exception as e:
            log.warning(f"Falha ao atualizar ranking fixo da guild {guild_id}: {e}")

    async def _enviar_aviso_meta_atualizada(
        self,
        guild: discord.Guild | None,
        guild_id: str,
        week_id: str,
        tipo: str,
        linhas: list[str],
        definido_por: discord.Member | discord.User,
    ):
        guild = guild or self.bot.get_guild(int(guild_id))
        if not guild:
            return

        canal_id = META_AVISOS_CHANNEL_ID
        canal = guild.get_channel(canal_id) or await _safe_fetch_channel(guild, canal_id)
        if not canal:
            log.warning("Canal de avisos de meta nao encontrado: guild=%s canal=%s", guild_id, canal_id)
            return

        embed = discord.Embed(
            title=f"🎯 Meta Atualizada — {tipo}",
            description=f"Semana: `{format_date_br(week_id)}`\n\n" + "\n".join(linhas),
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Definida por", value=definido_por.mention, inline=True)
        embed.set_footer(text="Morro do Mineiro — Sistema de Farm")

        try:
            await canal.send(
                content="@everyone",
                embed=embed,
                allowed_mentions=EVERYONE_ALLOWED_MENTIONS,
            )
        except Exception as e:
            log.warning("Falha ao enviar aviso de meta atualizada: %s", e)

    async def _notificar_aprovacao(
        self, guild: discord.Guild, user_id: str,
        aprovador: discord.Member, antecipada: bool = False,
    ):
        membro = guild.get_member(int(user_id)) or await _safe_fetch_member(guild, int(user_id))
        if not membro:
            return

        if antecipada:
            title = "⚡ Aprovação Antecipada!"
            desc  = (
                f"Parabéns, **{membro.display_name}**!\n"
                f"Sua meta foi aprovada antecipadamente por {aprovador.mention}.\n\n"
                f"Continue farmando para concluir a meta!"
            )
        else:
            title = "🏆 Meta Aprovada!"
            desc  = (
                f"Parabéns, **{membro.display_name}**!\n"
                f"Sua meta foi aprovada por {aprovador.mention}."
            )

        embed = discord.Embed(
            title=title, description=desc,
            color=discord.Color.gold(), timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.set_footer(text="Morro do Mineiro — Sistema de Farm")

        arte = _meta_aprovada_filename()
        if arte:
            embed.set_image(url=f"attachment://{arte}")

        def _arquivos() -> list[discord.File]:
            anexo = _meta_aprovada_anexo()
            return [anexo] if anexo else []

        pasta = await self._resolver_pasta_privada(guild, membro)
        if pasta:
            try:
                await pasta.send(membro.mention, embed=embed, files=_arquivos())
                log.info("Aprovação enviada na pasta privada: user=%s canal=%s", user_id, pasta.id)
                return
            except Exception as e:
                log.warning("Falha ao notificar pasta privada de %s: %s", user_id, e)

        try:
            await membro.send(embed=embed, files=_arquivos())
            return
        except Exception:
            pass

        cfg = db_get_guild_config(str(guild.id))
        canal_avisos_id = int(cfg["canal_avisos_farm"]) if cfg and cfg["canal_avisos_farm"] else None
        if canal_avisos_id:
            try:
                canal = guild.get_channel(canal_avisos_id) or await guild.fetch_channel(canal_avisos_id)
                await canal.send(membro.mention, embed=embed, files=_arquivos())
            except Exception as e:
                log.warning(f"Falha ao notificar canal de avisos: {e}")

    async def _resolver_pasta_privada(
        self, guild: discord.Guild, membro: discord.Member,
    ) -> discord.TextChannel | None:
        """Canal da pasta individual do membro, quando identificável com segurança."""
        cfg = db_get_guild_config(str(guild.id))
        if not cfg or not cfg["private_category_id"]:
            return None
        try:
            pasta = await resolve_member_folder(
                guild, str(guild.id), membro, int(cfg["private_category_id"]),
            )
        except MemberFolderError as e:
            log.info("Pasta privada não identificada para %s: %s", membro.id, e)
            return None
        except Exception as e:
            log.warning("Falha ao resolver pasta privada de %s: %s", membro.id, e)
            return None

        canal = guild.get_channel(pasta.channel_id) or await _safe_fetch_channel(guild, pasta.channel_id)
        return canal if isinstance(canal, discord.TextChannel) else None

    async def _notificar_conclusao(self, guild: discord.Guild, user_id: str, week_id: str):
        """
        MUDANÇA 3 — Parabeniza em tempo real quando todos os itens cruzam 100%.
        Dispara apenas uma vez por membro por semana (controlado pelo status 'concluida').
        """
        membro = guild.get_member(int(user_id)) or await _safe_fetch_member(guild, int(user_id))
        if not membro:
            return

        await self._promover_flanelinha_automaticamente(guild, membro, week_id)

        meta       = db_get_meta(str(guild.id), week_id)
        prog       = db_get_progresso(str(guild.id), week_id, user_id)
        meta_tipo  = db_meta_tipo_efetivo(meta)
        meta_itens = db_meta_itens_ativos(meta) if meta else {}
        meta_dinheiro_itens = db_meta_dinheiro_itens_ativos(meta) if meta else {}
        prog_itens = db_prog_itens(prog) if prog else {}

        if meta and meta_tipo == "dinheiro":
            total_prog = sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
            total_meta = db_meta_dinheiro_ativo(meta) or 1
            entregas_base = meta_dinheiro_itens or {nome: 0 for nome in DINHEIRO_ITEMS}
        else:
            total_prog = sum(prog_itens.get(nome, 0) for nome in meta_itens)
            total_meta = sum(meta_itens.values()) or 1
            entregas_base = meta_itens
        pct_total  = round(total_prog / total_meta * 100, 1)

        if meta_tipo == "dinheiro":
            if meta_dinheiro_itens:
                classificacao = classificar_resultado(meta_dinheiro_itens, prog_itens)
            else:
                classificacao = "elite" if pct_total >= 130 else "meta_batida"
        else:
            classificacao = classificar_resultado(meta_itens, prog_itens) if meta_itens else "meta_batida"
        entregue_txt = _format_entregas_separadas(
            prog_itens,
            entregas_base,
            dinheiro=meta_tipo == "dinheiro",
        )
        status_str    = "🔥 Elite" if classificacao == "elite" else "✅ Meta Batida"

        embed = discord.Embed(
            title="🏆 META BATIDA — Morro do Mineiro",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.add_field(name="👤 Membro",   value=membro.mention,                                      inline=True)
        embed.add_field(name="🏅 Status",   value=status_str,                                          inline=True)
        embed.add_field(name="📦 Entregou", value=entregue_txt, inline=False)
        embed.set_footer(text=f"Morro do Mineiro • Semana {format_date_br(week_id)}")

        cfg             = db_get_guild_config(str(guild.id))
        canal_notif_id  = int(cfg["canal_notificacao_farm"]) if cfg and cfg["canal_notificacao_farm"] else None
        canal_avisos_id = int(cfg["canal_avisos_farm"])       if cfg and cfg["canal_avisos_farm"]       else None

        if canal_notif_id:
            try:
                canal = guild.get_channel(canal_notif_id) or await guild.fetch_channel(canal_notif_id)
                await canal.send(embed=embed)
                log.info(f"Parabenização de meta batida enviada: user={user_id} semana={week_id}")
                return
            except Exception as e:
                log.warning(f"Falha ao notificar canal de notificação: {e}")

        if canal_avisos_id:
            try:
                canal = guild.get_channel(canal_avisos_id) or await guild.fetch_channel(canal_avisos_id)
                await canal.send(embed=embed)
            except Exception as e:
                log.warning(f"Falha ao notificar canal de avisos: {e}")

    async def _promover_flanelinha_automaticamente(
        self,
        guild: discord.Guild,
        membro: discord.Member,
        week_id: str,
    ) -> bool:
        cfg = db_get_guild_config(str(guild.id))
        if not cfg or not cfg["flanelinha_auto_promote"]:
            return False

        flanelinha_role_id = cfg["flanelinha_role_id"]
        member_role_id = cfg["member_role_id"]
        if not flanelinha_role_id or not member_role_id:
            log.warning("Promocao Flanelinha sem cargos configurados na guild %s", guild.id)
            return False

        flanelinha_role = guild.get_role(int(flanelinha_role_id))
        member_role = guild.get_role(int(member_role_id))
        if flanelinha_role is None or member_role is None:
            log.warning(
                "Cargo da promocao Flanelinha nao encontrado: guild=%s flanelinha=%s membro=%s",
                guild.id,
                flanelinha_role_id,
                member_role_id,
            )
            return False

        try:
            result = await promote_role(
                membro,
                flanelinha_role,
                member_role,
                reason=f"Meta semanal concluida em {format_date_br(week_id)}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.error(
                "Falha ao promover Flanelinha %s na guild %s: %s",
                membro.id,
                guild.id,
                exc,
            )
            return False

        if not result.promoted:
            if result.reason != "source_role_missing":
                log.warning(
                    "Promocao Flanelinha ignorada: guild=%s membro=%s motivo=%s",
                    guild.id,
                    membro.id,
                    result.reason,
                )
            return False

        notify_user_id = cfg["flanelinha_notify_user_id"] or str(guild.owner_id)
        embed = discord.Embed(
            title="🎉 Flanelinha promovido automaticamente",
            description=(
                f"{membro.mention} bateu a meta semanal e foi promovido "
                f"de {flanelinha_role.mention} para {member_role.mention}."
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Semana", value=f"`{format_date_br(week_id)}`", inline=True)
        embed.add_field(name="Membro", value=f"{membro.mention}\n`{membro.id}`", inline=True)
        embed.set_footer(text="Morro do Mineiro — Promoção automática do Farm")

        log_enviado = await send_log(
            self.bot,
            guild,
            "farm",
            embed,
            content=f"<@{notify_user_id}>" if notify_user_id else None,
        )
        if not log_enviado:
            log.warning(
                "Promocao realizada, mas o log nao foi enviado: guild=%s membro=%s",
                guild.id,
                membro.id,
            )

        log.info(
            "Flanelinha promovido automaticamente: guild=%s membro=%s semana=%s",
            guild.id,
            membro.id,
            week_id,
        )
        return True

    @tasks.loop(minutes=1)
    async def _ranking_task(self):
        dt = now_tz()
        if dt.weekday() != 6 or dt.hour != 23 or dt.minute != 59:
            return
        for guild_id_str in db_all_configured_guilds():
            cfg = db_get_guild_config(guild_id_str)
            if not cfg or not cfg["canal_avisos_farm"]:
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            week_id       = current_week_id()
            participantes = db_ranking_semana(guild_id_str, week_id)
            if not participantes:
                continue
            try:
                canal_id = int(cfg["canal_avisos_farm"])
                canal    = guild.get_channel(canal_id) or await guild.fetch_channel(canal_id)
                embed    = build_ranking_embed(guild_id_str, week_id, participantes, guild)
                await canal.send(embed=embed)
                log.info(f"Ranking semanal postado para guild {guild_id_str}, semana {week_id}")
            except Exception as e:
                log.error(f"Erro ao postar ranking para guild {guild_id_str}: {e}")

    @_ranking_task.before_loop
    async def _before_ranking(self):
        await self.bot.wait_until_ready()

    # ── Task: abertura de semana toda segunda às 00:00 ────────────────────────

    @tasks.loop(minutes=1)
    async def _abertura_semana(self):
        dt = now_tz()
        if dt.weekday() != 0 or dt.hour != 0 or dt.minute != 0:
            return
        for guild_id_str in db_all_configured_guilds():
            cfg = db_get_guild_config(guild_id_str)
            if not cfg or not cfg["canal_avisos_farm"]:
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            week_id    = current_week_id()
            meta       = db_get_meta(guild_id_str, week_id)
            meta_tipo = db_meta_tipo_efetivo(meta)
            if meta and meta_tipo == "dinheiro":
                meta_str = _fmt_money(db_meta_dinheiro_ativo(meta))
            else:
                meta_itens = db_meta_itens_ativos(meta) if meta else {}
                total_meta = sum(meta_itens.values())
                partes = []
                if total_meta:
                    nome_meta = "materiais de Colete" if meta_tipo == "colete" else "itens do Kit Desmanche"
                    partes.append(f"{total_meta} {nome_meta}")
                meta_str = " + ".join(partes) if partes else "A definir"

            embed = discord.Embed(
                title="⚙️ SEMANA ABERTA — Morro do Mineiro",
                color=0xFFD700,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="🎯 Meta da Semana", value=meta_str,                  inline=True)
            embed.add_field(name="📅 Prazo",          value="Segunda 00:00 → Domingo 23:59", inline=True)
            embed.add_field(
                name="\u200b",
                value="💬 Baú aberto. Registre seu farm dentro do prazo.",
                inline=False,
            )
            embed.set_footer(text=f"Morro do Mineiro • Semana {format_date_br(week_id)}")
            try:
                canal = guild.get_channel(int(cfg["canal_avisos_farm"])) or \
                        await guild.fetch_channel(int(cfg["canal_avisos_farm"]))
                await canal.send(embed=embed)
                log.info(f"Abertura de semana postada: guild={guild_id_str} semana={week_id}")
            except Exception as e:
                log.error(f"Erro ao postar abertura de semana guild={guild_id_str}: {e}")

    @_abertura_semana.before_loop
    async def _before_abertura(self):
        await self.bot.wait_until_ready()

    # ── Task: aviso de quarta às 20:00 (DM para quem tem zero entrega) ────────

    @tasks.loop(minutes=1)
    async def _aviso_quarta(self):
        dt = now_tz()
        if dt.weekday() != 2 or dt.hour != 20 or dt.minute != 0:
            return
        for guild_id_str in db_all_configured_guilds():
            if not db_is_farm_configured(guild_id_str):
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            week_id        = current_week_id()
            meta           = db_get_meta(guild_id_str, week_id)
            meta_tipo      = db_meta_tipo_efetivo(meta)
            meta_itens     = db_meta_itens_ativos(meta)
            permitidos_ids = db_get_permitidos_role_ids(guild_id_str)
            lista_prog     = db_lista_progresso(guild_id_str, week_id)
            prog_por_uid   = {str(row["user_id"]): row for row in lista_prog}
            for member in guild.members:
                if member.bot:
                    continue
                if not is_permitido_farm(member, permitidos_ids):
                    continue
                row = prog_por_uid.get(str(member.id))
                # Aprovados não recebem aviso
                if row and (bool(row["aprovada"]) or bool(row.get("aprovacao_antecipada", False))):
                    continue
                # Só envia DM se TODOS os itens estão zerados
                prog_itens = db_prog_itens(row) if row else {}
                if meta_tipo == "dinheiro":
                    tem_entrega = any(prog_itens.get(nome, 0) > 0 for nome in DINHEIRO_ITEMS)
                else:
                    tem_entrega = any(prog_itens.get(nome, 0) > 0 for nome in meta_itens)
                if tem_entrega:
                    continue
                try:
                    await member.send(
                        f"⚠️ A semana fecha domingo 23:59, {member.display_name}.\n"
                        f"Você ainda não tem nenhuma entrega no baú essa semana.\n"
                        f"Consegue farmar hoje ou amanhã?\n"
                        f"— Morro do Mineiro"
                    )
                except Exception as e:
                    log.warning(f"DM quarta falhou para {member.id}: {e}")

    @_aviso_quarta.before_loop
    async def _before_quarta(self):
        await self.bot.wait_until_ready()

    # ── Task: aviso de sabado às 20:00 (DM para quem continua com zero) ───────

    @tasks.loop(minutes=1)
    async def _aviso_quinta(self):
        dt = now_tz()
        if dt.weekday() != 5 or dt.hour != 20 or dt.minute != 0:
            return
        for guild_id_str in db_all_configured_guilds():
            if not db_is_farm_configured(guild_id_str):
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            week_id        = current_week_id()
            meta           = db_get_meta(guild_id_str, week_id)
            meta_tipo      = db_meta_tipo_efetivo(meta)
            meta_itens     = db_meta_itens_ativos(meta)
            permitidos_ids = db_get_permitidos_role_ids(guild_id_str)
            lista_prog     = db_lista_progresso(guild_id_str, week_id)
            prog_por_uid   = {str(row["user_id"]): row for row in lista_prog}
            for member in guild.members:
                if member.bot:
                    continue
                if not is_permitido_farm(member, permitidos_ids):
                    continue
                row = prog_por_uid.get(str(member.id))
                # Aprovados não recebem aviso
                if row and (bool(row["aprovada"]) or bool(row.get("aprovacao_antecipada", False))):
                    continue
                # Só envia DM se TODOS os itens estão zerados
                prog_itens = db_prog_itens(row) if row else {}
                if meta_tipo == "dinheiro":
                    tem_entrega = any(prog_itens.get(nome, 0) > 0 for nome in DINHEIRO_ITEMS)
                else:
                    tem_entrega = any(prog_itens.get(nome, 0) > 0 for nome in meta_itens)
                if tem_entrega:
                    continue
                try:
                    await member.send(
                        f"🚨 Último dia, {member.display_name}.\n"
                        f"Amanhã a semana fecha e você ainda não tem nenhuma entrega.\n"
                        f"Farma hoje antes que feche.\n"
                        f"— Morro do Mineiro"
                    )
                except Exception as e:
                    log.warning(f"DM quinta falhou para {member.id}: {e}")

    @_aviso_quinta.before_loop
    async def _before_quinta(self):
        await self.bot.wait_until_ready()

    # ── Task: fechamento de semana todo domingo às 23:59 ──────────────────────

    @tasks.loop(minutes=1)
    async def _fechamento_semana(self):
        dt = now_tz()
        if dt.weekday() != 6 or dt.hour != 23 or dt.minute != 59:
            return
        for guild_id_str in db_all_configured_guilds():
            cfg = db_get_guild_config(guild_id_str)
            if not cfg or not cfg["canal_avisos_farm"]:
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            week_id        = current_week_id()
            ranking        = db_ranking_semana(guild_id_str, week_id)
            ranking_by_uid = {r["user_id"]: r for r in ranking}
            permitidos_ids = db_get_permitidos_role_ids(guild_id_str)
            lista_prog     = db_lista_progresso(guild_id_str, week_id)
            prog_por_uid   = {str(row["user_id"]): row for row in lista_prog}

            elite_mentions   = []
            meta_mentions    = []
            parcial_mentions = []
            zero_count       = 0
            total_permitidos = 0
            total_sujo       = 0.0
            total_limpo      = 0.0

            for member in guild.members:
                if member.bot:
                    continue
                if not is_permitido_farm(member, permitidos_ids):
                    continue
                total_permitidos += 1
                row_rank = ranking_by_uid.get(str(member.id), {})
                classificacao = row_rank.get("classificacao", "zero")
                prog_itens = db_prog_itens(prog_por_uid.get(str(member.id)))
                total_sujo += float(prog_itens.get(DINHEIRO_SUJO_ITEM, 0) or 0)
                total_limpo += float(prog_itens.get(DINHEIRO_LIMPO_ITEM, 0) or 0)
                if classificacao == "elite":
                    elite_mentions.append(member.mention)
                elif classificacao == "meta_batida":
                    meta_mentions.append(member.mention)
                elif classificacao == "parcial":
                    parcial_mentions.append(member.mention)
                else:
                    zero_count += 1

            bateram_100 = len(elite_mentions) + len(meta_mentions)
            taxa        = round(bateram_100 / total_permitidos * 100) if total_permitidos else 0

            def _fmt(mentions: list[str]) -> str:
                if not mentions:
                    return "—"
                # Trunca para evitar exceder o limite de 1024 chars do campo
                texto = " ".join(mentions[:30])
                if len(mentions) > 30:
                    texto += f"\n*+{len(mentions) - 30} outros*"
                return texto

            embed = discord.Embed(
                title="📊 FECHAMENTO DA SEMANA — Morro do Mineiro",
                color=0xFFD700,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="🔥 Morro Forte — Elite", value=_fmt(elite_mentions),   inline=True)
            embed.add_field(name="✅ Meta Batida",          value=_fmt(meta_mentions),    inline=True)
            embed.add_field(name="⚠️ Parcial",              value=_fmt(parcial_mentions), inline=True)
            embed.add_field(
                name="❌ Abaixo do Mínimo",
                value=(
                    f"{zero_count} membros abaixo do mínimo — tratado internamente."
                    if zero_count else "Nenhum. 🎉"
                ),
                inline=False,
            )
            embed.add_field(
                name="📦 Resumo da Semana",
                value=(
                    f"Total participantes: {total_permitidos}\n"
                    f"Taxa de entrega: {taxa}% (100%+ da meta)\n"
                    f"Dinheiro sujo: {_fmt_money(total_sujo)}\n"
                    f"Dinheiro limpo: {_fmt_money(total_limpo)}\n"
                    f"Total dinheiro: {_fmt_money(total_sujo + total_limpo)}"
                ),
                inline=False,
            )
            embed.set_footer(text=f"Morro do Mineiro • Semana {format_date_br(week_id)}")

            try:
                canal = guild.get_channel(int(cfg["canal_avisos_farm"])) or \
                        await guild.fetch_channel(int(cfg["canal_avisos_farm"]))
                await canal.send(embed=embed)
                log.info(f"Fechamento de semana postado: guild={guild_id_str} semana={week_id}")
            except Exception as e:
                log.error(f"Erro ao postar fechamento guild={guild_id_str}: {e}")

    @_fechamento_semana.before_loop
    async def _before_fechamento(self):
        await self.bot.wait_until_ready()

    # ── Comandos ──────────────────────────────────────────────────────────────

    @app_commands.command(name="meta", description="Painel de metas semanais (liderança).")
    async def cmd_meta(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return
        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode acessar o painel de metas.", ephemeral=True)
            return
        week_id = current_week_id()
        meta    = db_get_meta(guild_id, week_id)
        embed   = build_meta_embed(meta, week_id)
        await interaction.response.send_message(embed=embed, view=MetaView(self, guild_id, week_id), ephemeral=True)

    @app_commands.command(name="farm", description="Seu painel de farm semanal.")
    async def cmd_farm(self, interaction: discord.Interaction):
        if not _cmd_enabled("farm"):
            await interaction.response.send_message("❌ Este comando está desativado pela administração.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return
        permitidos_ids = db_get_permitidos_role_ids(guild_id)
        if not is_permitido_farm(interaction.user, permitidos_ids):
            await interaction.response.send_message("❌ Você não tem permissão para usar o farm.", ephemeral=True)
            return
        week_id = current_week_id()
        user_id = str(interaction.user.id)
        db_ensure_progresso(guild_id, week_id, user_id)
        meta  = db_get_meta(guild_id, week_id)
        prog  = db_get_progresso(guild_id, week_id, user_id)
        embed = build_farm_embed(meta, prog, interaction.user, week_id)
        await interaction.response.send_message(embed=embed, view=FarmView(self, guild_id, week_id, user_id), ephemeral=True)
        try:
            msg = await interaction.original_response()
            db_salvar_painel(guild_id, week_id, user_id, str(interaction.channel_id), str(msg.id))
        except Exception as e:
            log.warning(f"Não foi possível salvar referência do painel: {e}")

    @app_commands.command(name="resultado", description="Painel de resultados da semana (liderança).")
    async def cmd_resultado(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return
        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode ver resultados.", ephemeral=True)
            return
        week_id       = current_week_id()
        participantes = db_lista_progresso(guild_id, week_id)
        embed = discord.Embed(
            title="📊 Resultados da Semana",
            description=f"📅 Semana: `{format_date_br(week_id)}` — {len(participantes)} participante(s)",
            color=discord.Color.blue(), timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=ResultadoView(self, guild_id, week_id, participantes, interaction.guild),
            ephemeral=True,
        )

    @app_commands.command(name="historico", description="Histórico de lançamentos de um membro por semana.")
    @app_commands.describe(
        membro="Membro para consultar (deixe vazio para ver o seu próprio)",
        semana="Data da semana em DD/MM/AAAA (deixe vazio para a semana atual)",
    )
    async def cmd_historico(
        self,
        interaction: discord.Interaction,
        membro: discord.Member = None,
        semana: str = None,
    ):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return
        try:
            week_id = _week_id_consulta(semana)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if week_id > current_week_id():
            await interaction.response.send_message(
                "❌ Não é possível consultar uma semana futura.",
                ephemeral=True,
            )
            return
        alvo    = membro or interaction.user
        if membro and str(interaction.user.id) != str(membro.id):
            lideranca_ids = db_get_lideranca_role_ids(guild_id)
            if not is_lideranca(interaction.user, lideranca_ids):
                await interaction.response.send_message("❌ Apenas liderança pode ver o histórico de outros membros.", ephemeral=True)
                return
        eventos = db_eventos_usuario(guild_id, week_id, str(alvo.id))
        embed = discord.Embed(
            title=f"📋 Histórico — {alvo.display_name}",
            description=f"📅 Semana: `{format_week_range_br(week_id)}`",
            color=discord.Color.blue(), timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=alvo.display_avatar.url)
        if not eventos:
            embed.add_field(name="Sem lançamentos", value="Nenhum lançamento encontrado nesta semana.", inline=False)
        else:
            linhas = []
            for i, ev in enumerate(eventos, 1):
                ev_itens = db_evento_itens(ev)
                partes   = [f"{nome}: `{qtd}`" for nome, qtd in ev_itens.items() if qtd > 0]
                conteudo = " | ".join(partes) if partes else "todos zerados"
                linhas.append(f"`#{i}` {fmt_dt(ev['criado_em'])} — {conteudo}")
            chunk = "\n".join(linhas[:15])
            embed.add_field(name=f"{len(eventos)} lançamento(s)", value=chunk or "—", inline=False)
            if len(eventos) > 15:
                embed.set_footer(text=f"Exibindo 15 de {len(eventos)} lançamentos")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ranking", description="Ranking semanal atual ou histórico (liderança).")
    @app_commands.describe(
        semana="Data da semana em DD/MM/AAAA (deixe vazio para a semana atual)",
    )
    async def cmd_ranking(self, interaction: discord.Interaction, semana: str = None):
        guild_id = str(interaction.guild_id)
        if not db_is_farm_configured(guild_id):
            await interaction.response.send_message(
                "❌ O módulo Farm não está configurado. Um administrador deve usar `/setup_farm`.",
                ephemeral=True,
            )
            return
        lideranca_ids = db_get_lideranca_role_ids(guild_id)
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode ver o ranking.", ephemeral=True)
            return
        try:
            week_id = _week_id_consulta(semana)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if week_id > current_week_id():
            await interaction.response.send_message(
                "❌ Não é possível consultar uma semana futura.",
                ephemeral=True,
            )
            return
        participantes = db_ranking_semana(guild_id, week_id)
        embed = build_ranking_embed(guild_id, week_id, participantes, interaction.guild)
        embed.description = embed.description.replace(
            format_date_br(week_id),
            format_week_range_br(week_id),
            1,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FarmCog(bot))
    log.info("FarmCog adicionado ao bot.")
