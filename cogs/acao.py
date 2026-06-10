"""
cogs/acao.py - Sistema de Ações para o bot Morro do Mineiro.
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from core.permissions import is_lideranca
from services.db_service import db_get_lideranca_role_ids, db_get_system_config

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


async def setup(bot: commands.Bot):
    await bot.add_cog(AcaoCog(bot))
    log.info("AcaoCog carregado com sucesso.")
