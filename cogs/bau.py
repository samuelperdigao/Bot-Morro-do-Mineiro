"""
cogs/bau.py - Sistema de Bau da Gerencia.
Controle de estoque com painel fixo, select menus e modais.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("bau", "bau.log")

BASE_DIR    = Path(__file__).resolve().parent.parent
DB_PATH     = BASE_DIR / "bau.db"
PAINEL_JSON = BASE_DIR / "bau_painel.json"
TZ_SP       = ZoneInfo("America/Sao_Paulo")

CANAL_BAU_ID = 1474869322387292357
CANAL_LOG_ID = 1499589255784173678

CATEGORIAS = {
    "\U0001f392 Itens Gerais": [
        "Drogas", "Camisa de Forca", "Placa Clonada", "Ticket Corrida",
        "Bloqueador de Sinal", "Masterpick", "Adrenalina", "C4",
        "Capuz", "Colete", "Algema", "Nitro", "Chimas", "Vaselina",
        "Pager", "Tesoura",
    ],
    "\U0001f52b Municoes": ["5mm", "9mm", "762mm", "12cbc"],
    "\U0001f527 Attachs": [
        "Clip Extendido", "Supressor", "Compensador",
        "Lanterna Acoplavel", "Mira Avancada", "Grip Avancado",
    ],
    "\U0001f48a Drogas/Efeitos": [
        "Balinha", "Viagra", "Erva", "Oxy", "Lanca Perfume",
        "Meta", "Farinha", "Rape", "Ayahuasca", "Skunk", "Heroina",
    ],
    "\U0001f52a Armas Brancas": [
        "Katana", "Pao (Arma Branca)", "Canivete", "Picareta",
        "Placa (Arma Branca)", "Kit de Desmanche", "Tablet Corrida",
    ],
    "\U0001f52b Armas 1": [
        "Pistola Colt .45", "Pistola M1911", "Sub Skorpion VZ61",
        "Sub Uzi", "Sub M-Tar 21", "Fuzil AK-103",
        "Fuzil G36C", "Escopeta Remington (Armas 1)",
    ],
    "\U0001f52b Armas 2": [
        "Pistola Five-Seven", "Pistola D-Eagle", "Sub Thompson",
        "Sub Tec-9", "Sub M-Tar X", "Fuzil AK-47",
        "Fuzil AUG", "Escopeta Remington (Armas 2)",
    ],
    "\U0001f697 Flipper/Chaves": [
        "Flipper MK5", "Flipper MK4", "Flipper MK3", "Flipper MK2",
        "Flipper MK1", "Chave Platina", "Chave Gold",
    ],
    "\U0001f5dd\ufe0f Chaves de Acao": ["MK1", "MK2", "MK3", "MK4", "MK5"],
    "\U0001f31f Outros": ["FN Fal", "Arco", "Flecha", "M16"],
    "\U0001f4b0 Dinheiro": ["Dinheiro", "Dinheiro Sujo"],
}

# Mapa legivel para exibicao (preserva emojis e acentos originais)
_CATEGORIAS_DISPLAY = {
    "\U0001f392 Itens Gerais":        "\U0001f392 Itens Gerais",
    "\U0001f52b Municoes":            "\U0001f52b Municoes",
    "\U0001f527 Attachs":             "\U0001f527 Attachs",
    "\U0001f48a Drogas/Efeitos":      "\U0001f48a Drogas/Efeitos",
    "\U0001f52a Armas Brancas":       "\U0001f52a Armas Brancas",
    "\U0001f52b Armas 1":             "\U0001f52b Armas 1",
    "\U0001f52b Armas 2":             "\U0001f52b Armas 2",
    "\U0001f697 Flipper/Chaves":      "\U0001f697 Flipper/Chaves",
    "\U0001f5dd\ufe0f Chaves de Acao": "\U0001f5dd\ufe0f Chaves de Acao",
    "\U0001f31f Outros":              "\U0001f31f Outros",
    "\U0001f4b0 Dinheiro":            "\U0001f4b0 Dinheiro",
}


# ── Banco de Dados ─────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bau_estoque (
                produto    TEXT PRIMARY KEY,
                categoria  TEXT NOT NULL,
                quantidade INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bau_historico (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                produto    TEXT NOT NULL,
                categoria  TEXT NOT NULL,
                tipo       TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                user_id    TEXT NOT NULL,
                user_nome  TEXT NOT NULL,
                criado_em  TEXT NOT NULL
            );
        """)
    log.info("Banco bau.db inicializado.")


def _seed_produtos() -> None:
    with _get_conn() as conn:
        for categoria, produtos in CATEGORIAS.items():
            for produto in produtos:
                conn.execute(
                    "INSERT OR IGNORE INTO bau_estoque (produto, categoria, quantidade) "
                    "VALUES (?, ?, 0)",
                    (produto, categoria),
                )
    log.info("Produtos semeados (INSERT OR IGNORE).")


def _get_estoque() -> dict:
    with _get_conn() as conn:
        rows = conn.execute("SELECT produto, quantidade FROM bau_estoque").fetchall()
    return {row["produto"]: row["quantidade"] for row in rows}


def _get_qtd(produto: str) -> int:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT quantidade FROM bau_estoque WHERE produto = ?", (produto,)
        ).fetchone()
    return row["quantidade"] if row else 0


def _movimentar(produto: str, categoria: str, tipo: str, qtd: int,
                user_id: str, user_nome: str) -> int:
    agora = datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")
    delta = qtd if tipo == "entrada" else -qtd
    with _get_conn() as conn:
        conn.execute(
            "UPDATE bau_estoque SET quantidade = quantidade + ? WHERE produto = ?",
            (delta, produto),
        )
        conn.execute(
            "INSERT INTO bau_historico "
            "(produto, categoria, tipo, quantidade, user_id, user_nome, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (produto, categoria, tipo, qtd, user_id, user_nome, agora),
        )
        novo = conn.execute(
            "SELECT quantidade FROM bau_estoque WHERE produto = ?", (produto,)
        ).fetchone()["quantidade"]
    log.info(
        "Movimentacao %s: produto=%s qtd=%d estoque_apos=%d user=%s",
        tipo, produto, qtd, novo, user_id,
    )
    return novo


# ── Referencia do painel ───────────────────────────────────────────────────────

def _load_painel_ref():
    if PAINEL_JSON.exists():
        try:
            data = json.loads(PAINEL_JSON.read_text(encoding="utf-8"))
            return int(data["channel_id"]), int(data["message_id"])
        except Exception as e:
            log.warning("Erro ao ler bau_painel.json: %s", e)
    return None, None


def _save_painel_ref(channel_id: int, message_id: int) -> None:
    PAINEL_JSON.write_text(
        json.dumps({"channel_id": channel_id, "message_id": message_id}),
        encoding="utf-8",
    )


# ── Embeds ─────────────────────────────────────────────────────────────────────

def _build_painel_embed() -> discord.Embed:
    estoque   = _get_estoque()
    agora_str = datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")
    embed = discord.Embed(
        title="\U0001f3e6 Bau da Gerencia",
        color=discord.Color.dark_gold(),
    )
    tem_item = False
    for categoria, produtos in CATEGORIAS.items():
        linhas = "\n".join(
            f"\u2022 {p}: {estoque.get(p, 0)}"
            for p in produtos
            if estoque.get(p, 0) > 0
        )
        if linhas:
            embed.add_field(name=categoria, value=linhas, inline=True)
            tem_item = True
    if not tem_item:
        embed.description = "*Nenhum item no bau no momento.*"
    embed.set_footer(text=f"Ultima atualizacao: {agora_str} (Brasilia)")
    return embed


def _build_log_embed(
    tipo: str,
    produto: str,
    user: discord.Member,
    qtd: int,
    estoque_apos: int,
) -> discord.Embed:
    agora_str = datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")
    if tipo == "entrada":
        titulo = f"\U0001f7e2 Entrada \u2014 {produto}"
        cor    = discord.Color.green()
        sinal  = f"+{qtd}"
    else:
        titulo = f"\U0001f534 Saida \u2014 {produto}"
        cor    = discord.Color.red()
        sinal  = f"-{qtd}"
    embed = discord.Embed(title=titulo, color=cor)
    embed.add_field(
        name="\U0001f464 Usuario",
        value=f"{user.display_name} (`{user.id}`)",
        inline=True,
    )
    embed.add_field(name="\U0001f4e6 Quantidade",    value=sinal,                      inline=True)
    embed.add_field(name="\U0001f5c3\ufe0f Estoque apos", value=f"{estoque_apos} unidades", inline=True)
    embed.add_field(name="\U0001f550 Horario",       value=agora_str,                  inline=False)
    return embed


# ── Views e Modais ─────────────────────────────────────────────────────────────

class QuantidadeModal(discord.ui.Modal):
    quantidade = discord.ui.TextInput(
        label="Quantidade",
        placeholder="Ex: 10",
        max_length=6,
        required=True,
    )

    def __init__(self, tipo: str, produto: str, categoria: str) -> None:
        prefixo = "Entrada" if tipo == "entrada" else "Saida"
        titulo  = f"{prefixo} \u2014 {produto}"
        super().__init__(title=titulo[:45])
        self.tipo      = tipo
        self.produto   = produto
        self.categoria = categoria

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.quantidade.value.strip()
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "\u274c Digite um numero inteiro positivo maior que zero.",
                ephemeral=True,
            )
            return

        qtd = int(raw)

        if self.tipo == "saida":
            atual = _get_qtd(self.produto)
            if atual < qtd:
                await interaction.response.send_message(
                    f"\u274c Estoque insuficiente! Disponivel: **{atual}** unidade(s).",
                    ephemeral=True,
                )
                return

        try:
            estoque_apos = _movimentar(
                self.produto, self.categoria, self.tipo, qtd,
                str(interaction.user.id), interaction.user.display_name,
            )
        except Exception as e:
            log.error("Erro ao movimentar estoque: %s", e, exc_info=True)
            await interaction.response.send_message(
                "\u274c Erro ao registrar movimentacao. Tente novamente.",
                ephemeral=True,
            )
            return

        # Atualiza o painel
        cog = interaction.client.get_cog("BauCog")
        if cog:
            await cog.atualizar_painel()

        # Envia log no canal configurado
        canal_log = interaction.client.get_channel(CANAL_LOG_ID)
        if canal_log is None:
            try:
                canal_log = await interaction.client.fetch_channel(CANAL_LOG_ID)
            except Exception:
                canal_log = None
        if canal_log:
            try:
                await canal_log.send(embed=_build_log_embed(
                    self.tipo, self.produto, interaction.user, qtd, estoque_apos,
                ))
            except Exception as e:
                log.error("Erro ao enviar embed de log: %s", e)

        tipo_label = "Entrada" if self.tipo == "entrada" else "Saida"
        await interaction.response.send_message(
            f"\u2705 **{tipo_label}** de `{qtd}x {self.produto}` registrada! "
            f"Estoque atual: **{estoque_apos}** unidade(s).",
            ephemeral=True,
        )


class AcaoView(discord.ui.View):
    def __init__(self, categoria: str, produto: str) -> None:
        super().__init__(timeout=120)
        self.categoria = categoria
        self.produto   = produto

    @discord.ui.button(label="\u2705 Entrada", style=discord.ButtonStyle.success)
    async def entrada(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            QuantidadeModal("entrada", self.produto, self.categoria)
        )

    @discord.ui.button(label="\u274c Saida", style=discord.ButtonStyle.danger)
    async def saida(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            QuantidadeModal("saida", self.produto, self.categoria)
        )


class ProdutoSelect(discord.ui.Select):
    def __init__(self, categoria: str) -> None:
        self.categoria = categoria
        options = [
            discord.SelectOption(label=p, value=p)
            for p in CATEGORIAS[categoria]
        ]
        super().__init__(placeholder="Selecione o produto...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        produto = self.values[0]
        await interaction.response.edit_message(
            content=f"\U0001f527 **{produto}** \u2014 o que deseja fazer?",
            view=AcaoView(self.categoria, produto),
        )


class ProdutosView(discord.ui.View):
    def __init__(self, categoria: str) -> None:
        super().__init__(timeout=120)
        self.add_item(ProdutoSelect(categoria))


class CategoriaSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=cat, value=cat)
            for cat in CATEGORIAS.keys()
        ]
        super().__init__(
            custom_id="bau:categoria_select",
            placeholder="Selecione uma categoria...",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        categoria = self.values[0]
        await interaction.response.send_message(
            f"\U0001f4e6 **{categoria}** \u2014 selecione o produto:",
            view=ProdutosView(categoria),
            ephemeral=True,
        )


class BauPainelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(CategoriaSelect())


# ── Cog ────────────────────────────────────────────────────────────────────────

class BauCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot                = bot
        self._painel_channel_id = None
        self._painel_message_id = None

    async def cog_load(self) -> None:
        _init_db()
        _seed_produtos()
        ch_id, msg_id = _load_painel_ref()
        self._painel_channel_id = ch_id
        self._painel_message_id = msg_id
        self.bot.add_view(BauPainelView())
        log.info(
            "BauCog carregado (painel_channel=%s, painel_msg=%s).",
            ch_id, msg_id,
        )

    async def atualizar_painel(self) -> None:
        if not self._painel_channel_id or not self._painel_message_id:
            return
        canal = self.bot.get_channel(self._painel_channel_id)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(self._painel_channel_id)
            except Exception as e:
                log.error("Nao foi possivel obter canal do painel: %s", e)
                return
        embed = _build_painel_embed()
        try:
            msg = await canal.fetch_message(self._painel_message_id)
            await msg.edit(embed=embed, view=BauPainelView())
            log.info("Painel do bau editado (msg_id=%s).", self._painel_message_id)
        except discord.NotFound:
            log.warning("Mensagem do painel nao encontrada; recriando...")
            try:
                msg = await canal.send(embed=embed, view=BauPainelView())
                self._painel_channel_id = msg.channel.id
                self._painel_message_id = msg.id
                _save_painel_ref(self._painel_channel_id, self._painel_message_id)
                log.info("Painel recriado (msg_id=%s).", msg.id)
            except Exception as e:
                log.error("Erro ao recriar painel: %s", e)
        except Exception as e:
            log.error("Erro ao editar painel: %s", e)

    @app_commands.command(
        name="bau_setup",
        description="Posta o painel do Bau da Gerencia no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bau_setup(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        # Verifica se ja existe painel ativo
        if self._painel_channel_id and self._painel_message_id:
            canal = self.bot.get_channel(self._painel_channel_id)
            if canal is None:
                try:
                    canal = await self.bot.fetch_channel(self._painel_channel_id)
                except Exception:
                    canal = None
            if canal:
                try:
                    await canal.fetch_message(self._painel_message_id)
                    await interaction.followup.send(
                        "\u26a0\ufe0f O painel do Bau ja esta ativo! Use-o no canal configurado.",
                        ephemeral=True,
                    )
                    return
                except discord.NotFound:
                    pass

        # Posta o painel
        canal_bau = self.bot.get_channel(CANAL_BAU_ID)
        if canal_bau is None:
            try:
                canal_bau = await self.bot.fetch_channel(CANAL_BAU_ID)
            except Exception:
                await interaction.followup.send(
                    "\u274c Canal do bau nao encontrado. Verifique o ID configurado.",
                    ephemeral=True,
                )
                return

        embed = _build_painel_embed()
        msg   = await canal_bau.send(embed=embed, view=BauPainelView())
        self._painel_channel_id = msg.channel.id
        self._painel_message_id = msg.id
        _save_painel_ref(self._painel_channel_id, self._painel_message_id)
        log.info(
            "Painel do bau criado por %s (msg_id=%s, channel_id=%s).",
            interaction.user.id, msg.id, msg.channel.id,
        )
        await interaction.followup.send(
            f"\u2705 Painel do Bau postado em {canal_bau.mention}!",
            ephemeral=True,
        )

    @bau_setup.error
    async def _bau_setup_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "\u274c Voce precisa da permissao **Gerenciar Servidor**.",
                ephemeral=True,
            )
        else:
            log.error("Erro em /bau_setup: %s", error, exc_info=True)
            try:
                await interaction.response.send_message(
                    "\u274c Erro inesperado.", ephemeral=True
                )
            except discord.InteractionResponded:
                await interaction.followup.send("\u274c Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BauCog(bot))
    log.info("BauCog registrado.")
