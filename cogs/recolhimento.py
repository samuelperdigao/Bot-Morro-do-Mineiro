"""
cogs/recolhimento.py - Sistema de Recolhimento Semanal.

/recolhimento → liderança inicia ciclo de dinheiro sujo ou farm no canal.
Embeds fixos atualizados a cada entrega via message.edit().

Estados do ciclo: aberto (aceita registros) → encerrado (domingo 23:59; não
aceita registros, mas ainda pode ser pago) → pago.
A task de fechamento roda a cada 5 minutos e encerra todo ciclo cuja semana
já terminou, inclusive semanas em que o bot estava fora do ar.
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.date_utils import format_date_br
from core.logger import get_logger
from core.money import fmt_brl, parse_money_br
from core.error_reporting import proteger_loop
from core.permissions import is_lideranca
from services.db_service import (
    DINHEIRO_ITEMS,
    TZ,
    current_week_id,
    now_tz,
    db_channel_map_get,
    db_get_lideranca_role_ids,
    db_prog_itens,
    db_lista_progresso,
    db_recolhimento_ciclo_aberto,
    db_recolhimento_ciclo_aberto_por_mensagem,
    db_recolhimento_ciclo_por_mensagem,
    db_recolhimento_excluir_ciclo_vazio,
    db_recolhimento_criar_ciclo,
    db_recolhimento_salvar_message_id,
    db_recolhimento_get_ciclo,
    db_recolhimento_marcar_pago,
    db_recolhimento_encerrar,
    db_recolhimento_ciclos_para_encerrar,
    db_recolhimento_add_entrega_dinheiro,
    db_recolhimento_add_entrega_farm,
    db_recolhimento_get_entregas,
)

log = get_logger("recolhimento", "recolhimento.log")

COR_RECOLHIMENTO = 0xFFD700
FOOTER_RECOLHIMENTO = "Morro do Mineiro — Sistema de Recolhimento"
LIMITE_FIELD = 1024
# Orçamento de caracteres para a lista de entregas (o embed inteiro tem
# limite de 6000; o restante fica para título, totais e status).
ORCAMENTO_ENTREGAS = 4200
MAX_FIELDS_ENTREGAS = 8

# Colunas legadas do banco → nome do item.
_KEY_LABELS = {
    "folha": "Borracha",
    "opio": "Aluminio",
    "seringa": "Cobre",
    "agulha": "Plastico",
    "ferro": "Ferro",
}
FARM_KEYS = tuple(_KEY_LABELS)


# ── Helpers de formatação ─────────────────────────────────────────────────────

def _fmt_data_curta(iso: str) -> str:
    """'2026-05-05T...' → '05/05/2026'"""
    return format_date_br(iso)


def _fmt_valor(valor: float) -> str:
    """1500.0 → 'R$ 1.500,00'"""
    return fmt_brl(valor)


def _parse_valor_recolhimento(raw: str) -> float:
    """Valor de recolhimento em R$ (padrão brasileiro). Deve ser maior que zero."""
    valor = parse_money_br(raw)
    if valor <= 0:
        raise ValueError("valor deve ser maior que zero")
    return valor


def _fmt_data_dm(iso: str) -> str:
    """'2026-05-05T...' → '05/05'"""
    return format_date_br(iso)[:5]


def _dividir_linhas_em_fields(linhas: list[str]) -> tuple[list[str], int]:
    """Agrupa linhas em blocos de até 1024 caracteres.

    Se tudo não couber no orçamento do embed, mantém as entregas mais
    recentes e devolve quantas das mais antigas ficaram de fora.
    """
    selecionadas: list[str] = []
    usados = 0
    for linha in reversed(linhas):
        custo = len(linha) + 1
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
        omitidas += sum(b.count("\n") + 1 for b in excedentes)
        blocos = blocos[-MAX_FIELDS_ENTREGAS:]
    return blocos, omitidas


def _adicionar_entregas(embed: discord.Embed, linhas: list[str]) -> None:
    if not linhas:
        embed.add_field(name="Entregas", value="_Nenhuma entrega registrada ainda._", inline=False)
        return
    blocos, omitidas = _dividir_linhas_em_fields(linhas)
    total = len(blocos)
    for i, bloco in enumerate(blocos, 1):
        nome = "Entregas" if total == 1 else f"Entregas ({i}/{total})"
        if i == 1 and omitidas:
            nome += f" — {omitidas} mais antiga(s) oculta(s)"
        embed.add_field(name=nome[:256], value=bloco, inline=False)


def _status_ciclo(ciclo) -> str:
    if ciclo["pago"]:
        data_pag = _fmt_data_curta(ciclo["data_pagamento"])
        return (
            f"✅ **Pago** em {data_pag} por <@{ciclo['pago_por']}>\n"
            f"Observação: {(ciclo['observacao_pagamento'] or '—')[:300]}"
        )
    if ciclo["encerrado"]:
        return "🔒 **Encerrado** — pagamento pendente"
    return "⏳ **Aberto** — recebendo entregas"


def _rodape(ciclo) -> str:
    return f"{FOOTER_RECOLHIMENTO} • Ciclo #{ciclo['id']}"


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
    buscar = db_recolhimento_ciclo_por_mensagem if incluir_encerrado else db_recolhimento_ciclo_aberto_por_mensagem
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


# ── Builders de embed ─────────────────────────────────────────────────────────

def build_embed_dinheiro(ciclo, entregas: list) -> discord.Embed:
    inicio_fmt = _fmt_data_curta(ciclo["semana_inicio"])
    fim_fmt    = _fmt_data_curta(ciclo["semana_fim"])

    embed = discord.Embed(
        title="🔴 Recolhimento — Dinheiro Sujo",
        description=f"Semana {inicio_fmt} → {fim_fmt}",
        color=COR_RECOLHIMENTO,
        timestamp=discord.utils.utcnow(),
    )

    total = 0.0
    linhas = []
    for i, e in enumerate(entregas, 1):
        valor = e["valor"] or 0
        total += valor
        nome = _row_get(e, "alvo_nome") or _row_get(e, "alvo_user_id") or "Não informado"
        linhas.append(
            f"`{i:02d}` {_fmt_data_dm(e['data'])} • **{nome}** → **{_fmt_valor(valor)}** "
            f"• por <@{e['registrado_por']}>"
        )
    _adicionar_entregas(embed, linhas)

    embed.add_field(name="💰 Total recolhido", value=f"**{_fmt_valor(total)}**", inline=True)
    embed.add_field(name="📦 Entregas", value=str(len(entregas)), inline=True)
    embed.add_field(name="Status", value=_status_ciclo(ciclo), inline=False)
    embed.set_footer(text=_rodape(ciclo))
    return embed


def build_embed_farm(ciclo, entregas: list) -> discord.Embed:
    inicio_fmt = _fmt_data_curta(ciclo["semana_inicio"])
    fim_fmt    = _fmt_data_curta(ciclo["semana_fim"])

    embed = discord.Embed(
        title="🟢 Recolhimento — Farm",
        description=f"Semana {inicio_fmt} → {fim_fmt}",
        color=COR_RECOLHIMENTO,
        timestamp=discord.utils.utcnow(),
    )

    total = {k: 0 for k in FARM_KEYS}
    linhas = []
    for i, e in enumerate(entregas, 1):
        partes = []
        for key in FARM_KEYS:
            val = _row_get(e, key) or 0
            total[key] += val
            if val:
                partes.append(f"{_KEY_LABELS[key]} {val}")
        nome = _row_get(e, "alvo_nome") or _row_get(e, "alvo_user_id") or "Não informado"
        linhas.append(
            f"`{i:02d}` {_fmt_data_dm(e['data'])} • **{nome}** → {', '.join(partes) or '—'} "
            f"• por <@{e['registrado_por']}>"
        )
    _adicionar_entregas(embed, linhas)

    total_str = " | ".join(f"{_KEY_LABELS[k]}: **{v}**" for k, v in total.items())
    embed.add_field(name="📦 Total recolhido", value=total_str, inline=False)
    embed.add_field(name="Status", value=_status_ciclo(ciclo), inline=False)
    embed.set_footer(text=_rodape(ciclo))
    return embed


def _view_para_ciclo(ciclo) -> discord.ui.View | None:
    """View do ciclo derivada do estado: sem botões se pago; sem Registrar se encerrado."""
    if ciclo["pago"]:
        return None
    view = RecolhimentoDinheiroView() if ciclo["tipo"] == "dinheiro" else RecolhimentoFarmView()
    if ciclo["encerrado"]:
        view.registrar.disabled = True
    return view


def _motivo_ciclo_fechado(ciclo) -> str | None:
    """Mensagem de recusa se o ciclo não aceita mais registros."""
    if ciclo is None:
        return "❌ Ciclo não encontrado."
    if ciclo["pago"]:
        return "⚠️ Este ciclo já foi pago e não aceita novos registros."
    if ciclo["encerrado"]:
        return "⚠️ Este ciclo já foi encerrado e não aceita novos registros."
    return None


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
        try:
            valor = _parse_valor_recolhimento(self.valor_input.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ Valor inválido. Exemplos: `1500`, `1.500`, `1.500,50` ou `R$ 1.500,00`.",
                ephemeral=True,
            )
            return

        motivo = _motivo_ciclo_fechado(db_recolhimento_get_ciclo(self.ciclo_id))
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
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
        try:
            folha   = max(0, int(self.folha_input.value   or 0))
            opio    = max(0, int(self.opio_input.value    or 0))
            seringa = max(0, int(self.seringa_input.value or 0))
            agulha  = max(0, int(self.agulha_input.value  or 0))
            ferro   = max(0, int(self.ferro_input.value   or 0))
        except ValueError:
            await interaction.response.send_message(
                "❌ Valores inválidos. Use números inteiros.", ephemeral=True
            )
            return

        if folha + opio + seringa + agulha + ferro == 0:
            await interaction.response.send_message(
                "❌ Informe pelo menos um valor acima de zero.", ephemeral=True
            )
            return

        motivo = _motivo_ciclo_fechado(db_recolhimento_get_ciclo(self.ciclo_id))
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return

        db_recolhimento_add_entrega_farm(
            self.ciclo_id,
            str(interaction.user.id),
            folha,
            opio,
            seringa,
            agulha,
            self.alvo_user_id,
            self.alvo_nome,
            self.alvo_pasta_id,
            ferro=ferro,
        )
        await interaction.response.send_message(
            f"✅ Recolhimento registrado para **{self.alvo_nome}**! "
            f"Borracha: {folha} | Aluminio: {opio} | Cobre: {seringa} | Plastico: {agulha} | Ferro: {ferro}",
            ephemeral=True,
        )
        cog = interaction.client.get_cog("RecolhimentoCog")
        if cog:
            await cog._atualizar_embed_ciclo(interaction.guild, self.ciclo_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em RecolhimentoFarmModal: %s", error, exc_info=True)
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
                total  = sum(e["valor"] or 0 for e in entregas)
                resumo = f"Total recolhido: {_fmt_valor(total)}"
                emoji  = "🔴"
                label  = "Dinheiro Sujo"
            else:
                totais = {k: sum(_row_get(e, k) or 0 for e in entregas) for k in FARM_KEYS}
                resumo = " | ".join(f"{_KEY_LABELS[k]}: {v}" for k, v in totais.items())
                emoji  = "🟢"
                label  = "Farm"

            notif = discord.Embed(
                title=f"{emoji} Recolhimento Pago — {label}",
                description=f"Ciclo {inicio_fmt} → {fim_fmt}\n\n{resumo}",
                color=COR_RECOLHIMENTO,
                timestamp=discord.utils.utcnow(),
            )
            notif.add_field(name="Pago por",   value=interaction.user.mention, inline=True)
            notif.add_field(name="Observação", value=observacao[:1024],        inline=True)
            if ciclo["message_id"]:
                link = f"https://discord.com/channels/{ciclo['guild_id']}/{ciclo['channel_id']}/{ciclo['message_id']}"
                notif.add_field(name="Ciclo", value=f"[Abrir recolhimento]({link})", inline=False)
            notif.set_footer(text=_rodape(ciclo))
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
        # Apenas cache (intents.members ativo): evita uma chamada à API por
        # membro, o que estourava os 3s da interação.
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

    entradas.sort(key=lambda e: e["nome"].lower())
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
        ciclo = _ciclo_da_mensagem(interaction, "farm", incluir_encerrado=True)
        if not ciclo:
            await interaction.response.send_message("❌ Ciclo não encontrado.", ephemeral=True)
            return
        if ciclo["pago"]:
            await interaction.response.send_message("⚠️ Este ciclo já foi pago.", ephemeral=True)
            return
        await interaction.response.send_modal(PagamentoModal(ciclo["id"]))


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
        tipo     = ciclo["tipo"]

        if tipo == "dinheiro":
            embed = build_embed_dinheiro(ciclo, entregas)
        else:
            embed = build_embed_farm(ciclo, entregas)
        # A view sempre segue o estado do ciclo (nunca reativa botões de
        # um ciclo pago ou encerrado).
        view = None if remover_view else _view_para_ciclo(ciclo)

        try:
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            log.warning("Falha ao editar mensagem do ciclo %s: %s", ciclo_id, e)

    async def _iniciar_ciclo(self, interaction: discord.Interaction, tipo: str):
        """Cria e posta um novo ciclo no canal (no máximo um aberto por tipo/semana/canal)."""
        guild_id    = str(interaction.guild_id)
        channel_id  = str(interaction.channel_id)
        week_inicio = current_week_id()
        week_fim    = _semana_fim_from_inicio(week_inicio)
        tipo_label  = "Dinheiro Sujo" if tipo == "dinheiro" else "Farm"

        # Responde já editando a mensagem de escolha: remove os botões (evita
        # duplo clique criando ciclos repetidos) e garante resposta em < 3s.
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
            # Ciclo órfão (sem mensagem): reaproveita em vez de duplicar.
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
        embed = build_embed_dinheiro(ciclo, entregas) if tipo == "dinheiro" else build_embed_farm(ciclo, entregas)

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
        """Encerra ciclos cuja semana terminou (domingo a partir das 23:59).

        Roda a cada 5 minutos e também logo após o bot ligar, então semanas em
        que o bot estava fora do ar no horário do fechamento são recuperadas.
        """
        agora = now_tz()
        hoje = agora.date()
        if hoje.weekday() == 6 and (agora.hour, agora.minute) >= (23, 59):
            ciclos = db_recolhimento_ciclos_para_encerrar(hoje.isoformat(), incluir_ate=True)
        else:
            ciclos = db_recolhimento_ciclos_para_encerrar(hoje.isoformat(), incluir_ate=False)
        if not ciclos:
            return

        log.info("Task de fechamento: %s ciclo(s) para encerrar em %s", len(ciclos), hoje)
        for ciclo in ciclos:
            try:
                await self._encerrar_ciclo(ciclo)
            except Exception:
                log.error("Falha ao encerrar ciclo %s", ciclo["id"], exc_info=True)

    async def _encerrar_ciclo(self, ciclo):
        db_recolhimento_encerrar(ciclo["id"])
        log.info("Ciclo encerrado: id=%s guild=%s", ciclo["id"], ciclo["guild_id"])

        guild = self.bot.get_guild(int(ciclo["guild_id"]))
        if not guild:
            return

        # Mantém o botão "Marcar como Pago" ativo até o pagamento.
        await self._atualizar_embed_ciclo(guild, ciclo["id"])

        if ciclo["pago"]:
            return
        entregas = db_recolhimento_get_entregas(ciclo["id"])
        if not entregas:
            return
        try:
            canal = guild.get_channel(int(ciclo["channel_id"])) or \
                    await guild.fetch_channel(int(ciclo["channel_id"]))
            tipo_label = "Dinheiro Sujo" if ciclo["tipo"] == "dinheiro" else "Farm"
            alerta = discord.Embed(
                title="⚠️ Recolhimento encerrado — pagamento pendente",
                description=(
                    f"O ciclo de **{tipo_label}** "
                    f"({_fmt_data_curta(ciclo['semana_inicio'])} → {_fmt_data_curta(ciclo['semana_fim'])}) "
                    "ainda **não foi marcado como pago**.\n\n"
                    "O botão **✅ Marcar como Pago** continua disponível na mensagem do ciclo."
                ),
                color=COR_RECOLHIMENTO,
                timestamp=discord.utils.utcnow(),
            )
            alerta.set_footer(text=_rodape(ciclo))
            await canal.send(embed=alerta)
        except Exception as e:
            log.warning("Falha ao enviar alerta de pendência (ciclo %s): %s", ciclo["id"], e)

    @_fechamento_ciclos.before_loop
    async def _before_fechamento(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RecolhimentoCog(bot))
    log.info("RecolhimentoCog adicionado ao bot.")
