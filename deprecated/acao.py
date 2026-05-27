"""
acao.py - Sistema de Ações para o bot Morro do Mineiro
Comando /acao: painel de seleção → regras da ação → inscrição de membros
"""

import logging
import logging.handlers
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

# ── Logger ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_fh  = logging.handlers.RotatingFileHandler(
    LOG_DIR / "acao.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_fh.setFormatter(_fmt)

log = logging.getLogger("acao")
if not log.handlers:
    log.addHandler(_fh)

# ══════════════════════════════════════════════════════════════════════════════
# DADOS DAS AÇÕES
# Cada ação contém:
#   emoji, nome, max_bandidos, max_policiais (None = proporcional),
#   armamento, negociacao, refens, obs (lista de strings extras)
# ══════════════════════════════════════════════════════════════════════════════

ACOES: dict[str, dict] = {
    "loja_tatuagens": {
        "emoji": "🖊️",
        "nome": "Loja de Tatuagens",
        "max_bandidos": 2,
        "max_policiais": 2,
        "armamento": "Apenas armas brancas (pode ser negociada remoção para combate em punhos)",
        "negociacao": "Obrigatória",
        "refens": "Proibido",
        "obs": [],
    },
    "barbearia": {
        "emoji": "✂️",
        "nome": "Barbearia",
        "max_bandidos": None,
        "max_policiais": None,
        "armamento": "Apenas armas brancas (pode ser negociada remoção para combate em punhos)",
        "negociacao": "Obrigatória",
        "refens": "Proibido",
        "obs": ["Bandidos: 4 a 10 (máximo)", "Policiais: igual ao número de bandidos (obrigatório)"],
    },
    "loja_armas_praca": {
        "emoji": "🔫",
        "nome": "Loja de Armas — Praça",
        "max_bandidos": 2,
        "max_policiais": 3,
        "armamento": "Apenas pistolas, exceto AP Pistol (pistola automática)",
        "negociacao": "Obrigatória",
        "refens": "Proibido",
        "obs": ["Nenhum bandido fora (todos obrigatoriamente dentro)"],
    },
    "loja_armas_porto": {
        "emoji": "🔫",
        "nome": "Loja de Armas — Porto",
        "max_bandidos": 5,
        "max_policiais": 7,
        "armamento": "Apenas pistolas, exceto AP Pistol (pistola automática)",
        "negociacao": "Obrigatória",
        "refens": "Proibido",
        "obs": ["Bandidos: 3 a 5 (máximo)", "Policiais: 5 a 7 (máximo), proporcional ao número de bandidos"],
    },
    "conveniencia": {
        "emoji": "🏪",
        "nome": "Loja de Conveniência",
        "max_bandidos": 6,
        "max_policiais": 8,
        "armamento": "Pistola obrigatória, exceto AP Pistol (pistola automática)",
        "negociacao": "Inexistente — ação iniciada ao perímetro ser fechado",
        "refens": "Proibido",
        "obs": [
            "Bandidos: 5 a 6 (máximo)",
            "Policiais: 7 a 8 (máximo), proporcional ao número de bandidos",
            "Trata-se de uma ação de troca de tiros — fuga não é permitida",
            "Até 2 (dois) bandidos podem estar fora da loja, dentro do perímetro",
        ],
    },
    "joalheria": {
        "emoji": "💎",
        "nome": "Joalheria",
        "max_bandidos": 7,
        "max_policiais": 11,
        "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta",
        "negociacao": "Obrigatória",
        "refens": "Opcional, máximo 3",
        "obs": [
            "Bandidos: 5 a 7 — máximo 3 fora e 4 dentro",
            "Policiais: 9 a 11, proporcional ao número de bandidos",
            "Máximo de 3 veículos em caso de fuga",
            "Em caso de fuga, todo o contingente policial pode ser liberado",
        ],
    },
    "concessionaria": {
        "emoji": "🚗",
        "nome": "Concessionária",
        "max_bandidos": 10,
        "max_policiais": 12,
        "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta",
        "negociacao": "Obrigatória",
        "refens": "Opcional, máximo 4",
        "obs": [
            "Bandidos: 8 a 10 — todos dentro",
            "Policiais: 12 (obrigatório)",
            "Máximo de 6 veículos em caso de fuga (3 próprios + 3 da concessionária)",
            "Em caso de fuga, todo o contingente policial pode ser liberado",
            "Limite de 5 granadas de gás para a polícia",
        ],
    },
    "fleeca": {
        "emoji": "💵",
        "nome": "Fleeca",
        "max_bandidos": 8,
        "max_policiais": 10,
        "armamento": "A depender de cada local",
        "negociacao": "Obrigatória",
        "refens": "Obrigatório, máximo 3",
        "obs": [
            "Bandidos: 6 a 8 (máximo)",
            "Policiais: 10 (obrigatório)",
            "Máximo de 3 veículos em caso de fuga",
            "Em caso de fuga, todo o contingente policial pode ser liberado",
        ],
    },
    "shopping": {
        "emoji": "🛍️",
        "nome": "Shopping",
        "max_bandidos": None,
        "max_policiais": None,
        "armamento": "Armamento mínimo: Submetralhadora (AP Pistol não é considerada), com obrigação de ter 4 Rifles",
        "negociacao": "—",
        "refens": "—",
        "obs": [
            "Com atirador: máximo de 4 bandidos em prédios",
            "Sem atirador: limite de 3 bandidos em prédios",
        ],
    },
    "praia": {
        "emoji": "🏖️",
        "nome": "Praia",
        "max_bandidos": None,
        "max_policiais": None,
        "armamento": "Restrito exclusivamente a Submetralhadora (AP Pistol não é considerada)",
        "negociacao": "—",
        "refens": "—",
        "obs": ["O interior da lojinha (cofre) é estritamente proibido"],
    },
    "biblioteca": {
        "emoji": "📚",
        "nome": "Biblioteca",
        "max_bandidos": 10,
        "max_policiais": 12,
        "armamento": "Submetralhadora (AP Pistol não é considerada)",
        "negociacao": "Obrigatória",
        "refens": "Opcional, apenas 1",
        "obs": [
            "Bandidos: 8 a 10 — todos dentro",
            "Policiais: 10 a 12, proporcional ao número de bandidos",
        ],
    },
    "merryweather": {
        "emoji": "⚔️",
        "nome": "Merryweather",
        "max_bandidos": 12,
        "max_policiais": 15,
        "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta",
        "negociacao": "Não há — ação de confronto direto",
        "refens": "Proibido",
        "obs": [
            "Bandidos: 8 a 12 (máximo)",
            "Policiais: 11 a 15, proporcional ao número de bandidos",
            "Os bandidos aguardam o início da ação, que ocorre apenas quando a polícia entrar no perímetro",
        ],
    },
    "acougue": {
        "emoji": "🥩",
        "nome": "Açougue",
        "max_bandidos": 10,
        "max_policiais": 12,
        "armamento": "Submetralhadora (AP Pistol não é considerada), fuzil e escopeta",
        "negociacao": "Obrigatória",
        "refens": "Opcional, máximo 3",
        "obs": [
            "Bandidos: 8 a 10 — todos dentro",
            "Policiais: 12 (obrigatório)",
            "Máximo de 3 veículos em caso de fuga",
            "Em caso de fuga, todo o contingente policial pode ser liberado",
            "Limite de 3 granadas de gás para a polícia",
            "A rotação por fora, entre P1 e P2 e vice-versa, é permitida",
        ],
    },
    "galinheiro": {
        "emoji": "🐔",
        "nome": "Galinheiro",
        "max_bandidos": 10,
        "max_policiais": 12,
        "armamento": "Submetralhadora (AP Pistol não é considerada) e fuzil",
        "negociacao": "Obrigatória",
        "refens": "Opcional, máximo 2",
        "obs": [
            "Bandidos: 8 a 10 — posicionamento dentro e fora do local permitido",
            "Policiais: 12 (obrigatório)",
            "Limite de 3 granadas de gás para a polícia",
            "NÃO é permitido posicionamento na área de mata e morros atrás dos trilhos (fora do perímetro)",
        ],
    },
    "banco_central": {
        "emoji": "🏦",
        "nome": "Banco Central",
        "max_bandidos": 10,
        "max_policiais": 13,
        "armamento": "Fuzil",
        "negociacao": "Obrigatória",
        "refens": "Opcional, máximo 4",
        "obs": [
            "Bandidos: 10 (obrigatório) — máximo 3 em prédios ou 5 no chão",
            "Policiais: 13 (obrigatório)",
            "Máximo de 3 veículos em caso de fuga",
            "Em caso de fuga, todo o contingente policial pode ser liberado",
            "Reféns podem ser usados para neutralizar atiradores ou impedir reposicionamento com helicóptero (não ambos simultaneamente)",
            "Proibido ter bandidos fora em caso de fuga",
        ],
    },
    "banco_paleto": {
        "emoji": "🏦",
        "nome": "Banco Paleto",
        "max_bandidos": 10,
        "max_policiais": 12,
        "armamento": "Fuzil",
        "negociacao": "Não há — ação de confronto direto",
        "refens": "Proibido",
        "obs": [
            "Bandidos: 10 (máximo)",
            "Policiais: 12 (obrigatório)",
            "Os bandidos aguardam o início da ação, que ocorre apenas quando a polícia entrar no perímetro",
        ],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_regras_embed(acao_key: str, membros_inscritos: list[discord.Member] | None = None) -> discord.Embed:
    """Monta o embed de regras de uma ação específica."""
    acao = ACOES[acao_key]
    max_b = acao["max_bandidos"]
    max_p = acao["max_policiais"]

    vagas_b = f"Máximo {max_b}" if max_b else "Ver observações"
    vagas_p = f"Máximo {max_p}" if max_p else "Ver observações"

    embed = discord.Embed(
        title=f"{acao['emoji']} {acao['nome']}",
        color=discord.Color.dark_red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="🔴 Bandidos", value=vagas_b, inline=True)
    embed.add_field(name="🔵 Policiais", value=vagas_p, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🔫 Armamento", value=acao["armamento"], inline=False)
    embed.add_field(name="🤝 Negociação", value=acao["negociacao"], inline=True)
    embed.add_field(name="👤 Reféns", value=acao["refens"], inline=True)

    if acao["obs"]:
        obs_text = "\n".join(f"• {o}" for o in acao["obs"])
        embed.add_field(name="📋 Observações", value=obs_text, inline=False)

    # Membros inscritos
    if membros_inscritos:
        lista = "\n".join(f"• {m.mention}" for m in membros_inscritos)
        embed.add_field(
            name=f"✅ Participantes ({len(membros_inscritos)})",
            value=lista,
            inline=False,
        )
    else:
        embed.add_field(name="✅ Participantes", value="Nenhum inscrito ainda", inline=False)

    embed.set_footer(text="Use os botões abaixo para se inscrever ou remover")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# VIEW — SELETOR DE AÇÃO (Select Menu)
# ══════════════════════════════════════════════════════════════════════════════

class AcaoSelectView(discord.ui.View):
    """Painel com dropdown para escolher a ação."""

    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="Escolha a ação...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=d["nome"], value=k, emoji=d["emoji"])
            for k, d in ACOES.items()
        ],
    )
    async def selecionar_acao(self, interaction: discord.Interaction, select: discord.ui.Select):
        acao_key = select.values[0]
        acao     = ACOES[acao_key]

        embed = _build_regras_embed(acao_key)
        view  = AcaoParticipantesView(acao_key=acao_key)

        await interaction.response.send_message(
            embed=embed,
            view=view,
        )
        log.info(f"{interaction.user} abriu painel de ação: {acao['nome']}")


# ══════════════════════════════════════════════════════════════════════════════
# VIEW — PAINEL DE PARTICIPANTES
# ══════════════════════════════════════════════════════════════════════════════

class AcaoParticipantesView(discord.ui.View):
    """
    Painel público onde os membros podem se inscrever e a liderança pode
    adicionar / remover participantes manualmente.
    """

    def __init__(self, acao_key: str):
        super().__init__(timeout=None)
        self.acao_key = acao_key
        self.inscritos: list[discord.Member] = []

    def _max_bandidos(self) -> int | None:
        return ACOES[self.acao_key]["max_bandidos"]

    def _esta_inscrito(self, member: discord.Member) -> bool:
        return any(m.id == member.id for m in self.inscritos)

    def _atualizar_embed(self) -> discord.Embed:
        return _build_regras_embed(self.acao_key, self.inscritos)

    # ── Botão: Entrar na ação ─────────────────────────────────────────────────
    @discord.ui.button(
        label="✅ Entrar na ação",
        style=discord.ButtonStyle.success,
        custom_id="acao:entrar",
    )
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        member  = interaction.user
        max_b   = self._max_bandidos()

        if self._esta_inscrito(member):
            await interaction.response.send_message(
                "⚠️ Você já está inscrito nesta ação.", ephemeral=True
            )
            return

        if max_b and len(self.inscritos) >= max_b:
            await interaction.response.send_message(
                f"❌ Vagas esgotadas (máximo: {max_b} participantes).", ephemeral=True
            )
            return

        self.inscritos.append(member)
        log.info(f"{member} entrou na ação '{ACOES[self.acao_key]['nome']}'")

        await interaction.response.edit_message(embed=self._atualizar_embed(), view=self)
        await interaction.followup.send(
            f"✅ {member.mention} inscrito na ação **{ACOES[self.acao_key]['nome']}**!",
            ephemeral=True,
        )

    # ── Botão: Sair da ação ───────────────────────────────────────────────────
    @discord.ui.button(
        label="🚪 Sair da ação",
        style=discord.ButtonStyle.danger,
        custom_id="acao:sair",
    )
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        if not self._esta_inscrito(member):
            await interaction.response.send_message(
                "⚠️ Você não está inscrito nesta ação.", ephemeral=True
            )
            return

        self.inscritos = [m for m in self.inscritos if m.id != member.id]
        log.info(f"{member} saiu da ação '{ACOES[self.acao_key]['nome']}'")

        await interaction.response.edit_message(embed=self._atualizar_embed(), view=self)
        await interaction.followup.send(
            f"🚪 {member.mention} removido da ação.", ephemeral=True
        )

    # ── Botão: Adicionar membro (liderança) ───────────────────────────────────
    @discord.ui.button(
        label="➕ Adicionar membro",
        style=discord.ButtonStyle.secondary,
        custom_id="acao:adicionar",
    )
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_lideranca(interaction):
            await interaction.response.send_message(
                "❌ Apenas liderança pode adicionar membros.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AdicionarMembroModal(painel_view=self, painel_msg=interaction.message))

    # ── Botão: Remover membro (liderança) ─────────────────────────────────────
    @discord.ui.button(
        label="➖ Remover membro",
        style=discord.ButtonStyle.secondary,
        custom_id="acao:remover",
    )
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_lideranca(interaction):
            await interaction.response.send_message(
                "❌ Apenas liderança pode remover membros.", ephemeral=True
            )
            return
        if not self.inscritos:
            await interaction.response.send_message(
                "⚠️ Nenhum membro inscrito para remover.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RemoverMembroModal(painel_view=self, painel_msg=interaction.message))

    # ── Botão: Encerrar ação ──────────────────────────────────────────────────
    @discord.ui.button(
        label="🔒 Encerrar ação",
        style=discord.ButtonStyle.danger,
        custom_id="acao:encerrar",
        row=1,
    )
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_lideranca(interaction):
            await interaction.response.send_message(
                "❌ Apenas liderança pode encerrar a ação.", ephemeral=True
            )
            return

        acao_nome = ACOES[self.acao_key]["nome"]
        nomes = ", ".join(m.display_name for m in self.inscritos) if self.inscritos else "Nenhum"

        embed_final = discord.Embed(
            title=f"🔒 Ação Encerrada — {acao_nome}",
            description=f"Encerrada por {interaction.user.mention}",
            color=discord.Color.greyple(),
            timestamp=discord.utils.utcnow(),
        )
        embed_final.add_field(
            name=f"✅ Participantes finais ({len(self.inscritos)})",
            value=nomes,
            inline=False,
        )

        self.stop()
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed_final, view=self)
        log.info(f"{interaction.user} encerrou a ação '{acao_nome}' com {len(self.inscritos)} participante(s)")


# ══════════════════════════════════════════════════════════════════════════════
# VIEWS — Adicionar / Remover membro via UserSelect (lista de membros)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MODALS — Adicionar / Remover membro via menção ou nick
# ══════════════════════════════════════════════════════════════════════════════

class AdicionarMembroModal(discord.ui.Modal, title="Adicionar membro à ação"):
    membro_input = discord.ui.TextInput(
        label="Mencione o membro (@nick)",
        placeholder="Ex: @João Silva",
        max_length=100,
    )

    def __init__(self, painel_view: "AcaoParticipantesView", painel_msg: discord.Message):
        super().__init__()
        self.painel_view = painel_view
        self.painel_msg  = painel_msg

    async def on_submit(self, interaction: discord.Interaction):
        raw   = self.membro_input.value.strip().strip("<@!>")
        guild = interaction.guild
        max_b = self.painel_view._max_bandidos()
        member = None

        # Tenta por ID numérico
        if raw.isdigit():
            member = guild.get_member(int(raw)) or await guild.fetch_member(int(raw))

        # Tenta por display_name ou username (busca na lista em cache)
        if not member:
            raw_lower = raw.lstrip("@").lower()
            member = discord.utils.find(
                lambda m: m.display_name.lower() == raw_lower or m.name.lower() == raw_lower,
                guild.members,
            )

        if not member:
            await interaction.response.send_message(
                "❌ Membro não encontrado. Use @nick exato ou ID do Discord.", ephemeral=True
            )
            return

        if self.painel_view._esta_inscrito(member):
            await interaction.response.send_message(
                f"⚠️ {member.display_name} já está inscrito.", ephemeral=True
            )
            return

        if max_b and len(self.painel_view.inscritos) >= max_b:
            await interaction.response.send_message(
                f"❌ Vagas esgotadas (máximo: {max_b}).", ephemeral=True
            )
            return

        self.painel_view.inscritos.append(member)
        log.info(f"Liderança {interaction.user} adicionou {member} à ação '{ACOES[self.painel_view.acao_key]['nome']}'")

        # Confirma para quem clicou
        await interaction.response.send_message(
            f"✅ {member.mention} adicionado à ação!", ephemeral=True
        )
        # Atualiza o painel público com a lista nova
        try:
            await self.painel_msg.edit(
                embed=self.painel_view._atualizar_embed(), view=self.painel_view
            )
        except Exception as e:
            log.warning(f"Não foi possível atualizar painel após adicionar: {e}")


class RemoverMembroModal(discord.ui.Modal, title="Remover membro da ação"):
    membro_input = discord.ui.TextInput(
        label="Mencione o membro (@nick)",
        placeholder="Ex: @João Silva",
        max_length=100,
    )

    def __init__(self, painel_view: "AcaoParticipantesView", painel_msg: discord.Message):
        super().__init__()
        self.painel_view = painel_view
        self.painel_msg  = painel_msg

    async def on_submit(self, interaction: discord.Interaction):
        raw       = self.membro_input.value.strip().strip("<@!>")
        guild     = interaction.guild
        member    = None

        if raw.isdigit():
            member = guild.get_member(int(raw))

        if not member:
            raw_lower = raw.lstrip("@").lower()
            member = discord.utils.find(
                lambda m: m.display_name.lower() == raw_lower or m.name.lower() == raw_lower,
                guild.members,
            )

        if not member:
            await interaction.response.send_message(
                "❌ Membro não encontrado.", ephemeral=True
            )
            return

        if not self.painel_view._esta_inscrito(member):
            await interaction.response.send_message(
                f"⚠️ {member.display_name} não está inscrito nesta ação.", ephemeral=True
            )
            return

        self.painel_view.inscritos = [m for m in self.painel_view.inscritos if m.id != member.id]
        log.info(f"Liderança {interaction.user} removeu {member} da ação '{ACOES[self.painel_view.acao_key]['nome']}'")

        await interaction.response.send_message(
            f"🚪 {member.mention} removido da ação.", ephemeral=True
        )
        try:
            await self.painel_msg.edit(
                embed=self.painel_view._atualizar_embed(), view=self.painel_view
            )
        except Exception as e:
            log.warning(f"Não foi possível atualizar painel após remover: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE PERMISSÃO
# ══════════════════════════════════════════════════════════════════════════════

def _is_lideranca(interaction: discord.Interaction) -> bool:
    """
    Reutiliza CARGOS_LIDERANCA_FARM do .env para verificar permissão.
    Admins sempre passam.
    """
    import os
    member = interaction.user
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    raw = os.getenv("CARGOS_LIDERANCA_FARM", "")
    ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    return bool({r.id for r in member.roles} & set(ids))


# ══════════════════════════════════════════════════════════════════════════════
# COG — registra o comando /acao
# ══════════════════════════════════════════════════════════════════════════════

class AcaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="acao", description="Abre o painel para iniciar uma ação.")
    async def acao(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎯 Painel de Ações",
            description=(
                "Selecione abaixo a ação que deseja realizar.\n"
                "As regras e vagas serão exibidas logo em seguida."
            ),
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Morro do Mineiro • Sistema de Ações")
        await interaction.response.send_message(embed=embed, view=AcaoSelectView(), ephemeral=False)
        log.info(f"{interaction.user} abriu o painel de ações")


async def setup(bot: commands.Bot):
    await bot.add_cog(AcaoCog(bot))
    log.info("AcaoCog carregado com sucesso.")