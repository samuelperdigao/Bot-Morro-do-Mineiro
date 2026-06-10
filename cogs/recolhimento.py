"""
cogs/recolhimento.py - Sistema de Recolhimento Semanal.

/recolhimento → liderança inicia ciclo de dinheiro sujo ou farm no canal.
Embeds fixos atualizados a cada entrega via message.edit().
Task de fechamento todo domingo 23:59 encerra ciclos abertos.
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.date_utils import format_date_br
from core.logger import get_logger
from core.permissions import is_lideranca
from services.db_service import (
    DINHEIRO_ITEMS,
    TZ,
    current_week_id,
    now_tz,
    db_channel_map_get,
    db_get_lideranca_role_ids,
    db_get_meta,
    db_meta_tipo_efetivo,
    db_meta_itens,
    db_prog_itens,
    db_lista_progresso,
    db_recolhimento_ciclo_aberto_por_mensagem,
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

_KEY_LABELS = {
    "folha": "Borracha",
    "opio": "Aluminio",
    "seringa": "Cobre",
    "agulha": "Plastico",
}


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


def _ciclo_da_mensagem(interaction: discord.Interaction, tipo: str):
    if not interaction.message:
        return None
    return db_recolhimento_ciclo_aberto_por_mensagem(
        str(interaction.guild_id),
        str(interaction.channel_id),
        tipo,
        str(interaction.message.id),
    )


def _semana_fim_from_inicio(semana_inicio: str) -> str:
    """Segunda-feira → domingo (+ 6 dias)."""
    inicio = datetime.date.fromisoformat(semana_inicio)
    return (inicio + datetime.timedelta(days=6)).isoformat()


def _verificar_meta_atingida(ciclo, meta, entregas: list) -> bool:
    """Retorna True se o total do ciclo atingiu a meta da semana."""
    if not meta:
        return False
    tipo = ciclo["tipo"]
    tipo_meta = db_meta_tipo_efetivo(meta)
    if tipo == "dinheiro" and tipo_meta in {"dinheiro", "misto"}:
        meta_val = meta["meta_dinheiro"] or 0
        if meta_val <= 0:
            return False
        total = sum(e["valor"] or 0 for e in entregas)
        return total >= meta_val
    if tipo == "farm" and tipo_meta in {"itens", "misto"}:
        meta_itens = db_meta_itens(meta)
        if not meta_itens:
            return False
        nome_to_key = {
            "Borracha": "folha",
            "Aluminio": "opio",
            "Cobre": "seringa",
            "Plastico": "agulha",
        }
        totais = {k: sum(e[k] or 0 for e in entregas) for k in ("folha", "opio", "seringa", "agulha")}
        return all(
            totais.get(nome_to_key.get(nome, ""), 0) >= qtd
            for nome, qtd in meta_itens.items()
            if qtd > 0
        )
    return False


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
    if entregas:
        linhas = []
        for i, e in enumerate(entregas, 1):
            data_fmt  = _fmt_data_curta(e["data"])
            valor_fmt = _fmt_valor(e["valor"] or 0)
            total    += e["valor"] or 0
            linhas.append(
                f"Recolhimento {i:02d} | {data_fmt} | {valor_fmt} | "
                f"{_fmt_alvo_entrega(e)} | Recolhido por <@{e['registrado_por']}>"
            )
        embed.add_field(name="Entregas", value="\n".join(linhas), inline=False)

    embed.add_field(name="TOTAL", value=_fmt_valor(total), inline=True)

    if ciclo["pago"]:
        data_pag = _fmt_data_curta(ciclo["data_pagamento"])
        embed.add_field(
            name="STATUS",
            value=(
                f"🟡 Pago\n"
                f"Data: {data_pag}\n"
                f"Pago por: <@{ciclo['pago_por']}>\n"
                f"Observação: {ciclo['observacao_pagamento'] or '—'}"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="STATUS", value="⏳ Pendente", inline=True)

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

    total = {"folha": 0, "opio": 0, "seringa": 0, "agulha": 0}
    if entregas:
        linhas = []
        for i, e in enumerate(entregas, 1):
            data_fmt = _fmt_data_curta(e["data"])
            partes = []
            for key in ("folha", "opio", "seringa", "agulha"):
                val = e[key] or 0
                total[key] += val
                partes.append(f"{_KEY_LABELS[key]}: {val}")
            linhas.append(
                f"Recolhimento {i:02d} | {data_fmt} | "
                + " | ".join(partes)
                + f" | {_fmt_alvo_entrega(e)} | Recolhido por <@{e['registrado_por']}>"
            )
        embed.add_field(name="Entregas", value="\n".join(linhas), inline=False)

    total_str = " | ".join(f"{_KEY_LABELS[k]}: {v}" for k, v in total.items())
    embed.add_field(name="TOTAL", value=total_str, inline=False)

    if ciclo["pago"]:
        data_pag = _fmt_data_curta(ciclo["data_pagamento"])
        embed.add_field(
            name="STATUS",
            value=(
                f"🟡 Pago\n"
                f"Data: {data_pag}\n"
                f"Pago por: <@{ciclo['pago_por']}>\n"
                f"Observação: {ciclo['observacao_pagamento'] or '—'}"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="STATUS", value="⏳ Pendente", inline=True)

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
        raw = self.valor_input.value.strip()
        raw = raw.replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            valor = float(raw)
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
        except ValueError:
            await interaction.response.send_message(
                "❌ Valores inválidos. Use números inteiros.", ephemeral=True
            )
            return

        if folha + opio + seringa + agulha == 0:
            await interaction.response.send_message(
                "❌ Informe pelo menos um valor acima de zero.", ephemeral=True
            )
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
        )
        await interaction.response.send_message(
            f"✅ Recolhimento registrado para **{self.alvo_nome}**! "
            f"Borracha: {folha} | Aluminio: {opio} | Cobre: {seringa} | Plastico: {agulha}",
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
        db_recolhimento_marcar_pago(self.ciclo_id, str(interaction.user.id), observacao)
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
                totais = {k: sum(e[k] or 0 for e in entregas) for k in ("folha", "opio", "seringa", "agulha")}
                resumo = " | ".join(f"{_KEY_LABELS[k]}: {v}" for k, v in totais.items())
                emoji  = "🟢"
                label  = "Farm"

            notif = discord.Embed(
                title=f"{emoji} Recolhimento Pago — {label}",
                description=f"Ciclo {inicio_fmt} → {fim_fmt}\n\n{resumo}",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )
            notif.add_field(name="Pago por",   value=interaction.user.mention, inline=True)
            notif.add_field(name="Observação", value=observacao,               inline=True)
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
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception:
                member = None

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
        ciclo = _ciclo_da_mensagem(interaction, "dinheiro")
        if not ciclo:
            await interaction.response.send_message(
                "❌ Ciclo não encontrado ou já encerrado.", ephemeral=True
            )
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
        ciclo = _ciclo_da_mensagem(interaction, "farm")
        if not ciclo:
            await interaction.response.send_message(
                "❌ Ciclo não encontrado ou já encerrado.", ephemeral=True
            )
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
            view  = None if remover_view else RecolhimentoDinheiroView()
        else:
            embed = build_embed_farm(ciclo, entregas)
            view  = None if remover_view else RecolhimentoFarmView()

        try:
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            log.warning("Falha ao editar mensagem do ciclo %s: %s", ciclo_id, e)

    async def _iniciar_ciclo(self, interaction: discord.Interaction, tipo: str):
        """Cria e posta um novo ciclo no canal."""
        guild_id    = str(interaction.guild_id)
        channel_id  = str(interaction.channel_id)
        week_inicio = current_week_id()
        week_fim    = _semana_fim_from_inicio(week_inicio)

        ciclo_id = db_recolhimento_criar_ciclo(
            guild_id=guild_id,
            member_id=str(interaction.user.id),
            channel_id=channel_id,
            tipo=tipo,
            semana_inicio=week_inicio,
            semana_fim=week_fim,
        )

        ciclo    = db_recolhimento_get_ciclo(ciclo_id)
        entregas = []

        if tipo == "dinheiro":
            embed = build_embed_dinheiro(ciclo, entregas)
            view  = RecolhimentoDinheiroView()
        else:
            embed = build_embed_farm(ciclo, entregas)
            view  = RecolhimentoFarmView()

        canal = interaction.channel
        if canal is None:
            canal = interaction.guild.get_channel(int(channel_id)) or \
                    await interaction.guild.fetch_channel(int(channel_id))
        msg = await canal.send(embed=embed, view=view)
        db_recolhimento_salvar_message_id(ciclo_id, str(msg.id))

        tipo_label = "Dinheiro Sujo" if tipo == "dinheiro" else "Farm"
        await interaction.response.send_message(
            f"✅ Ciclo de **{tipo_label}** criado!\n"
            f"Semana: `{format_date_br(week_inicio)}` → `{format_date_br(week_fim)}`",
            ephemeral=True,
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

    @tasks.loop(time=datetime.time(hour=23, minute=59, tzinfo=TZ))
    async def _fechamento_ciclos(self):
        dt = now_tz()
        if dt.weekday() != 6 or dt.hour != 23 or dt.minute != 59:
            return

        hoje   = now_tz().date().isoformat()
        ciclos = db_recolhimento_ciclos_para_encerrar(hoje)
        if not ciclos:
            return

        log.info("Task de fechamento: %s ciclo(s) para encerrar em %s", len(ciclos), hoje)
        for ciclo in ciclos:
            guild = self.bot.get_guild(int(ciclo["guild_id"]))
            if not guild:
                db_recolhimento_encerrar(ciclo["id"])
                continue

            entregas     = db_recolhimento_get_entregas(ciclo["id"])
            meta         = db_get_meta(ciclo["guild_id"], ciclo["semana_inicio"])
            meta_atingida = _verificar_meta_atingida(ciclo, meta, entregas)

            if meta_atingida and not ciclo["pago"]:
                try:
                    canal = guild.get_channel(int(ciclo["channel_id"])) or \
                            await guild.fetch_channel(int(ciclo["channel_id"]))
                    tipo_label = "Dinheiro Sujo" if ciclo["tipo"] == "dinheiro" else "Farm"
                    alerta = discord.Embed(
                        title="⚠️ Meta Atingida — Pagamento Pendente",
                        description=(
                            f"O ciclo de **{tipo_label}** desta semana atingiu a meta,\n"
                            f"mas ainda **não foi marcado como pago**.\n\n"
                            f"Use o botão **✅ Marcar como Pago** antes do fechamento."
                        ),
                        color=discord.Color.orange(),
                        timestamp=discord.utils.utcnow(),
                    )
                    await canal.send(embed=alerta)
                except Exception as e:
                    log.warning("Falha ao enviar alerta de meta (ciclo %s): %s", ciclo["id"], e)

            db_recolhimento_encerrar(ciclo["id"])
            await self._atualizar_embed_ciclo(guild, ciclo["id"], remover_view=True)
            log.info("Ciclo encerrado: id=%s guild=%s", ciclo["id"], ciclo["guild_id"])

    @_fechamento_ciclos.before_loop
    async def _before_fechamento(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RecolhimentoCog(bot))
    log.info("RecolhimentoCog adicionado ao bot.")
