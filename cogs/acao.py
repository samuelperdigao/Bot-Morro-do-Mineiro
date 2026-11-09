"""
cogs/acao.py - Sistema de Ações para o bot Morro do Mineiro.
"""

import re

import discord
from discord import app_commands
from discord.ext import commands

from core.date_utils import DATE_BR_EXAMPLE, normalize_date_br
from core.logger import get_logger
from core.permissions import is_lideranca
from services import acao_service
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


HORARIO_RE = re.compile(r"^([01]?[0-9]|2[0-3])[:hH]([0-5][0-9])$")
MENCOES_POR_FIELD = 35  # "• <@id>" tem até ~25 caracteres: 35 cabem em 1024
MAX_FIELDS_PARTICIPANTES = 3


def normalizar_horario(raw: str) -> str:
    """Aceita 21:00, 21h00, 9:30 e devolve HH:MM."""
    m = HORARIO_RE.match((raw or "").strip())
    if not m:
        raise ValueError("Horário inválido. Use o formato **HH:MM** (ex.: 21:00).")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _build_regras_embed(
    acao_key: str,
    inscritos: list[str] | None = None,
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
    inscritos = inscritos or []
    if inscritos:
        vagas = f"/{max_b}" if max_b else ""
        # Até 3 blocos (~105 nomes) para manter o embed abaixo de 6000 caracteres.
        visiveis = inscritos[:MENCOES_POR_FIELD * MAX_FIELDS_PARTICIPANTES]
        for inicio in range(0, len(visiveis), MENCOES_POR_FIELD):
            bloco = visiveis[inicio:inicio + MENCOES_POR_FIELD]
            nome = f"✅ Participantes ({len(inscritos)}{vagas})" if inicio == 0 else "✅ Participantes (cont.)"
            valor = "\n".join(f"• <@{uid}>" for uid in bloco)
            if inicio + MENCOES_POR_FIELD >= len(visiveis) and len(inscritos) > len(visiveis):
                valor += f"\n… e mais {len(inscritos) - len(visiveis)}"
            embed.add_field(name=nome, value=valor[:1024], inline=False)
    else:
        embed.add_field(name="✅ Participantes", value="Nenhum inscrito ainda", inline=False)
    embed.set_footer(text="Morro do Mineiro — Sistema de Ações • use os botões para se inscrever")
    return embed


def _embed_da_acao(acao) -> discord.Embed:
    return _build_regras_embed(
        acao["acao_key"], acao_service.inscritos(acao["id"]), acao["horario"], acao["tipo"], acao["data"]
    )


def _embed_encerrada(acao, encerrado_por: str) -> discord.Embed:
    nome = ACOES[acao["acao_key"]]["nome"]
    ids = acao_service.inscritos(acao["id"])
    embed = discord.Embed(
        title=f"🔒 Ação Encerrada — {nome}",
        description=f"Encerrada por <@{encerrado_por}>",
        color=discord.Color.greyple(),
        timestamp=discord.utils.utcnow(),
    )
    valor = ", ".join(f"<@{uid}>" for uid in ids) if ids else "Nenhum"
    if len(valor) > 1024:
        valor = valor[:1000].rsplit(",", 1)[0] + f", … (+{len(ids)} no total)"
    embed.add_field(name=f"✅ Participantes finais ({len(ids)})", value=valor, inline=False)
    embed.set_footer(text="Morro do Mineiro — Sistema de Ações")
    return embed


def _view_encerrada() -> "AcaoParticipantesView":
    view = AcaoParticipantesView()
    for item in view.children:
        item.disabled = True
    return view


async def _atualizar_painel(client: discord.Client, acao) -> None:
    """Reedita a mensagem do painel com os inscritos atuais."""
    if not acao["message_id"]:
        return
    try:
        canal = client.get_channel(int(acao["channel_id"])) or await client.fetch_channel(int(acao["channel_id"]))
        await canal.get_partial_message(int(acao["message_id"])).edit(embed=_embed_da_acao(acao))
    except Exception as e:
        log.warning("Não foi possível atualizar o painel da ação %s: %s", acao["id"], e)


class AcaoSelectView(discord.ui.View):
    def __init__(
        self,
        horario: str | None = None,
        tipo: str | None = None,
        data: str | None = None,
        iniciador_id: int | None = None,
    ):
        super().__init__(timeout=600)
        self.horario = horario
        self.tipo    = tipo
        self.data    = data
        self.iniciador_id = iniciador_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.iniciador_id is None or interaction.user.id == self.iniciador_id:
            return True
        if is_lideranca(interaction.user, db_get_lideranca_role_ids(str(interaction.guild_id))):
            return True
        await interaction.response.send_message(
            "❌ Apenas quem iniciou a ação ou a liderança pode escolher a ação.", ephemeral=True
        )
        return False

    @discord.ui.select(
        placeholder="Escolha a ação...", min_values=1, max_values=1,
        options=[discord.SelectOption(label=d["nome"], value=k, emoji=d["emoji"]) for k, d in ACOES.items()],
    )
    async def selecionar_acao(self, interaction: discord.Interaction, select: discord.ui.Select):
        acao_key = select.values[0]
        acao_id = acao_service.criar_acao(
            str(interaction.guild_id), str(interaction.channel_id), acao_key,
            str(interaction.user.id), self.data, self.horario, self.tipo,
        )
        embed = _build_regras_embed(acao_key, [], horario=self.horario, tipo=self.tipo, data=self.data)
        view = AcaoParticipantesView()
        try:
            if interaction.message is not None and not interaction.message.flags.ephemeral:
                # Transforma o seletor no painel: some o menu (sem escolha dupla).
                await interaction.response.edit_message(embed=embed, view=view)
                message = interaction.message
            else:
                await interaction.response.send_message(embed=embed, view=view)
                message = await interaction.original_response()
        except Exception:
            acao_service.excluir_acao(acao_id)
            raise
        acao_service.salvar_mensagem(acao_id, str(message.channel.id), str(message.id))
        self.stop()
        log.info(f"{interaction.user} abriu painel de ação: {ACOES[acao_key]['nome']} (id={acao_id})")


class AcaoParticipantesView(discord.ui.View):
    """View única e sem estado: a ação é localizada pela mensagem clicada."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _acao(self, interaction: discord.Interaction):
        acao = acao_service.get_por_mensagem(str(interaction.message.id)) if interaction.message else None
        if acao is None:
            await interaction.response.send_message(
                "⚠️ Esta ação foi criada antes da atualização do bot e não pode mais ser alterada. "
                "Inicie uma nova ação.",
                ephemeral=True,
            )
            return None
        if acao["status"] != acao_service.ABERTA:
            await interaction.response.send_message("🔒 Esta ação já foi encerrada.", ephemeral=True)
            return None
        return acao

    @staticmethod
    def _eh_lideranca(interaction: discord.Interaction) -> bool:
        return is_lideranca(interaction.user, db_get_lideranca_role_ids(str(interaction.guild_id)))

    @discord.ui.button(label="✅ Entrar na ação", style=discord.ButtonStyle.success, custom_id="acao:entrar")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao = await self._acao(interaction)
        if acao is None:
            return
        nome = ACOES[acao["acao_key"]]["nome"]
        max_b = ACOES[acao["acao_key"]]["max_bandidos"]
        resultado = acao_service.inscrever(acao["id"], str(interaction.user.id), str(interaction.user.id), max_b)
        if resultado == "ja_inscrito":
            await interaction.response.send_message("⚠️ Você já está inscrito nesta ação.", ephemeral=True)
            return
        if resultado == "lotada":
            await interaction.response.send_message(f"❌ Vagas esgotadas (máximo: {max_b} participantes).", ephemeral=True)
            return
        if resultado == "encerrada":
            await interaction.response.send_message("🔒 Esta ação já foi encerrada.", ephemeral=True)
            return
        log.info(f"{interaction.user} entrou na ação '{nome}' (id={acao['id']})")
        await interaction.response.edit_message(embed=_embed_da_acao(acao), view=self)
        await interaction.followup.send(f"✅ {interaction.user.mention} inscrito na ação **{nome}**!", ephemeral=True)

    @discord.ui.button(label="🚪 Sair da ação", style=discord.ButtonStyle.danger, custom_id="acao:sair")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        acao = await self._acao(interaction)
        if acao is None:
            return
        if acao_service.remover(acao["id"], str(interaction.user.id)) != "ok":
            await interaction.response.send_message("⚠️ Você não está inscrito nesta ação.", ephemeral=True)
            return
        log.info(f"{interaction.user} saiu da ação '{ACOES[acao['acao_key']]['nome']}' (id={acao['id']})")
        await interaction.response.edit_message(embed=_embed_da_acao(acao), view=self)
        await interaction.followup.send(f"🚪 {interaction.user.mention} removido da ação.", ephemeral=True)

    @discord.ui.button(label="➕ Adicionar membro", style=discord.ButtonStyle.secondary, custom_id="acao:adicionar")
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._eh_lideranca(interaction):
            await interaction.response.send_message("❌ Apenas liderança pode adicionar membros.", ephemeral=True)
            return
        acao = await self._acao(interaction)
        if acao is None:
            return
        await interaction.response.send_message(
            "Selecione o membro para adicionar à ação:",
            view=GerenciarMembroView(acao["id"], adicionar=True),
            ephemeral=True,
        )

    @discord.ui.button(label="➖ Remover membro", style=discord.ButtonStyle.secondary, custom_id="acao:remover")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._eh_lideranca(interaction):
            await interaction.response.send_message("❌ Apenas liderança pode remover membros.", ephemeral=True)
            return
        acao = await self._acao(interaction)
        if acao is None:
            return
        if not acao_service.inscritos(acao["id"]):
            await interaction.response.send_message("⚠️ Nenhum membro inscrito para remover.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Selecione o membro que deseja remover da ação:",
            view=GerenciarMembroView(acao["id"], adicionar=False),
            ephemeral=True,
        )

    @discord.ui.button(label="🔒 Encerrar ação", style=discord.ButtonStyle.danger, custom_id="acao:encerrar", row=1)
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._eh_lideranca(interaction):
            await interaction.response.send_message("❌ Apenas liderança pode encerrar a ação.", ephemeral=True)
            return
        acao = await self._acao(interaction)
        if acao is None:
            return
        if not acao_service.encerrar(acao["id"], str(interaction.user.id)):
            await interaction.response.send_message("🔒 Esta ação já foi encerrada.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_embed_encerrada(acao, str(interaction.user.id)), view=_view_encerrada()
        )
        log.info(
            f"{interaction.user} encerrou a ação '{ACOES[acao['acao_key']]['nome']}' "
            f"(id={acao['id']}) com {len(acao_service.inscritos(acao['id']))} participante(s)"
        )


class GerenciarMembroView(discord.ui.View):
    """Adicionar/remover inscrito via seletor de usuário (sem limite de 25)."""

    def __init__(self, acao_id: int, adicionar: bool):
        super().__init__(timeout=120)
        self.acao_id = acao_id
        self.adicionar = adicionar
        select = discord.ui.UserSelect(
            placeholder="Selecione o membro..." if adicionar else "Selecione quem remover...",
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        membro = interaction.data.get("values", [None])[0]
        acao = acao_service.get_acao(self.acao_id)
        if acao is None or acao["status"] != acao_service.ABERTA:
            await interaction.response.edit_message(content="🔒 Esta ação já foi encerrada.", view=None)
            return
        user = interaction.guild.get_member(int(membro)) if membro else None
        if user is None or user.bot:
            await interaction.response.edit_message(content="❌ Membro inválido.", view=None)
            return
        nome = ACOES[acao["acao_key"]]["nome"]
        if self.adicionar:
            max_b = ACOES[acao["acao_key"]]["max_bandidos"]
            resultado = acao_service.inscrever(acao["id"], str(user.id), str(interaction.user.id), max_b)
            mensagens = {
                "ok": f"✅ {user.mention} adicionado à ação!",
                "ja_inscrito": f"⚠️ {user.display_name} já está inscrito.",
                "lotada": f"❌ Vagas esgotadas (máximo: {max_b}).",
                "encerrada": "🔒 Esta ação já foi encerrada.",
            }
        else:
            resultado = acao_service.remover(acao["id"], str(user.id))
            mensagens = {
                "ok": f"🚪 {user.mention} removido da ação.",
                "nao_inscrito": f"⚠️ {user.display_name} não está inscrito.",
                "encerrada": "🔒 Esta ação já foi encerrada.",
            }
        await interaction.response.edit_message(content=mensagens[resultado], view=None)
        if resultado == "ok":
            log.info(
                "Liderança %s %s %s na ação '%s' (id=%s)",
                interaction.user, "adicionou" if self.adicionar else "removeu", user, nome, acao["id"],
            )
            await _atualizar_painel(interaction.client, acao)


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
        try:
            horario_val = normalizar_horario(self.horario.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
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
            await canal.send(embed=embed, view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val, iniciador_id=interaction.user.id))
            await interaction.followup.send(
                f"✅ Seletor de ação aberto em {canal.mention}!", ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=embed, view=AcaoSelectView(horario=horario_val, tipo=tipo_val, data=data_val, iniciador_id=interaction.user.id)
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
        # Uma única view persistente atende todos os painéis de ação.
        bot.add_view(AcaoParticipantesView())

    @app_commands.command(name="acao", description="Abre o painel para iniciar uma ação.")
    async def acao(self, interaction: discord.Interaction):
        row      = db_get_system_config(str(interaction.guild_id), "acao")
        canal_id = row["canal_interacao_id"] if row else None
        await interaction.response.send_modal(IniciarAcaoModal(canal_id=canal_id))
        log.info(f"{interaction.user} abriu o painel de ações")


async def setup(bot: commands.Bot):
    await bot.add_cog(AcaoCog(bot))
    log.info("AcaoCog carregado com sucesso.")
