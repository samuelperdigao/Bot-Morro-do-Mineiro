"""
cogs/recolhimento.py - Sistema de Recolhimento Semanal.

/recolhimento → liderança inicia ciclo de dinheiro sujo ou farm no canal.
Embeds fixos atualizados a cada entrega via message.edit().
Task de fechamento (a cada 5 min) encerra os ciclos de painel cuja semana
terminou; o ciclo encerrado continua pagável até ser marcado como pago.
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.date_utils import format_date_br
from core.logger import get_logger
from core.error_reporting import proteger_loop
from core.money import parse_money_br
from core.permissions import is_lideranca
from services.db_service import (
    DINHEIRO_ITEMS,
    current_week_id,
    now_tz,
    db_channel_map_get,
    db_evento_itens,
    db_get_lideranca_role_ids,
    db_get_meta,
    db_meta_tipo_efetivo,
    db_meta_itens_ativos,
    db_meta_dinheiro_ativo,
    db_meta_dinheiro_itens_ativos,
    db_prog_itens,
    db_lista_progresso,
    db_recolhimento_ciclo_aberto,
    db_recolhimento_ciclo_aberto_por_mensagem,
    db_recolhimento_ciclo_por_mensagem,
    db_recolhimento_criar_ciclo,
    db_recolhimento_salvar_message_id,
    db_recolhimento_get_ciclo,
    db_recolhimento_marcar_pago,
    db_recolhimento_encerrar,
    db_recolhimento_ciclos_vencidos,
    db_recolhimento_excluir_ciclo_vazio,
    db_recolhimento_add_entrega_dinheiro,
    db_recolhimento_add_entrega_itens,
    db_recolhimento_entrega_itens,
    db_recolhimento_get_entregas,
    db_ticket_launches,
)

log = get_logger("recolhimento", "recolhimento.log")

_KEY_LABELS = {
    "folha": "Borracha",
    "opio": "Aluminio",
    "seringa": "Cobre",
    "agulha": "Plastico",
}
# Itens do recolhimento de farm, na ordem exibida. Entregas antigas usam as
# colunas legadas (sem Ferro, que conta 0); as novas usam itens_json.
FARM_ITENS = (*_KEY_LABELS.values(), "Ferro")

LIMITE_FIELD = 1024
# Orçamento de caracteres para a lista de entregas (o embed inteiro tem
# limite de 6000; o restante fica para título, totais e status).
ORCAMENTO_ENTREGAS = 4200
MAX_FIELDS_ENTREGAS = 8
# Ciclos vencidos há mais tempo que isso são encerrados sem alerta (evita
# avisos em massa de semanas antigas quando o bot volta do ar).
DIAS_ALERTA_PENDENCIA = 7


# ── Helpers de formatação ─────────────────────────────────────────────────────

def _fmt_data_curta(iso: str) -> str:
    """'2026-05-05T...' → '05/05/2026'"""
    return format_date_br(iso)


def _fmt_valor(valor: float) -> str:
    """1500.0 → 'R$ 1.500,00'"""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _row_get(row, key: str, default=None):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _fmt_alvo_entrega(entrega) -> str:
    nome = _row_get(entrega, "alvo_nome") or _row_get(entrega, "alvo_user_id")
    pasta_id = _row_get(entrega, "alvo_pasta_id")
    if not nome:
        return "Membro: `Nao informado`"
    pasta = f" | Pasta: <#{pasta_id}>" if pasta_id else ""
    return f"Membro: `{nome}`{pasta}"


def _total_lancado_para_tipo(tipo: str, prog) -> int | float:
    itens = db_prog_itens(prog)
    if tipo == "dinheiro":
        return sum(itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
    return sum(qtd for nome, qtd in itens.items() if nome not in DINHEIRO_ITEMS)


def _ciclo_da_mensagem(interaction: discord.Interaction, tipo: str, incluir_encerrado: bool = False):
    if not interaction.message:
        return None
    buscar = (
        db_recolhimento_ciclo_por_mensagem
        if incluir_encerrado
        else db_recolhimento_ciclo_aberto_por_mensagem
    )
    return buscar(
        str(interaction.guild_id),
        str(interaction.channel_id),
        tipo,
        str(interaction.message.id),
    )


def _semana_fim_from_inicio(semana_inicio: str) -> str:
    """Segunda-feira → domingo (+ 6 dias)."""
    inicio = datetime.date.fromisoformat(semana_inicio)
    return (inicio + datetime.timedelta(days=6)).isoformat()


def _valor_dinheiro(entrega) -> float:
    """Valor de uma entrega de dinheiro (coluna legada ou itens_json)."""
    valor = _row_get(entrega, "valor")
    if valor:
        return float(valor)
    return float(sum(float(v or 0) for v in db_recolhimento_entrega_itens(entrega).values()))


def _itens_farm(entrega) -> dict[str, int]:
    """Itens de uma entrega de farm (colunas legadas ou itens_json)."""
    return {
        nome: int(qtd or 0)
        for nome, qtd in db_recolhimento_entrega_itens(entrega).items()
    }


def _totais_farm(entregas: list) -> dict[str, int]:
    totais = {nome: 0 for nome in FARM_ITENS}
    for entrega in entregas:
        for nome, qtd in _itens_farm(entrega).items():
            totais[nome] = totais.get(nome, 0) + qtd
    return totais


def _fmt_itens_farm(itens: dict[str, int]) -> str:
    extras = sorted(nome for nome in itens if nome not in FARM_ITENS and itens[nome])
    return " | ".join(f"{nome}: {itens.get(nome, 0)}" for nome in (*FARM_ITENS, *extras))


def _dividir_linhas_em_fields(linhas: list[str]) -> tuple[list[str], int]:
    """Agrupa linhas em blocos de até 1024 caracteres.

    Se tudo não couber no orçamento do embed, mantém as entregas mais
    recentes e devolve quantas das mais antigas ficaram de fora.
    """
    selecionadas: list[str] = []
    usados = 0
    for linha in reversed(linhas):
        custo = min(len(linha), LIMITE_FIELD) + 1
        if usados + custo > ORCAMENTO_ENTREGAS:
            break
        selecionadas.append(linha)
        usados += custo
    selecionadas.reverse()
    omitidas = len(linhas) - len(selecionadas)

    blocos: list[str] = []
    atual = ""
    for linha in selecionadas:
        linha = linha[:LIMITE_FIELD]
        candidato = f"{atual}\n{linha}" if atual else linha
        if len(candidato) > LIMITE_FIELD:
            blocos.append(atual)
            atual = linha
        else:
            atual = candidato
    if atual:
        blocos.append(atual)
    if len(blocos) > MAX_FIELDS_ENTREGAS:
        excedentes = blocos[:-MAX_FIELDS_ENTREGAS]
        omitidas += sum(bloco.count("\n") + 1 for bloco in excedentes)
        blocos = blocos[-MAX_FIELDS_ENTREGAS:]
    return blocos, omitidas


def _adicionar_entregas(embed: discord.Embed, linhas: list[str]) -> None:
    """Adiciona as entregas em fields de até 1024 caracteres.

    Antes todas iam num field só e o embed parava de atualizar depois de
    5 a 7 entregas (o Discord recusava o field acima do limite).
    """
    if not linhas:
        return
    blocos, omitidas = _dividir_linhas_em_fields(linhas)
    total = len(blocos)
    for i, bloco in enumerate(blocos, 1):
        nome = "Entregas" if total == 1 else f"Entregas ({i}/{total})"
        if i == 1 and omitidas:
            nome += f" — {omitidas} mais antiga(s) oculta(s)"
        embed.add_field(name=nome[:256], value=bloco, inline=False)


def _adicionar_status(embed: discord.Embed, ciclo) -> None:
    if ciclo["pago"]:
        data_pag = _fmt_data_curta(ciclo["data_pagamento"])
        embed.add_field(
            name="STATUS",
            value=(
                f"🟡 Pago\n"
                f"Data: {data_pag}\n"
                f"Pago por: <@{ciclo['pago_por']}>\n"
                f"Observação: {(ciclo['observacao_pagamento'] or '—')[:300]}"
            ),
            inline=False,
        )
    elif ciclo["encerrado"]:
        embed.add_field(name="STATUS", value="🔒 Encerrado — pagamento pendente", inline=True)
    else:
        embed.add_field(name="STATUS", value="⏳ Pendente", inline=True)


def _motivo_ciclo_fechado(ciclo) -> str | None:
    """Mensagem de recusa se o ciclo não aceita mais registros."""
    if ciclo is None:
        return "❌ Ciclo não encontrado."
    if ciclo["pago"]:
        return "⚠️ Este ciclo já foi pago e não aceita novos registros."
    if ciclo["encerrado"]:
        return "⚠️ Este ciclo já foi encerrado e não aceita novos registros."
    return None


# ── Builders de embed ─────────────────────────────────────────────────────────

def build_embed_dinheiro(ciclo, entregas: list) -> discord.Embed:
    inicio_fmt = _fmt_data_curta(ciclo["semana_inicio"])
    fim_fmt    = _fmt_data_curta(ciclo["semana_fim"])

    embed = discord.Embed(
        title="🔴 DINHEIRO SUJO",
        description=f"Ciclo {inicio_fmt} → {fim_fmt}",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )

    total = 0.0
    linhas = []
    for i, e in enumerate(entregas, 1):
        valor = _valor_dinheiro(e)
        total += valor
        linhas.append(
            f"Recolhimento {i:02d} | {_fmt_data_curta(e['data'])} | {_fmt_valor(valor)} | "
            f"{_fmt_alvo_entrega(e)} | Recolhido por <@{e['registrado_por']}>"
        )
    _adicionar_entregas(embed, linhas)

    embed.add_field(name="TOTAL", value=_fmt_valor(total), inline=True)
    _adicionar_status(embed, ciclo)

    embed.set_footer(text=f"ID do ciclo: {ciclo['id']}")
    return embed


def build_embed_farm(ciclo, entregas: list) -> discord.Embed:
    inicio_fmt = _fmt_data_curta(ciclo["semana_inicio"])
    fim_fmt    = _fmt_data_curta(ciclo["semana_fim"])

    embed = discord.Embed(
        title="🟢 FARM",
        description=f"Ciclo {inicio_fmt} → {fim_fmt}",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )

    linhas = []
    for i, e in enumerate(entregas, 1):
        linhas.append(
            f"Recolhimento {i:02d} | {_fmt_data_curta(e['data'])} | "
            + _fmt_itens_farm(_itens_farm(e))
            + f" | {_fmt_alvo_entrega(e)} | Recolhido por <@{e['registrado_por']}>"
        )
    _adicionar_entregas(embed, linhas)

    embed.add_field(name="TOTAL", value=_fmt_itens_farm(_totais_farm(entregas)), inline=False)
    _adicionar_status(embed, ciclo)

    embed.set_footer(text=f"ID do ciclo: {ciclo['id']}")
    return embed


# ── Modals ────────────────────────────────────────────────────────────────────

class RecolhimentoDinheiroModal(discord.ui.Modal, title="💰 Registrar Recolhimento"):
    valor_input = discord.ui.TextInput(
        label="Valor (R$)",
        placeholder="Ex: 1500 ou R$ 1.500,00",
        required=True,
        max_length=20,
    )

    def __init__(
        self,
        ciclo_id: int,
        alvo_user_id: str,
        alvo_nome: str,
        alvo_pasta_id: str | None = None,
    ):
        super().__init__()
        self.ciclo_id = ciclo_id
        self.alvo_user_id = alvo_user_id
        self.alvo_nome = alvo_nome
        self.alvo_pasta_id = alvo_pasta_id

    async def on_submit(self, interaction: discord.Interaction):
        motivo = _motivo_ciclo_fechado(db_recolhimento_get_ciclo(self.ciclo_id))
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return
        try:
            valor = parse_money_br(self.valor_input.value)
            if valor <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valor inválido. Use apenas o número, ex: `1500` ou `R$ 1.500,00`.",
                ephemeral=True,
            )
            return

        db_recolhimento_add_entrega_dinheiro(
            self.ciclo_id,
            str(interaction.user.id),
            valor,
            self.alvo_user_id,
            self.alvo_nome,
            self.alvo_pasta_id,
        )
        await interaction.response.send_message(
            f"✅ Recolhimento de {_fmt_valor(valor)} registrado para **{self.alvo_nome}**!",
            ephemeral=True,
        )
        cog = interaction.client.get_cog("RecolhimentoCog")
        if cog:
            await cog._atualizar_embed_ciclo(interaction.guild, self.ciclo_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em RecolhimentoDinheiroModal: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro ao registrar.", ephemeral=True)


class RecolhimentoFarmModal(discord.ui.Modal, title="Kit Desmanche"):
    folha_input   = discord.ui.TextInput(label="Borracha",  placeholder="0", required=False, max_length=10)
    opio_input    = discord.ui.TextInput(label="Aluminio",  placeholder="0", required=False, max_length=10)
    seringa_input = discord.ui.TextInput(label="Cobre",     placeholder="0", required=False, max_length=10)
    agulha_input  = discord.ui.TextInput(label="Plastico",  placeholder="0", required=False, max_length=10)
    ferro_input   = discord.ui.TextInput(label="Ferro",     placeholder="0", required=False, max_length=10)

    def __init__(
        self,
        ciclo_id: int,
        alvo_user_id: str,
        alvo_nome: str,
        alvo_pasta_id: str | None = None,
    ):
        super().__init__()
        self.ciclo_id = ciclo_id
        self.alvo_user_id = alvo_user_id
        self.alvo_nome = alvo_nome
        self.alvo_pasta_id = alvo_pasta_id

    async def on_submit(self, interaction: discord.Interaction):
        motivo = _motivo_ciclo_fechado(db_recolhimento_get_ciclo(self.ciclo_id))
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return
        campos = (
            ("Borracha", self.folha_input),
            ("Aluminio", self.opio_input),
            ("Cobre", self.seringa_input),
            ("Plastico", self.agulha_input),
            ("Ferro", self.ferro_input),
        )
        try:
            quantidades = {nome: max(0, int(campo.value or 0)) for nome, campo in campos}
        except ValueError:
            await interaction.response.send_message(
                "❌ Valores inválidos. Use números inteiros.", ephemeral=True
            )
            return

        if sum(quantidades.values()) == 0:
            await interaction.response.send_message(
                "❌ Informe pelo menos um valor acima de zero.", ephemeral=True
            )
            return

        db_recolhimento_add_entrega_itens(
            self.ciclo_id,
            str(interaction.user.id),
            {nome: qtd for nome, qtd in quantidades.items() if qtd > 0},
            self.alvo_user_id,
            self.alvo_nome,
            self.alvo_pasta_id,
        )
        await interaction.response.send_message(
            f"✅ Recolhimento registrado para **{self.alvo_nome}**! "
            + " | ".join(f"{nome}: {qtd}" for nome, qtd in quantidades.items()),
            ephemeral=True,
        )
        cog = interaction.client.get_cog("RecolhimentoCog")
        if cog:
            await cog._atualizar_embed_ciclo(interaction.guild, self.ciclo_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em RecolhimentoFarmModal: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro ao registrar.", ephemeral=True)


def _itens_meta_recolhimento(meta) -> tuple[str, dict[str, float]]:
    meta_tipo = db_meta_tipo_efetivo(meta)
    if meta_tipo == "dinheiro":
        itens = db_meta_dinheiro_itens_ativos(meta)
        if itens:
            return meta_tipo, {nome: float(valor) for nome, valor in itens.items()}
        total = float(db_meta_dinheiro_ativo(meta))
        return meta_tipo, {"Dinheiro": total} if total > 0 else {}
    return meta_tipo, {
        nome: float(valor)
        for nome, valor in db_meta_itens_ativos(meta).items()
        if float(valor or 0) > 0
    }


def _saldo_recolhimento_ticket(
    ticket_id: int,
    ciclo_id: int,
    item_names: list[str],
) -> dict[str, float]:
    movimentos: dict[str, list[tuple[int, dict]]] = {}
    for lancamento in db_ticket_launches(ticket_id):
        movimentos.setdefault(lancamento["criado_em"], []).append(
            (0, db_evento_itens(lancamento))
        )
    for entrega in db_recolhimento_get_entregas(ciclo_id):
        movimentos.setdefault(entrega["data"], []).append(
            (1, db_recolhimento_entrega_itens(entrega))
        )

    saldos = {nome: 0.0 for nome in item_names}
    for timestamp in sorted(movimentos):
        adicionados = {nome: 0.0 for nome in item_names}
        retirados = {nome: 0.0 for nome in item_names}
        for tipo_movimento, valores in movimentos[timestamp]:
            destino = adicionados if tipo_movimento == 0 else retirados
            for nome, valor in valores.items():
                if nome in destino:
                    destino[nome] += float(valor or 0)
        for nome in item_names:
            disponivel_no_instante = saldos[nome] + adicionados[nome]
            if retirados[nome] > disponivel_no_instante:
                saldos[nome] = max(saldos[nome] - retirados[nome], 0) + adicionados[nome]
            else:
                saldos[nome] = disponivel_no_instante - retirados[nome]
    return saldos


class RecolhimentoMetaModal(discord.ui.Modal):
    def __init__(
        self,
        ciclo_id: int,
        ticket_id: int,
        guild_id: str,
        week_id: str,
        meta_tipo: str,
        disponiveis: dict[str, float],
        alvo_user_id: str,
        alvo_nome: str,
        alvo_pasta_id: str | None = None,
        alvo_slot: int | None = None,
    ):
        titulo = {
            "colete": "Recolher Materiais de Colete",
            "dinheiro": "Recolher Dinheiro",
            "itens": "Recolher Kit Desmanche",
        }.get(meta_tipo, "Registrar Recolhimento")
        super().__init__(title=titulo)
        self.ciclo_id = ciclo_id
        self.ticket_id = ticket_id
        self.guild_id = guild_id
        self.week_id = week_id
        self.meta_tipo = meta_tipo
        self.item_names = list(disponiveis)[:5]
        self.alvo_user_id = alvo_user_id
        self.alvo_nome = alvo_nome
        self.alvo_pasta_id = alvo_pasta_id
        self.alvo_slot = alvo_slot
        self.disponiveis = dict(disponiveis)
        self.inputs: list[discord.ui.TextInput] = []
        for nome in self.item_names:
            disponivel = disponiveis[nome]
            saldo = _fmt_valor(disponivel) if meta_tipo == "dinheiro" else str(int(disponivel))
            field = discord.ui.TextInput(
                label=f"{nome} | disponível: {saldo}"[:45],
                placeholder="Digite a quantidade a recolher",
                required=False,
                max_length=20,
                default=saldo,
            )
            self.add_item(field)
            self.inputs.append(field)

    async def on_submit(self, interaction: discord.Interaction):
        meta_tipo, itens_atuais = _itens_meta_recolhimento(
            db_get_meta(self.guild_id, self.week_id)
        )
        if meta_tipo != self.meta_tipo or list(itens_atuais)[:5] != self.item_names:
            await interaction.response.send_message(
                "A meta da semana mudou. Abra o recolhimento novamente.", ephemeral=True
            )
            return

        disponiveis = _saldo_recolhimento_ticket(
            self.ticket_id,
            self.ciclo_id,
            self.item_names,
        )

        valores = {}
        try:
            for nome, field in zip(self.item_names, self.inputs):
                if self.meta_tipo == "dinheiro":
                    valor = parse_money_br(field.value)
                else:
                    raw = (field.value or "0").replace("R$", "").replace(".", "").replace(",", ".").strip()
                    valor = int(raw or 0)
                if valor < 0:
                    raise ValueError
                if valor > 0:
                    valores[nome] = valor
        except ValueError:
            await interaction.response.send_message(
                "Informe apenas valores positivos válidos.", ephemeral=True
            )
            return
        if not valores:
            await interaction.response.send_message(
                "Informe pelo menos um valor acima de zero.", ephemeral=True
            )
            return
        excedidos = {
            nome: (valor, disponiveis.get(nome, 0))
            for nome, valor in valores.items()
            if float(valor) > disponiveis.get(nome, 0)
        }
        if excedidos:
            detalhes = " | ".join(
                f"{nome}: solicitado {valor:g}, disponível {saldo:g}"
                for nome, (valor, saldo) in excedidos.items()
            )
            await interaction.response.send_message(
                f"Não é possível recolher acima do saldo lançado. {detalhes}",
                ephemeral=True,
            )
            return

        db_recolhimento_add_entrega_itens(
            self.ciclo_id,
            str(interaction.user.id),
            valores,
            self.alvo_user_id,
            self.alvo_nome,
            self.alvo_pasta_id,
        )
        resumo = " | ".join(
            f"{nome}: {_fmt_valor(valor) if self.meta_tipo == 'dinheiro' else int(valor)}"
            for nome, valor in valores.items()
        )
        linhas_quantidades = "\n".join(
            f"• **{nome}:** {_fmt_valor(valor) if self.meta_tipo == 'dinheiro' else int(valor)}"
            for nome, valor in valores.items()
        )
        await interaction.response.send_message(
            f"✅ Recolhimento registrado para **{self.alvo_nome}**! {resumo}",
            ephemeral=True,
        )
        slot = f"{int(self.alvo_slot):02d}" if self.alvo_slot is not None else "Não informado"
        embed = discord.Embed(
            title="📦 Recolhimento confirmado",
            description=f"O farm de <@{self.alvo_user_id}> foi recolhido com sucesso.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="📋 Quantidades recolhidas",
            value=linhas_quantidades,
            inline=False,
        )
        embed.add_field(
            name="👮 Recolhido por",
            value=f"<@{interaction.user.id}>",
            inline=True,
        )
        embed.add_field(name="📁 Slot da pasta", value=f"`{slot}`", inline=True)
        embed.set_footer(text="O saldo disponível foi atualizado automaticamente.")
        await interaction.channel.send(embed=embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em RecolhimentoMetaModal: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro ao registrar.", ephemeral=True)


class PagamentoModal(discord.ui.Modal, title="💳 Confirmar Pagamento"):
    observacao_input = discord.ui.TextInput(
        label="Observação",
        placeholder="Ex: Pago via PIX direto",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )

    def __init__(self, ciclo_id: int):
        super().__init__()
        self.ciclo_id = ciclo_id

    async def on_submit(self, interaction: discord.Interaction):
        ciclo = db_recolhimento_get_ciclo(self.ciclo_id)
        if not ciclo:
            await interaction.response.send_message("❌ Ciclo não encontrado.", ephemeral=True)
            return
        if ciclo["pago"]:
            await interaction.response.send_message(
                "⚠️ Este ciclo já foi marcado como pago.", ephemeral=True
            )
            return

        observacao = self.observacao_input.value.strip() or "—"
        if not db_recolhimento_marcar_pago(self.ciclo_id, str(interaction.user.id), observacao):
            await interaction.response.send_message(
                "⚠️ Este ciclo já foi marcado como pago.", ephemeral=True
            )
            return
        await interaction.response.send_message("✅ Ciclo marcado como pago!", ephemeral=True)

        cog = interaction.client.get_cog("RecolhimentoCog")
        if cog:
            await cog._atualizar_embed_ciclo(interaction.guild, self.ciclo_id, remover_view=True)

        # Notificação pública
        try:
            canal = interaction.guild.get_channel(int(ciclo["channel_id"])) or \
                    await interaction.guild.fetch_channel(int(ciclo["channel_id"]))
            entregas  = db_recolhimento_get_entregas(self.ciclo_id)
            tipo      = ciclo["tipo"]
            inicio_fmt = _fmt_data_curta(ciclo["semana_inicio"])
            fim_fmt    = _fmt_data_curta(ciclo["semana_fim"])

            if tipo == "dinheiro":
                total  = sum(_valor_dinheiro(e) for e in entregas)
                resumo = f"Total recolhido: {_fmt_valor(total)}"
                emoji  = "🔴"
                label  = "Dinheiro Sujo"
            else:
                resumo = _fmt_itens_farm(_totais_farm(entregas))
                emoji  = "🟢"
                label  = "Farm"

            notif = discord.Embed(
                title=f"{emoji} Recolhimento Pago — {label}",
                description=f"Ciclo {inicio_fmt} → {fim_fmt}\n\n{resumo}",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )
            notif.add_field(name="Pago por",   value=interaction.user.mention, inline=True)
            notif.add_field(name="Observação", value=observacao[:1024],        inline=True)
            await canal.send(embed=notif)
        except Exception as e:
            log.warning("Falha ao enviar notificação de pagamento (ciclo %s): %s", self.ciclo_id, e)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em PagamentoModal: %s", error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Erro ao confirmar pagamento.", ephemeral=True)


async def _membros_com_lancamento(guild: discord.Guild, guild_id: str, week_id: str, tipo: str) -> list[dict]:
    entradas = []
    for prog in db_lista_progresso(guild_id, week_id):
        total = _total_lancado_para_tipo(tipo, prog)
        if total <= 0:
            continue

        user_id = str(prog["user_id"])
        # Só o cache: um fetch por membro estourava os 3s da interação.
        member = guild.get_member(int(user_id))
        nome = member.display_name if member else f"ID {user_id}"
        pasta_id = db_channel_map_get(guild_id, user_id)
        pasta_label = "Sem pasta vinculada"
        if pasta_id:
            canal = guild.get_channel(pasta_id)
            pasta_label = f"#{canal.name}" if canal else f"Pasta ID {pasta_id}"

        entradas.append({
            "user_id": user_id,
            "nome": nome,
            "pasta_id": str(pasta_id) if pasta_id else None,
            "pasta_label": pasta_label,
        })

    return entradas


async def _abrir_selecao_membro_recolhimento(
    interaction: discord.Interaction,
    ciclo,
    tipo: str,
):
    guild_id = str(interaction.guild_id)
    week_id = ciclo["semana_inicio"]
    entradas = await _membros_com_lancamento(interaction.guild, guild_id, week_id, tipo)
    if not entradas:
        tipo_label = "dinheiro" if tipo == "dinheiro" else "farm"
        await interaction.response.send_message(
            f"⚠️ Nenhum membro com lançamento de {tipo_label} nesta semana.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "Selecione o membro do qual você está recolhendo:",
        view=RecolhimentoMembroSelectView(ciclo["id"], tipo, entradas),
        ephemeral=True,
    )


class RecolhimentoMembroSelectView(discord.ui.View):
    POR_PAGINA = 25

    def __init__(self, ciclo_id: int, tipo: str, entradas: list[dict], pagina: int = 0):
        super().__init__(timeout=120)
        self.ciclo_id = ciclo_id
        self.tipo = tipo
        self.entradas = entradas
        self.pagina = pagina
        self._rebuild()

    def _total_paginas(self) -> int:
        return max(1, (len(self.entradas) + self.POR_PAGINA - 1) // self.POR_PAGINA)

    def _rebuild(self):
        self.clear_items()
        inicio = self.pagina * self.POR_PAGINA
        fatia = self.entradas[inicio: inicio + self.POR_PAGINA]
        opcoes = [
            discord.SelectOption(
                label=entrada["nome"][:100],
                value=entrada["user_id"],
                description=entrada["pasta_label"][:100],
            )
            for entrada in fatia
        ]

        select = discord.ui.Select(
            placeholder=f"Membros com lançamento (pág. {self.pagina + 1}/{self._total_paginas()})...",
            min_values=1,
            max_values=1,
            options=opcoes,
        )
        select.callback = self._on_select
        self.add_item(select)

        if self._total_paginas() > 1:
            prev_button = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                disabled=self.pagina == 0,
            )
            prev_button.callback = self._prev
            self.add_item(prev_button)

            next_button = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                disabled=self.pagina >= self._total_paginas() - 1,
            )
            next_button.callback = self._next
            self.add_item(next_button)

    def _entrada_por_user_id(self, user_id: str) -> dict | None:
        return next((entrada for entrada in self.entradas if entrada["user_id"] == user_id), None)

    async def _on_select(self, interaction: discord.Interaction):
        user_id = interaction.data.get("values", [None])[0]
        entrada = self._entrada_por_user_id(user_id)
        if not entrada:
            await interaction.response.send_message("❌ Membro não encontrado na lista.", ephemeral=True)
            return

        if self.tipo == "dinheiro":
            modal = RecolhimentoDinheiroModal(
                self.ciclo_id,
                entrada["user_id"],
                entrada["nome"],
                entrada["pasta_id"],
            )
        else:
            modal = RecolhimentoFarmModal(
                self.ciclo_id,
                entrada["user_id"],
                entrada["nome"],
                entrada["pasta_id"],
            )
        await interaction.response.send_modal(modal)

    async def _prev(self, interaction: discord.Interaction):
        self.pagina -= 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _next(self, interaction: discord.Interaction):
        self.pagina += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)


# ── PersistentViews ───────────────────────────────────────────────────────────

class RecolhimentoDinheiroView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📥 Registrar",
        style=discord.ButtonStyle.primary,
        custom_id="recolhimento:dinheiro_registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return
        ciclo = _ciclo_da_mensagem(interaction, "dinheiro")
        if not ciclo:
            await interaction.response.send_message(
                "❌ Ciclo não encontrado ou já encerrado. Use `/recolhimento` para criar um novo.",
                ephemeral=True,
            )
            return
        if ciclo["pago"]:
            await interaction.response.send_message("⚠️ Este ciclo já foi pago.", ephemeral=True)
            return
        await _abrir_selecao_membro_recolhimento(interaction, ciclo, "dinheiro")

    @discord.ui.button(
        label="✅ Marcar como Pago",
        style=discord.ButtonStyle.success,
        custom_id="recolhimento:dinheiro_pagar",
    )
    async def pagar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return
        # Ciclo encerrado continua pagável até ser marcado como pago.
        ciclo = _ciclo_da_mensagem(interaction, "dinheiro", incluir_encerrado=True)
        if not ciclo:
            await interaction.response.send_message("❌ Ciclo não encontrado.", ephemeral=True)
            return
        if ciclo["pago"]:
            await interaction.response.send_message("⚠️ Este ciclo já foi pago.", ephemeral=True)
            return
        await interaction.response.send_modal(PagamentoModal(ciclo["id"]))


class RecolhimentoFarmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📥 Registrar",
        style=discord.ButtonStyle.primary,
        custom_id="recolhimento:farm_registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return
        ciclo = _ciclo_da_mensagem(interaction, "farm")
        if not ciclo:
            await interaction.response.send_message(
                "❌ Ciclo não encontrado ou já encerrado. Use `/recolhimento` para criar um novo.",
                ephemeral=True,
            )
            return
        if ciclo["pago"]:
            await interaction.response.send_message("⚠️ Este ciclo já foi pago.", ephemeral=True)
            return
        await _abrir_selecao_membro_recolhimento(interaction, ciclo, "farm")

    @discord.ui.button(
        label="✅ Marcar como Pago",
        style=discord.ButtonStyle.success,
        custom_id="recolhimento:farm_pagar",
    )
    async def pagar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return
        # Ciclo encerrado continua pagável até ser marcado como pago.
        ciclo = _ciclo_da_mensagem(interaction, "farm", incluir_encerrado=True)
        if not ciclo:
            await interaction.response.send_message("❌ Ciclo não encontrado.", ephemeral=True)
            return
        if ciclo["pago"]:
            await interaction.response.send_message("⚠️ Este ciclo já foi pago.", ephemeral=True)
            return
        await interaction.response.send_modal(PagamentoModal(ciclo["id"]))


def _view_para_ciclo(ciclo) -> discord.ui.View | None:
    """View derivada do estado: sem botões se pago; só "Pagar" se encerrado."""
    if ciclo["pago"]:
        return None
    view = RecolhimentoDinheiroView() if ciclo["tipo"] == "dinheiro" else RecolhimentoFarmView()
    if ciclo["encerrado"]:
        view.registrar.disabled = True
    return view


# ── View de escolha do tipo (efêmera, não persistente) ───────────────────────

class EscolherTipoView(discord.ui.View):
    def __init__(self, cog: "RecolhimentoCog"):
        super().__init__(timeout=120)
        self.cog = cog

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="🔴 Dinheiro Sujo", style=discord.ButtonStyle.danger)
    async def btn_dinheiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._iniciar_ciclo(interaction, "dinheiro")

    @discord.ui.button(label="🟢 Farm", style=discord.ButtonStyle.success)
    async def btn_farm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._iniciar_ciclo(interaction, "farm")


# ── Cog ───────────────────────────────────────────────────────────────────────

class RecolhimentoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(RecolhimentoDinheiroView())
        bot.add_view(RecolhimentoFarmView())
        proteger_loop(self._fechamento_ciclos, "recolhimento_fechamento", lambda: self.bot)
        self._fechamento_ciclos.start()
        log.info("RecolhimentoCog inicializado.")

    def cog_unload(self):
        self._fechamento_ciclos.cancel()

    def _modal_recolhimento_ticket(self, ticket, registrado_por: str):
        meta_tipo, itens = _itens_meta_recolhimento(
            db_get_meta(ticket["guild_id"], ticket["week_id"])
        )
        if not itens:
            return None
        ciclo = db_recolhimento_ciclo_aberto(
            ticket["guild_id"],
            ticket["channel_id"],
            meta_tipo,
            ticket["week_id"],
        )
        if not ciclo:
            ciclo_id = db_recolhimento_criar_ciclo(
                guild_id=ticket["guild_id"],
                member_id=registrado_por,
                channel_id=ticket["channel_id"],
                tipo=meta_tipo,
                semana_inicio=ticket["week_id"],
                semana_fim=_semana_fim_from_inicio(ticket["week_id"]),
            )
        else:
            ciclo_id = int(ciclo["id"])

        alvo_nome = _row_get(ticket, "folder_nickname") or ticket["member_name"]
        alvo_pasta_id = _row_get(ticket, "folder_channel_id")
        alvo_slot = _row_get(ticket, "folder_slot")
        disponiveis = _saldo_recolhimento_ticket(
            int(ticket["id"]),
            ciclo_id,
            list(itens)[:5],
        )
        return RecolhimentoMetaModal(
            ciclo_id,
            int(ticket["id"]),
            ticket["guild_id"],
            ticket["week_id"],
            meta_tipo,
            disponiveis,
            ticket["user_id"],
            alvo_nome,
            alvo_pasta_id,
            alvo_slot,
        )

    async def _atualizar_embed_ciclo(
        self,
        guild: discord.Guild,
        ciclo_id: int,
        remover_view: bool = False,
    ):
        """Edita o embed existente do ciclo com dados atualizados."""
        ciclo = db_recolhimento_get_ciclo(ciclo_id)
        if not ciclo or not ciclo["message_id"] or not ciclo["channel_id"]:
            return

        try:
            canal = guild.get_channel(int(ciclo["channel_id"])) or \
                    await guild.fetch_channel(int(ciclo["channel_id"]))
            msg = await canal.fetch_message(int(ciclo["message_id"]))
        except (discord.NotFound, discord.Forbidden, Exception) as e:
            log.warning("Falha ao buscar mensagem do ciclo %s: %s", ciclo_id, e)
            return

        entregas = db_recolhimento_get_entregas(ciclo_id)
        if ciclo["tipo"] == "dinheiro":
            embed = build_embed_dinheiro(ciclo, entregas)
        else:
            embed = build_embed_farm(ciclo, entregas)
        # A view segue o estado do ciclo: nunca reativa botões de um ciclo
        # pago ou encerrado.
        view = None if remover_view else _view_para_ciclo(ciclo)

        try:
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            log.warning("Falha ao editar mensagem do ciclo %s: %s", ciclo_id, e)

    async def _iniciar_ciclo(self, interaction: discord.Interaction, tipo: str):
        """Cria e posta um ciclo no canal (no máximo um aberto por tipo/semana/canal)."""
        guild_id    = str(interaction.guild_id)
        channel_id  = str(interaction.channel_id)
        week_inicio = current_week_id()
        week_fim    = _semana_fim_from_inicio(week_inicio)
        tipo_label  = "Dinheiro Sujo" if tipo == "dinheiro" else "Farm"

        # Responde editando a mensagem de escolha: some com os botões (evita
        # duplo clique criando ciclos repetidos) e responde em menos de 3s.
        await interaction.response.edit_message(
            content=f"⏳ Criando ciclo de **{tipo_label}**...", view=None
        )

        existente = db_recolhimento_ciclo_aberto(guild_id, channel_id, tipo, week_inicio)
        if existente and existente["message_id"]:
            link = f"https://discord.com/channels/{guild_id}/{channel_id}/{existente['message_id']}"
            await interaction.edit_original_response(
                content=f"⚠️ Já existe um ciclo de **{tipo_label}** aberto nesta semana neste canal: {link}"
            )
            return
        if existente:
            # Ciclo sem mensagem (órfão): reaproveita em vez de duplicar.
            ciclo_id = existente["id"]
        else:
            ciclo_id = db_recolhimento_criar_ciclo(
                guild_id=guild_id,
                member_id=str(interaction.user.id),
                channel_id=channel_id,
                tipo=tipo,
                semana_inicio=week_inicio,
                semana_fim=week_fim,
            )

        ciclo    = db_recolhimento_get_ciclo(ciclo_id)
        entregas = db_recolhimento_get_entregas(ciclo_id)
        if tipo == "dinheiro":
            embed = build_embed_dinheiro(ciclo, entregas)
        else:
            embed = build_embed_farm(ciclo, entregas)

        try:
            canal = interaction.channel
            if canal is None:
                canal = interaction.guild.get_channel(int(channel_id)) or \
                        await interaction.guild.fetch_channel(int(channel_id))
            msg = await canal.send(embed=embed, view=_view_para_ciclo(ciclo))
        except discord.Forbidden:
            db_recolhimento_excluir_ciclo_vazio(ciclo_id)
            await interaction.edit_original_response(
                content="❌ O bot não tem permissão para enviar mensagens neste canal."
            )
            return
        except Exception:
            db_recolhimento_excluir_ciclo_vazio(ciclo_id)
            raise
        db_recolhimento_salvar_message_id(ciclo_id, str(msg.id))

        await interaction.edit_original_response(
            content=(
                f"✅ Ciclo de **{tipo_label}** criado!\n"
                f"Semana: `{format_date_br(week_inicio)}` → `{format_date_br(week_fim)}`"
            )
        )
        log.info(
            "Ciclo criado: id=%s tipo=%s guild=%s canal=%s semana=%s",
            ciclo_id, tipo, guild_id, channel_id, week_inicio,
        )

    @app_commands.command(
        name="recolhimento",
        description="Inicia um ciclo de recolhimento semanal (dinheiro sujo ou farm).",
    )
    async def cmd_recolhimento(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not is_lideranca(interaction.user, db_get_lideranca_role_ids(guild_id)):
            await interaction.response.send_message(
                "❌ Apenas liderança pode iniciar ciclos de recolhimento.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Escolha o tipo de recolhimento para esta semana:",
            view=EscolherTipoView(self),
            ephemeral=True,
        )

    @tasks.loop(minutes=5)
    async def _fechamento_ciclos(self):
        """Encerra os ciclos de painel cuja semana terminou (domingo 23:59).

        Roda a cada 5 minutos e logo que o bot liga, então semanas em que o
        bot estava fora do ar no horário do fechamento também são encerradas.
        """
        agora = now_tz()
        hoje = agora.date()
        incluir_hoje = hoje.weekday() == 6 and (agora.hour, agora.minute) >= (23, 59)
        ciclos = db_recolhimento_ciclos_vencidos(hoje.isoformat(), incluir_hoje)
        if not ciclos:
            return

        log.info("Task de fechamento: %s ciclo(s) para encerrar em %s", len(ciclos), hoje)
        for ciclo in ciclos:
            # Erro num ciclo não impede o fechamento dos demais.
            try:
                await self._encerrar_ciclo(ciclo, hoje)
            except Exception:
                log.error("Falha ao encerrar ciclo %s", ciclo["id"], exc_info=True)

    async def _encerrar_ciclo(self, ciclo, hoje: datetime.date):
        db_recolhimento_encerrar(ciclo["id"])
        log.info("Ciclo encerrado: id=%s guild=%s", ciclo["id"], ciclo["guild_id"])

        guild = self.bot.get_guild(int(ciclo["guild_id"]))
        if not guild:
            return

        # O botão "Marcar como Pago" continua ativo até o pagamento.
        await self._atualizar_embed_ciclo(guild, ciclo["id"])

        if ciclo["pago"] or not db_recolhimento_get_entregas(ciclo["id"]):
            return
        semana_fim = datetime.date.fromisoformat(ciclo["semana_fim"])
        if (hoje - semana_fim).days > DIAS_ALERTA_PENDENCIA:
            return
        try:
            canal = guild.get_channel(int(ciclo["channel_id"])) or \
                    await guild.fetch_channel(int(ciclo["channel_id"]))
            tipo_label = "Dinheiro Sujo" if ciclo["tipo"] == "dinheiro" else "Farm"
            alerta = discord.Embed(
                title="⚠️ Recolhimento Encerrado — Pagamento Pendente",
                description=(
                    f"O ciclo de **{tipo_label}** "
                    f"({_fmt_data_curta(ciclo['semana_inicio'])} → {_fmt_data_curta(ciclo['semana_fim'])}) "
                    "ainda **não foi marcado como pago**.\n\n"
                    "O botão **✅ Marcar como Pago** continua disponível na mensagem do ciclo."
                ),
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            await canal.send(embed=alerta)
        except Exception as e:
            log.warning("Falha ao enviar alerta de pendência (ciclo %s): %s", ciclo["id"], e)

    @_fechamento_ciclos.before_loop
    async def _before_fechamento(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RecolhimentoCog(bot))
    log.info("RecolhimentoCog adicionado ao bot.")
