"""
cogs/acao.py - Sistema de Ações para o bot Morro do Mineiro.
"""

import re
from decimal import Decimal, InvalidOperation

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from core.permissions import is_lideranca
from services.db_service import (
    db_acao_criar,
    db_acao_finalizar,
    db_acao_get,
    db_acao_get_by_message,
    db_acao_participante_add,
    db_acao_participante_remove,
    db_acao_participantes,
    db_get_lideranca_role_ids,
    db_get_system_config,
)

log = get_logger("acao", "acao.log")

ACOES: dict[str, dict] = {
    "loja_tatuagens": {"emoji": "🖊️", "nome": "Loja de Tatuagens", "max_bandidos": 2, "max_policiais": 2, "armamento": "Apenas armas brancas (pode ser negociada remoção para combate em punhos)", "negociacao": "Obrigatória", "refens": "Proibido", "obs": []},
    "barbearia": {"emoji": "✂️", "nome": "Barbearia", "max_bandidos": None, "max_policiais": None, "armamento": "Apenas armas brancas (pode ser negociada remoção para combate em punhos)", "negociacao": "Obrigatória", "refens": "Proibido", "obs": ["Bandidos: 4 a 10 (máximo)", "Policiais: igual ao número de bandidos (obrigatório)"]},
    "loja_armas_praca": {"emoji": "🔫", "nome": "Loja de Armas — Praça", "max_bandidos": 2, "max_policiais": 3, "armamento": "Apenas pistolas, exceto AP Pistol (pistola automática)", "negociacao": "Obrigatória", "refens": "Proibido", "obs": ["Nenhum bandido fora (todos obrigatoriamente dentro)"]},
    "loja_armas_porto": {"emoji": "🔫", "nome": "Loja de Armas — Porto", "max_bandidos": 5, "max_policiais": 7, "armamento": "Apenas pistolas, exceto AP Pistol (pistola automática)", "negociacao": "Obrigatória", "refens": "Proibido", "obs": ["Bandidos: 3 a 5 (máximo)", "Policiais: 5 a 7 (máximo), proporcional ao número de bandidos"]},
    "conveniencia": {"emoji": "🏪", "nome": "Loja de Conveniência", "max_bandidos": 6, "max_policiais": 8, "armamento": "Pistola obrigatória, exceto AP Pistol (pistola automática)", "negociacao": "Inexistente — ação iniciada ao perímetro ser fechado", "refens": "Proibido", "obs": ["Bandidos: 5 a 6 (máximo)", "Policiais: 7 a 8 (máximo), proporcional ao número de bandidos", "Trata-se de uma ação de troca de tiros — fuga não é permitida", "Até 2 (dois) bandidos podem estar fora da loja, dentro do perímetro"]},
    "joalheria": {"emoji": "💎", "nome": "Joalheria", "max_bandidos": 7, "max_policiais": 11, "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta", "negociacao": "Obrigatória", "refens": "Opcional, máximo 3", "obs": ["Bandidos: 5 a 7 — máximo 3 fora e 4 dentro", "Policiais: 9 a 11, proporcional ao número de bandidos", "Máximo de 3 veículos em caso de fuga", "Em caso de fuga, todo o contingente policial pode ser liberado"]},
    "concessionaria": {"emoji": "🚗", "nome": "Concessionária", "max_bandidos": 10, "max_policiais": 12, "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta", "negociacao": "Obrigatória", "refens": "Opcional, máximo 4", "obs": ["Bandidos: 8 a 10 — todos dentro", "Policiais: 12 (obrigatório)", "Máximo de 6 veículos em caso de fuga (3 próprios + 3 da concessionária)", "Em caso de fuga, todo o contingente policial pode ser liberado", "Limite de 5 granadas de gás para a polícia"]},
    "fleeca": {"emoji": "💵", "nome": "Fleeca", "max_bandidos": 8, "max_policiais": 10, "armamento": "A depender de cada local", "negociacao": "Obrigatória", "refens": "Obrigatório, máximo 3", "obs": ["Bandidos: 6 a 8 (máximo)", "Policiais: 10 (obrigatório)", "Máximo de 3 veículos em caso de fuga", "Em caso de fuga, todo o contingente policial pode ser liberado"]},
    "shopping": {"emoji": "🛍️", "nome": "Shopping", "max_bandidos": None, "max_policiais": None, "armamento": "Armamento mínimo: Submetralhadora (AP Pistol não é considerada), com obrigação de ter 4 Rifles", "negociacao": "—", "refens": "—", "obs": ["Com atirador: máximo de 4 bandidos em prédios", "Sem atirador: limite de 3 bandidos em prédios"]},
    "praia": {"emoji": "🏖️", "nome": "Praia", "max_bandidos": None, "max_policiais": None, "armamento": "Restrito exclusivamente a Submetralhadora (AP Pistol não é considerada)", "negociacao": "—", "refens": "—", "obs": ["O interior da lojinha (cofre) é estritamente proibido"]},
    "biblioteca": {"emoji": "📚", "nome": "Biblioteca", "max_bandidos": 10, "max_policiais": 12, "armamento": "Submetralhadora (AP Pistol não é considerada)", "negociacao": "Obrigatória", "refens": "Opcional, apenas 1", "obs": ["Bandidos: 8 a 10 — todos dentro", "Policiais: 10 a 12, proporcional ao número de bandidos"]},
    "merryweather": {"emoji": "⚔️", "nome": "Merryweather", "max_bandidos": 12, "max_policiais": 15, "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta", "negociacao": "Não há — ação de confronto direto", "refens": "Proibido", "obs": ["Bandidos: 8 a 12 (máximo)", "Policiais: 11 a 15, proporcional ao número de bandidos", "Os bandidos aguardam o início da ação, que ocorre apenas quando a polícia entrar no perímetro"]},
    "acougue": {"emoji": "🥩", "nome": "Açougue", "max_bandidos": 10, "max_policiais": 12, "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta", "negociacao": "Obrigatória", "refens": "Opcional, máximo 3", "obs": ["Bandidos: 8 a 10 — todos dentro", "Policiais: 12 (obrigatório)", "Máximo de 3 veículos em caso de fuga", "Em caso de fuga, todo o contingente policial pode ser liberado", "Limite de 3 granadas de gás para a polícia", "A rotação por fora, entre P1 e P2 e vice-versa, é permitida"]},
    "galinheiro": {"emoji": "🐔", "nome": "Galinheiro", "max_bandidos": 10, "max_policiais": 12, "armamento": "Submetralhadora (AP Pistol não é considerada) e fuzil", "negociacao": "Obrigatória", "refens": "Opcional, máximo 2", "obs": ["Bandidos: 8 a 10 — posicionamento dentro e fora do local permitido", "Policiais: 12 (obrigatório)", "Limite de 3 granadas de gás para a polícia", "NÃO é permitido posicionamento na área de mata e morros atrás dos trilhos (fora do perímetro)"]},
    "banco_central": {"emoji": "🏦", "nome": "Banco Central", "max_bandidos": 10, "max_policiais": 13, "armamento": "Fuzil", "negociacao": "Obrigatória", "refens": "Opcional, máximo 4", "obs": ["Bandidos: 10 (obrigatório) — máximo 3 em prédios ou 5 no chão", "Policiais: 13 (obrigatório)", "Máximo de 3 veículos em caso de fuga", "Em caso de fuga, todo o contingente policial pode ser liberado", "Reféns podem ser usados para neutralizar atiradores ou impedir reposicionamento com helicóptero (não ambos simultaneamente)", "Proibido ter bandidos fora em caso de fuga"]},
    "banco_paleto": {"emoji": "🏦", "nome": "Banco Paleto", "max_bandidos": 10, "max_policiais": 12, "armamento": "Fuzil", "negociacao": "Não há — ação de confronto direto", "refens": "Proibido", "obs": ["Bandidos: 10 (máximo)", "Policiais: 12 (obrigatório)", "Os bandidos aguardam o início da ação, que ocorre apenas quando a polícia entrar no perímetro"]},
}


def _build_regras_embed(
    acao_key: str,
    membros_inscritos: list[discord.Member] | None = None,
    horario: str | None = None,
    tipo: str | None = None,
    data: str | None = None,
) -> discord.Embed:
    acao  = ACOES[acao_key]
    max_b = acao["max_bandidos"]
    max_p = acao["max_policiais"]

    if tipo == "fuga":
        color        = discord.Color.from_rgb(255, 140, 0)
        tipo_display = "🏃 Fuga"
    elif tipo == "tiro":
        color        = discord.Color.red()
        tipo_display = "🔫 No Tiro"
    else:
        color        = discord.Color.dark_red()
        tipo_display = None

    partes = []
    if data:         partes.append(f"📅 **Data:** `{data}`")
    if horario:      partes.append(f"🕐 **Hora:** `{horario}`")
    if tipo_display: partes.append(f"⚔️ **Tipo:** `{tipo_display}`")
    desc = (
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n{'　　'.join(partes)}\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"
        if partes else None
    )

    embed = discord.Embed(title=f"{acao['emoji']} {acao['nome']}", description=desc, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="🔴 Bandidos",  value=f"Máximo {max_b}" if max_b else "Ver observações", inline=True)
    embed.add_field(name="🔵 Policiais", value=f"Máximo {max_p}" if max_p else "Ver observações", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🔫 Armamento",  value=acao["armamento"],  inline=False)
    embed.add_field(name="🤝 Negociação", value=acao["negociacao"], inline=True)
    embed.add_field(name="👤 Reféns",     value=acao["refens"],     inline=True)
    if acao["obs"]:
        embed.add_field(name="📋 Observações", value="\n".join(f"• {o}" for o in acao["obs"]), inline=False)
    if membros_inscritos:
        embed.add_field(name=f"✅ Participantes ({len(membros_inscritos)})", value="\n".join(f"• {m.mention}" for m in membros_inscritos), inline=False)
    else:
        embed.add_field(name="✅ Participantes", value="Nenhum inscrito ainda", inline=False)
    embed.set_footer(text="Use os botões abaixo para se inscrever ou remover")
    return embed


class AcaoSelectView(discord.ui.View):
    def __init__(self, horario: str | None = None, tipo: str | None = None, data: str | None = None):
        super().__init__(timeout=120)
        self.horario = horario
        self.tipo    = tipo
        self.data    = data

    @discord.ui.select(
        placeholder="Escolha a ação...", min_values=1, max_values=1,
        options=[discord.SelectOption(label=d["nome"], value=k, emoji=d["emoji"]) for k, d in ACOES.items()],
    )
    async def selecionar_acao(self, interaction: discord.Interaction, select: discord.ui.Select):
        acao_key = select.values[0]
        embed    = _build_regras_embed(acao_key, horario=self.horario, tipo=self.tipo, data=self.data)
        view     = AcaoParticipantesView(acao_key=acao_key, horario=self.horario, tipo=self.tipo, data=self.data)
        await interaction.response.send_message(embed=embed, view=view)
        log.info(f"{interaction.user} abriu painel de ação: {ACOES[acao_key]['nome']}")


class AcaoParticipantesView(discord.ui.View):
    def __init__(self, acao_key: str, horario: str | None = None, tipo: str | None = None, data: str | None = None):
        super().__init__(timeout=None)
        self.acao_key = acao_key
        self.horario  = horario
        self.tipo     = tipo
        self.data     = data
        self.inscritos: list[discord.Member] = []

    def _max_bandidos(self) -> int | None:
        return ACOES[self.acao_key]["max_bandidos"]

    def _esta_inscrito(self, member: discord.Member) -> bool:
        return any(m.id == member.id for m in self.inscritos)

    def _atualizar_embed(self) -> discord.Embed:
        return _build_regras_embed(self.acao_key, self.inscritos, self.horario, self.tipo, self.data)

    @discord.ui.button(label="✅ Entrar na ação", style=discord.ButtonStyle.success, custom_id="acao:entrar")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        max_b  = self._max_bandidos()
        if self._esta_inscrito(member):
            await interaction.response.send_message("⚠️ Você já está inscrito nesta ação.", ephemeral=True)
            return
        if max_b and len(self.inscritos) >= max_b:
            await interaction.response.send_message(f"❌ Vagas esgotadas (máximo: {max_b} participantes).", ephemeral=True)
            return
        self.inscritos.append(member)
        log.info(f"{member} entrou na ação '{ACOES[self.acao_key]['nome']}'")
        await interaction.response.edit_message(embed=self._atualizar_embed(), view=self)
        await interaction.followup.send(f"✅ {member.mention} inscrito na ação **{ACOES[self.acao_key]['nome']}**!", ephemeral=True)

    @discord.ui.button(label="🚪 Sair da ação", style=discord.ButtonStyle.danger, custom_id="acao:sair")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not self._esta_inscrito(member):
            await interaction.response.send_message("⚠️ Você não está inscrito nesta ação.", ephemeral=True)
            return
        self.inscritos = [m for m in self.inscritos if m.id != member.id]
        log.info(f"{member} saiu da ação '{ACOES[self.acao_key]['nome']}'")
        await interaction.response.edit_message(embed=self._atualizar_embed(), view=self)
        await interaction.followup.send(f"🚪 {member.mention} removido da ação.", ephemeral=True)

    @discord.ui.button(label="➕ Adicionar membro", style=discord.ButtonStyle.secondary, custom_id="acao:adicionar")
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        lideranca_ids = db_get_lideranca_role_ids(str(interaction.guild_id))
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode adicionar membros.", ephemeral=True)
            return
        membros = sorted(
            [m for m in interaction.guild.members if not m.bot and not self._esta_inscrito(m)],
            key=lambda m: m.display_name.lower(),
        )
        if not membros:
            await interaction.response.send_message("⚠️ Nenhum membro disponível para adicionar.", ephemeral=True)
            return
        total = max(1, (len(membros) + AdicionarMembroPaginadoView.POR_PAGINA - 1) // AdicionarMembroPaginadoView.POR_PAGINA)
        await interaction.response.send_message(
            f"Selecione o membro para adicionar à ação (página 1/{total}):",
            view=AdicionarMembroPaginadoView(painel_view=self, painel_msg=interaction.message, membros=membros),
            ephemeral=True,
        )

    @discord.ui.button(label="➖ Remover membro", style=discord.ButtonStyle.secondary, custom_id="acao:remover")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        lideranca_ids = db_get_lideranca_role_ids(str(interaction.guild_id))
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode remover membros.", ephemeral=True)
            return
        if not self.inscritos:
            await interaction.response.send_message("⚠️ Nenhum membro inscrito para remover.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Selecione o membro que deseja remover da ação:",
            view=RemoverMembroView(painel_view=self, painel_msg=interaction.message),
            ephemeral=True,
        )

    @discord.ui.button(label="🔒 Encerrar ação", style=discord.ButtonStyle.danger, custom_id="acao:encerrar", row=1)
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        lideranca_ids = db_get_lideranca_role_ids(str(interaction.guild_id))
        if not is_lideranca(interaction.user, lideranca_ids):
            await interaction.response.send_message("❌ Apenas liderança pode encerrar a ação.", ephemeral=True)
            return
        acao_nome = ACOES[self.acao_key]["nome"]
        nomes     = ", ".join(m.display_name for m in self.inscritos) if self.inscritos else "Nenhum"
        embed_final = discord.Embed(
            title=f"🔒 Ação Encerrada — {acao_nome}",
            description=f"Encerrada por {interaction.user.mention}",
            color=discord.Color.greyple(), timestamp=discord.utils.utcnow(),
        )
        embed_final.add_field(name=f"✅ Participantes finais ({len(self.inscritos)})", value=nomes, inline=False)
        self.stop()
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=embed_final, view=self)
        log.info(f"{interaction.user} encerrou a ação '{acao_nome}' com {len(self.inscritos)} participante(s)")


class AdicionarMembroPaginadoView(discord.ui.View):
    POR_PAGINA = 20

    def __init__(self, painel_view: "AcaoParticipantesView", painel_msg: discord.Message, membros: list[discord.Member], pagina: int = 0):
        super().__init__(timeout=60)
        self.painel_view = painel_view
        self.painel_msg  = painel_msg
        self.membros     = membros
        self.pagina      = pagina
        self._rebuild()

    def _total_paginas(self) -> int:
        return max(1, (len(self.membros) + self.POR_PAGINA - 1) // self.POR_PAGINA)

    def _rebuild(self):
        self.clear_items()
        inicio = self.pagina * self.POR_PAGINA
        fatia  = self.membros[inicio : inicio + self.POR_PAGINA]
        opcoes = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in fatia
        ]
        sel = discord.ui.Select(
            placeholder=f"Membros (pág. {self.pagina + 1}/{self._total_paginas()})...",
            min_values=1, max_values=1, options=opcoes,
        )
        sel.callback = self._on_select
        self.add_item(sel)

        if self._total_paginas() > 1:
            prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary,
                                     disabled=self.pagina == 0)
            prev.callback = self._prev
            self.add_item(prev)
            nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary,
                                    disabled=self.pagina >= self._total_paginas() - 1)
            nxt.callback = self._next
            self.add_item(nxt)

    async def _on_select(self, interaction: discord.Interaction):
        member_id = int(interaction.data["values"][0])
        member    = interaction.guild.get_member(member_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except Exception:
                await interaction.response.edit_message(content="❌ Membro não encontrado no servidor.", view=None)
                return
        pv = self.painel_view
        if pv._esta_inscrito(member):
            await interaction.response.edit_message(content=f"⚠️ {member.display_name} já está inscrito.", view=None)
            return
        max_b = pv._max_bandidos()
        if max_b and len(pv.inscritos) >= max_b:
            await interaction.response.edit_message(content=f"❌ Vagas esgotadas (máximo: {max_b}).", view=None)
            return
        pv.inscritos.append(member)
        log.info("Liderança %s adicionou %s à ação '%s'", interaction.user, member, ACOES[pv.acao_key]["nome"])
        await interaction.response.edit_message(content=f"✅ {member.mention} adicionado à ação!", view=None)
        try:
            await self.painel_msg.edit(embed=pv._atualizar_embed(), view=pv)
        except Exception as e:
            log.warning("Não foi possível atualizar painel após adicionar: %s", e)

    async def _prev(self, interaction: discord.Interaction):
        self.pagina -= 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _next(self, interaction: discord.Interaction):
        self.pagina += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)


class RemoverMembroView(discord.ui.View):
    def __init__(self, painel_view: "AcaoParticipantesView", painel_msg: discord.Message):
        super().__init__(timeout=60)
        self.painel_view = painel_view
        self.painel_msg  = painel_msg
        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in painel_view.inscritos
        ]
        select = discord.ui.Select(
            placeholder="Selecione o membro para remover...",
            min_values=1, max_values=1,
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        member_id = int(interaction.data["values"][0])
        member    = next((m for m in self.painel_view.inscritos if m.id == member_id), None)
        if not member:
            await interaction.response.edit_message(content="❌ Membro não encontrado na lista.", view=None)
            return
        self.painel_view.inscritos = [m for m in self.painel_view.inscritos if m.id != member_id]
        log.info(f"Liderança {interaction.user} removeu {member} da ação '{ACOES[self.painel_view.acao_key]['nome']}'")
        await interaction.response.edit_message(content=f"🚪 {member.mention} removido da ação.", view=None)
        try:
            await self.painel_msg.edit(embed=self.painel_view._atualizar_embed(), view=self.painel_view)
        except Exception as e:
            log.warning(f"Não foi possível atualizar painel após remover: {e}")


class IniciarAcaoModal(discord.ui.Modal, title="⚡ Configurar Ação"):
    data = discord.ui.TextInput(
        label="Data da ação",
        placeholder=f"Ex: {DATE_BR_EXAMPLE}",
        max_length=10,
        required=True,
    )
    horario = discord.ui.TextInput(
        label="Horário da ação",
        placeholder="Ex: 21:00",
        max_length=10,
        required=True,
    )
    tipo_acao = discord.ui.TextInput(
        label="Tipo da ação",
        placeholder="Digite: fuga  ou  tiro",
        max_length=10,
        required=True,
    )

    def __init__(self, canal_id: str | None = None):
        super().__init__()
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data_val = normalize_date_br(self.data.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        horario_val = self.horario.value.strip()
        tipo_val    = self.tipo_acao.value.strip().lower()
        if tipo_val not in ("fuga", "tiro"):
            await interaction.response.send_message(
                "❌ Tipo inválido. Digite **fuga** ou **tiro**.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        tipo_display = "🏃 Fuga" if tipo_val == "fuga" else "🔫 No Tiro"
        embed = discord.Embed(
            title="⚡ Selecione a Ação",
            description="Escolha a ação que deseja realizar no menu abaixo.",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="📅 Data",    value=data_val,    inline=True)
        embed.add_field(name="🕐 Horário", value=horario_val, inline=True)
        embed.add_field(name="⚔️ Tipo",    value=tipo_display, inline=True)
        embed.set_footer(text="Morro do Mineiro • Sistema de Ações")

        canal = None
        if self.canal_id:
            canal = interaction.guild.get_channel(int(self.canal_id))
            if canal is None:
                try:
                    canal = await interaction.guild.fetch_channel(int(self.canal_id))
                except Exception:
                    canal = None

        if canal:
            await canal.send(embed=embed, view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val))
            await interaction.followup.send(
                f"✅ Seletor de ação aberto em {canal.mention}!", ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=embed, view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val)
            )
        log.info(f"{interaction.user} iniciou ação via /acao — data: {data_val}, horário: {horario_val}, tipo: {tipo_val}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em IniciarAcaoModal.on_submit: %s", error, exc_info=True)
        try:
            await interaction.followup.send("❌ Erro ao iniciar ação. Tente novamente.", ephemeral=True)
        except Exception:
            pass


class AcaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="acao", description="Abre o painel para iniciar uma ação.")
    async def acao(self, interaction: discord.Interaction):
        row      = db_get_system_config(str(interaction.guild_id), "acao")
        canal_id = row["canal_interacao_id"] if row else None
        await interaction.response.send_modal(IniciarAcaoModal(canal_id=canal_id))
        log.info(f"{interaction.user} abriu o painel de ações")


# ── Implementação persistente do painel de ação ──────────────────────────────

def normalizar_horario(value: str) -> str:
    raw = value.strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("Use o formato HH:MM.")
    hora, minuto = (int(part) for part in raw.split(":"))
    if hora > 23 or minuto > 59:
        raise ValueError("Informe um horário válido entre 00:00 e 23:59.")
    return f"{hora:02d}:{minuto:02d}"


def parse_money_centavos(value: str) -> int:
    raw = value.strip().lower().replace("r$", "").replace(" ", "")
    if not raw:
        raise ValueError("Informe o valor total da ação.")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Informe um valor em dinheiro válido.") from exc
    if amount <= 0:
        raise ValueError("O valor total precisa ser maior que zero.")
    return int((amount * 100).to_integral_value())


def calcular_pagamento(valor_total_centavos: int, participantes_count: int) -> dict[str, int]:
    if participantes_count <= 0:
        raise ValueError("Vitória precisa ter pelo menos um participante.")
    valor_participantes = valor_total_centavos // 2
    valor_por_participante = valor_participantes // participantes_count
    valor_participantes_distribuido = valor_por_participante * participantes_count
    valor_faccao = valor_total_centavos - valor_participantes_distribuido
    return {
        "valor_total_centavos": valor_total_centavos,
        "valor_faccao_centavos": valor_faccao,
        "valor_participantes_centavos": valor_participantes_distribuido,
        "valor_por_participante_centavos": valor_por_participante,
    }


def normalize_resultado(value: str) -> str:
    raw = value.strip().lower().replace("í", "i").replace("ó", "o")
    if raw in {"vitoria", "ganha", "ganhou"}:
        return "ganha"
    if raw in {"derrota", "perdida", "perdeu"}:
        return "perdida"
    raise ValueError("Resultado inválido. Use vitória/ganha ou derrota/perdida.")


def _fmt_money_centavos(value: int | None) -> str:
    value = int(value or 0)
    reais, centavos = divmod(value, 100)
    inteiro = f"{reais:,}".replace(",", ".")
    return f"R$ {inteiro},{centavos:02d}"


def _tipo_display(tipo: str | None) -> str:
    if tipo == "fuga":
        return "🏃 Fuga"
    if tipo == "tiro":
        return "🔫 No Tiro"
    return "Não informado"


def _status_display(status: str | None) -> str:
    return {
        "aberta": "🟢 Aberta",
        "ganha": "🏆 Ganha",
        "perdida": "❌ Perdida",
    }.get(status or "aberta", status or "Aberta")


def _participante_value(participantes) -> str:
    if not participantes:
        return "Nenhum inscrito ainda"
    linhas = [f"• <@{p['user_id']}>" for p in participantes[:35]]
    if len(participantes) > 35:
        linhas.append(f"• ... +{len(participantes) - 35} participante(s)")
    return "\n".join(linhas)


def _build_regras_embed(
    acao_key: str,
    participantes=None,
    horario: str | None = None,
    tipo: str | None = None,
    data: str | None = None,
    criador_id: str | None = None,
    status: str = "aberta",
    finalizado_por: str | None = None,
    observacao: str | None = None,
) -> discord.Embed:
    participantes = participantes or []
    acao = ACOES[acao_key]
    max_b = acao["max_bandidos"]
    max_p = acao["max_policiais"]
    color = discord.Color.green() if status == "ganha" else discord.Color.red() if status == "perdida" else discord.Color.from_rgb(255, 140, 0)
    vagas = "Ver observações" if max_b is None else f"{len(participantes)}/{max_b}"
    embed = discord.Embed(
        title=f"{acao['emoji']} {acao['nome']}",
        description=f"**Status:** {_status_display(status)}",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="📅 Data", value=data or "-", inline=True)
    embed.add_field(name="🕐 Horário", value=horario or "-", inline=True)
    embed.add_field(name="⚔️ Tipo", value=_tipo_display(tipo), inline=True)
    embed.add_field(name="👤 Criador", value=f"<@{criador_id}>" if criador_id else "-", inline=True)
    embed.add_field(name="🔴 Bandidos", value=f"Máximo {max_b}" if max_b else "Ver observações", inline=True)
    embed.add_field(name="🔵 Policiais", value=f"Máximo {max_p}" if max_p else "Ver observações", inline=True)
    embed.add_field(name="🎟️ Vagas", value=vagas, inline=True)
    embed.add_field(name="🔫 Armamento", value=acao["armamento"], inline=False)
    embed.add_field(name="🤝 Negociação", value=acao["negociacao"], inline=True)
    embed.add_field(name="👤 Reféns", value=acao["refens"], inline=True)
    if acao["obs"]:
        embed.add_field(name="📋 Observações", value="\n".join(f"• {o}" for o in acao["obs"]), inline=False)
    embed.add_field(name=f"✅ Participantes ({len(participantes)})", value=_participante_value(participantes), inline=False)
    if finalizado_por:
        embed.add_field(name="🔒 Finalizada por", value=f"<@{finalizado_por}>", inline=True)
    if observacao:
        embed.add_field(name="📝 Observação", value=observacao[:1000], inline=False)
    embed.set_footer(text="Use os botões abaixo para participar ou finalizar")
    return embed


def _build_select_embed(data: str, horario: str, tipo: str) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Selecione a Ação",
        description="Escolha a missão no menu abaixo para abrir o painel de participantes.",
        color=discord.Color.gold(),
    )
    embed.add_field(name="📅 Data", value=data, inline=True)
    embed.add_field(name="🕐 Horário", value=horario, inline=True)
    embed.add_field(name="⚔️ Tipo", value=_tipo_display(tipo), inline=True)
    embed.set_footer(text="Morro do Mineiro — Sistema de Ação")
    return embed


async def _fetch_config_channel(guild: discord.Guild, sistema: str):
    row = db_get_system_config(str(guild.id), sistema)
    channel_id = None
    if row:
        channel_id = row["canal_interacao_id"]
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except Exception:
            return None
    return channel


async def _send_action_channel_log(guild: discord.Guild, sistema: str, embed: discord.Embed) -> bool:
    channel = await _fetch_config_channel(guild, sistema)
    if not channel:
        return False
    await channel.send(embed=embed)
    return True


async def _delete_action_panel_message(interaction: discord.Interaction, acao_row) -> bool:
    try:
        if interaction.message:
            await interaction.message.delete()
            return True
    except Exception:
        pass

    try:
        channel = interaction.guild.get_channel(int(acao_row["channel_id"]))
        if channel is None:
            channel = await interaction.guild.fetch_channel(int(acao_row["channel_id"]))
        message = await channel.fetch_message(int(acao_row["message_id"]))
        await message.delete()
        return True
    except Exception:
        log.warning("Nao foi possivel apagar painel da acao %s", acao_row["id"], exc_info=True)
        return False


def _is_lideranca(member: discord.Member, guild_id: str) -> bool:
    return is_lideranca(member, db_get_lideranca_role_ids(guild_id))


class AcaoTipoView(discord.ui.View):
    def __init__(self, canal_id: str | None = None):
        super().__init__(timeout=60)
        self.canal_id = canal_id

    async def _abrir_modal(self, interaction: discord.Interaction, tipo: str):
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode iniciar ação.", ephemeral=True)
            return
        await interaction.response.send_modal(IniciarAcaoModal(tipo=tipo, canal_id=self.canal_id))

    @discord.ui.button(label="Fuga", emoji="🏃", style=discord.ButtonStyle.primary)
    async def fuga(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._abrir_modal(interaction, "fuga")

    @discord.ui.button(label="No Tiro", emoji="🔫", style=discord.ButtonStyle.danger)
    async def tiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._abrir_modal(interaction, "tiro")


class AcaoSelectView(discord.ui.View):
    def __init__(self, horario: str, tipo: str, data: str, criador_id: str):
        super().__init__(timeout=120)
        self.horario = horario
        self.tipo = tipo
        self.data = data
        self.criador_id = criador_id

    @discord.ui.select(
        placeholder="Escolha a ação...",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label=d["nome"], value=k, emoji=d["emoji"]) for k, d in ACOES.items()],
    )
    async def selecionar_acao(self, interaction: discord.Interaction, select: discord.ui.Select):
        acao_key = select.values[0]
        embed = _build_regras_embed(acao_key, horario=self.horario, tipo=self.tipo, data=self.data, criador_id=self.criador_id)
        await interaction.response.send_message(embed=embed, view=AcaoParticipantesView())
        msg = await interaction.original_response()
        acao_id = db_acao_criar(str(interaction.guild_id), acao_key, self.tipo, self.data, self.horario, self.criador_id, str(msg.channel.id), str(msg.id))
        try:
            await interaction.message.delete()
        except Exception:
            pass
        log.info("%s criou painel persistente de ação %s", interaction.user, ACOES[acao_key]["nome"])


class AcaoParticipantesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _load(self, interaction: discord.Interaction):
        if not interaction.message:
            return None
        return db_acao_get_by_message(str(interaction.guild_id), str(interaction.message.id))

    async def _refresh_message(self, interaction: discord.Interaction, acao_row):
        participantes = db_acao_participantes(int(acao_row["id"]))
        embed = _build_regras_embed(
            acao_row["acao_key"],
            participantes,
            acao_row["horario"],
            acao_row["tipo"],
            acao_row["data"],
            acao_row["criado_por"],
            acao_row["status"],
            acao_row["finalizado_por"],
            acao_row["observacao"],
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✅ Entrar na ação", style=discord.ButtonStyle.success, custom_id="acao:entrar")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao_row = self._load(interaction)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        participantes = db_acao_participantes(int(acao_row["id"]))
        max_b = ACOES[acao_row["acao_key"]]["max_bandidos"]
        if max_b and len(participantes) >= max_b:
            await interaction.response.send_message(f"❌ Vagas esgotadas (máximo: {max_b}).", ephemeral=True)
            return
        added = db_acao_participante_add(int(acao_row["id"]), str(interaction.user.id), interaction.user.display_name, "self", str(interaction.user.id))
        if not added:
            await interaction.response.send_message("⚠️ Você já está inscrito nesta ação.", ephemeral=True)
            return
        acao_row = db_acao_get(int(acao_row["id"]))
        await self._refresh_message(interaction, acao_row)
        await interaction.followup.send(f"✅ {interaction.user.mention} inscrito na ação!", ephemeral=True)

    @discord.ui.button(label="🚪 Sair da ação", style=discord.ButtonStyle.danger, custom_id="acao:sair")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao_row = self._load(interaction)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        removed = db_acao_participante_remove(int(acao_row["id"]), str(interaction.user.id))
        if not removed:
            await interaction.response.send_message("⚠️ Você não está inscrito nesta ação.", ephemeral=True)
            return
        acao_row = db_acao_get(int(acao_row["id"]))
        await self._refresh_message(interaction, acao_row)
        await interaction.followup.send(f"🚪 {interaction.user.mention} removido da ação.", ephemeral=True)

    @discord.ui.button(label="➕ Adicionar membro", style=discord.ButtonStyle.secondary, custom_id="acao:adicionar")
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao_row = self._load(interaction)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode adicionar membros.", ephemeral=True)
            return
        inscritos = {p["user_id"] for p in db_acao_participantes(int(acao_row["id"]))}
        membros = sorted([m for m in interaction.guild.members if not m.bot and str(m.id) not in inscritos], key=lambda m: m.display_name.lower())
        if not membros:
            await interaction.response.send_message("⚠️ Nenhum membro disponível para adicionar.", ephemeral=True)
            return
        total = max(1, (len(membros) + AdicionarMembroPaginadoView.POR_PAGINA - 1) // AdicionarMembroPaginadoView.POR_PAGINA)
        await interaction.response.send_message(
            f"Selecione o membro para adicionar à ação (página 1/{total}):",
            view=AdicionarMembroPaginadoView(int(acao_row["id"]), interaction.message, membros),
            ephemeral=True,
        )

    @discord.ui.button(label="➖ Remover membro", style=discord.ButtonStyle.secondary, custom_id="acao:remover")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao_row = self._load(interaction)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode remover membros.", ephemeral=True)
            return
        participantes = db_acao_participantes(int(acao_row["id"]))
        if not participantes:
            await interaction.response.send_message("⚠️ Nenhum membro inscrito para remover.", ephemeral=True)
            return
        await interaction.response.send_message("Selecione o membro que deseja remover da ação:", view=RemoverMembroView(int(acao_row["id"]), interaction.message, participantes), ephemeral=True)

    @discord.ui.button(label="🔒 Finalizar ação", style=discord.ButtonStyle.danger, custom_id="acao:encerrar", row=1)
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao_row = self._load(interaction)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode finalizar a ação.", ephemeral=True)
            return
        await interaction.response.send_modal(FinalizarAcaoModal(int(acao_row["id"])))


class AdicionarMembroPaginadoView(discord.ui.View):
    POR_PAGINA = 20

    def __init__(self, acao_id: int, painel_msg: discord.Message, membros: list[discord.Member], pagina: int = 0):
        super().__init__(timeout=60)
        self.acao_id = acao_id
        self.painel_msg = painel_msg
        self.membros = membros
        self.pagina = pagina
        self._rebuild()

    def _total_paginas(self) -> int:
        return max(1, (len(self.membros) + self.POR_PAGINA - 1) // self.POR_PAGINA)

    def _rebuild(self):
        self.clear_items()
        fatia = self.membros[self.pagina * self.POR_PAGINA : self.pagina * self.POR_PAGINA + self.POR_PAGINA]
        sel = discord.ui.Select(
            placeholder=f"Membros (pág. {self.pagina + 1}/{self._total_paginas()})...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=m.display_name[:100], value=str(m.id)) for m in fatia],
        )
        sel.callback = self._on_select
        self.add_item(sel)
        if self._total_paginas() > 1:
            prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.pagina == 0)
            prev.callback = self._prev
            self.add_item(prev)
            nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.pagina >= self._total_paginas() - 1)
            nxt.callback = self._next
            self.add_item(nxt)

    async def _on_select(self, interaction: discord.Interaction):
        acao_row = db_acao_get(self.acao_id)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.edit_message(content="❌ Ação não encontrada ou já finalizada.", view=None)
            return
        member_id = int(interaction.data["values"][0])
        member = interaction.guild.get_member(member_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except Exception:
                await interaction.response.edit_message(content="❌ Membro não encontrado no servidor.", view=None)
                return
        participantes = db_acao_participantes(self.acao_id)
        max_b = ACOES[acao_row["acao_key"]]["max_bandidos"]
        if max_b and len(participantes) >= max_b:
            await interaction.response.edit_message(content=f"❌ Vagas esgotadas (máximo: {max_b}).", view=None)
            return
        added = db_acao_participante_add(self.acao_id, str(member.id), member.display_name, "lideranca_add", str(interaction.user.id))
        if not added:
            await interaction.response.edit_message(content=f"⚠️ {member.display_name} já está inscrito.", view=None)
            return
        acao_row = db_acao_get(self.acao_id)
        embed = _build_regras_embed(acao_row["acao_key"], db_acao_participantes(self.acao_id), acao_row["horario"], acao_row["tipo"], acao_row["data"], acao_row["criado_por"])
        await self.painel_msg.edit(embed=embed, view=AcaoParticipantesView())
        await interaction.response.edit_message(content=f"✅ {member.mention} adicionado à ação!", view=None)

    async def _prev(self, interaction: discord.Interaction):
        self.pagina -= 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _next(self, interaction: discord.Interaction):
        self.pagina += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)


class RemoverMembroView(discord.ui.View):
    def __init__(self, acao_id: int, painel_msg: discord.Message, participantes):
        super().__init__(timeout=60)
        self.acao_id = acao_id
        self.painel_msg = painel_msg
        select = discord.ui.Select(
            placeholder="Selecione o membro para remover...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=(p["user_name"] or p["user_id"])[:100], value=str(p["user_id"])) for p in participantes[:25]],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        acao_row = db_acao_get(self.acao_id)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.edit_message(content="❌ Ação não encontrada ou já finalizada.", view=None)
            return
        member_id = str(interaction.data["values"][0])
        removed = db_acao_participante_remove(self.acao_id, member_id)
        if not removed:
            await interaction.response.edit_message(content="❌ Membro não encontrado na lista.", view=None)
            return
        acao_row = db_acao_get(self.acao_id)
        embed = _build_regras_embed(acao_row["acao_key"], db_acao_participantes(self.acao_id), acao_row["horario"], acao_row["tipo"], acao_row["data"], acao_row["criado_por"])
        await self.painel_msg.edit(embed=embed, view=AcaoParticipantesView())
        await interaction.response.edit_message(content=f"🚪 <@{member_id}> removido da ação.", view=None)


def _build_resultado_embed(acao_row, participantes) -> discord.Embed:
    acao_nome = ACOES[acao_row["acao_key"]]["nome"]
    embed = discord.Embed(title=f"{_status_display(acao_row['status'])} — {acao_nome}", color=discord.Color.green() if acao_row["status"] == "ganha" else discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Data/Hora", value=f"{acao_row['data']} {acao_row['horario']}", inline=True)
    embed.add_field(name="Tipo", value=_tipo_display(acao_row["tipo"]), inline=True)
    embed.add_field(name="Finalizada por", value=f"<@{acao_row['finalizado_por']}>", inline=True)
    embed.add_field(name=f"Participantes ({len(participantes)})", value=_participante_value(participantes), inline=False)
    if acao_row["observacao"]:
        embed.add_field(name="Observação", value=acao_row["observacao"][:1000], inline=False)
    return embed


def _build_pagamento_embed(acao_row, participantes) -> discord.Embed:
    acao_nome = ACOES[acao_row["acao_key"]]["nome"]
    embed = discord.Embed(title=f"💰 Pagamento de Ação — {acao_nome}", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Data/Hora", value=f"{acao_row['data']} {acao_row['horario']}", inline=True)
    embed.add_field(name="Participantes", value=str(len(participantes)), inline=True)
    embed.add_field(name="Valor total", value=_fmt_money_centavos(acao_row["valor_total_centavos"]), inline=True)
    embed.add_field(name="Facção", value=_fmt_money_centavos(acao_row["valor_faccao_centavos"]), inline=True)
    embed.add_field(name="Total participantes", value=_fmt_money_centavos(acao_row["valor_participantes_centavos"]), inline=True)
    embed.add_field(name="Por participante", value=_fmt_money_centavos(acao_row["valor_por_participante_centavos"]), inline=True)
    embed.add_field(name="Quem recebe", value=_participante_value(participantes), inline=False)
    embed.set_footer(text="Regra: 50% participantes e 50% facção; sobras de centavos ficam com a facção.")
    return embed


class FinalizarAcaoModal(discord.ui.Modal, title="🔒 Finalizar Ação"):
    resultado = discord.ui.TextInput(label="Resultado", placeholder="vitória/ganha ou derrota/perdida", max_length=20, required=True)
    valor_total = discord.ui.TextInput(label="Valor total (obrigatório se vitória)", placeholder="Ex: R$ 50.000,00", max_length=30, required=False)
    observacao = discord.ui.TextInput(label="Observação", style=discord.TextStyle.paragraph, max_length=1000, required=False)

    def __init__(self, acao_id: int):
        super().__init__()
        self.acao_id = acao_id

    async def on_submit(self, interaction: discord.Interaction):
        acao_row = db_acao_get(self.acao_id)
        if not acao_row or acao_row["status"] != "aberta":
            await interaction.response.send_message("❌ Ação não encontrada ou já finalizada.", ephemeral=True)
            return
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode finalizar a ação.", ephemeral=True)
            return
        try:
            resultado = normalize_resultado(self.resultado.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        participantes = db_acao_participantes(self.acao_id)
        pagamento = {"valor_total_centavos": None, "valor_faccao_centavos": None, "valor_participantes_centavos": None, "valor_por_participante_centavos": None}
        if resultado == "ganha":
            if not participantes:
                await interaction.response.send_message("❌ Vitória precisa ter pelo menos um participante para calcular pagamento.", ephemeral=True)
                return
            try:
                pagamento = calcular_pagamento(parse_money_centavos(self.valor_total.value), len(participantes))
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        obs = self.observacao.value.strip() or None
        await interaction.response.defer(ephemeral=True)
        db_acao_finalizar(
            self.acao_id,
            resultado,
            str(interaction.user.id),
            obs,
            pagamento["valor_total_centavos"],
            pagamento["valor_faccao_centavos"],
            pagamento["valor_participantes_centavos"],
            pagamento["valor_por_participante_centavos"],
        )
        final = db_acao_get(self.acao_id)
        destino = "acao_ganhas" if resultado == "ganha" else "acao_perdidas"
        sent_result = await _send_action_channel_log(interaction.guild, destino, _build_resultado_embed(final, participantes))
        sent_payment = True
        if resultado == "ganha":
            sent_payment = await _send_action_channel_log(interaction.guild, "acao_pagamento", _build_pagamento_embed(final, participantes))
        deleted_panel = await _delete_action_panel_message(interaction, final)
        avisos = []
        if not sent_result:
            avisos.append("canal de resultado não configurado/encontrado")
        if not sent_payment:
            avisos.append("canal de pagamento não configurado/encontrado")
        if not deleted_panel:
            avisos.append("painel da ação não foi apagado")
        extra = f" ⚠️ {'; '.join(avisos)}." if avisos else ""
        await interaction.followup.send(f"✅ Ação finalizada como {_status_display(resultado)}.{extra}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em FinalizarAcaoModal: %s", error, exc_info=True)
        try:
            await interaction.response.send_message("❌ Erro ao finalizar ação.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send("❌ Erro ao finalizar ação.", ephemeral=True)


class IniciarAcaoModal(discord.ui.Modal, title="⚡ Configurar Ação"):
    data = discord.ui.TextInput(label="Data da ação", placeholder=f"Ex: {DATE_BR_EXAMPLE}", max_length=10, required=True)
    horario = discord.ui.TextInput(label="Horário da ação", placeholder="Ex: 21:00", max_length=5, required=True)

    def __init__(self, tipo: str, canal_id: str | None = None):
        super().__init__()
        self.tipo = tipo
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data_val = normalize_date_br(self.data.value)
            horario_val = normalizar_horario(self.horario.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        canal = interaction.channel
        if self.canal_id:
            canal = interaction.guild.get_channel(int(self.canal_id))
            if canal is None:
                try:
                    canal = await interaction.guild.fetch_channel(int(self.canal_id))
                except Exception:
                    canal = interaction.channel
        await canal.send(embed=_build_select_embed(data_val, horario_val, self.tipo), view=AcaoSelectView(horario_val, self.tipo, data_val, str(interaction.user.id)))
        await interaction.followup.send(f"✅ Seletor de ação aberto em {canal.mention}!", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro em IniciarAcaoModal.on_submit: %s", error, exc_info=True)
        try:
            await interaction.followup.send("❌ Erro ao iniciar ação. Tente novamente.", ephemeral=True)
        except Exception:
            pass


class AcaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AcaoParticipantesView())

    @app_commands.command(name="acao", description="Abre o painel para iniciar uma ação.")
    async def acao(self, interaction: discord.Interaction):
        if not _is_lideranca(interaction.user, str(interaction.guild_id)):
            await interaction.response.send_message("❌ Apenas liderança pode iniciar ação.", ephemeral=True)
            return
        row = db_get_system_config(str(interaction.guild_id), "acao")
        canal_id = row["canal_interacao_id"] if row else None
        await interaction.response.send_message("Escolha o tipo da ação:", view=AcaoTipoView(canal_id=canal_id), ephemeral=True)
        log.info("%s abriu o seletor de tipo de ação", interaction.user)


async def setup(bot: commands.Bot):
    await bot.add_cog(AcaoCog(bot))
    log.info("AcaoCog carregado com sucesso.")
