"""
cogs/bau_gerentes.py - Painel de Slots de Gerentes do Bau.
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

log = get_logger("bau_gerentes", "bau.log")

BASE_DIR    = Path(__file__).resolve().parent.parent
DB_PATH     = BASE_DIR / "bau.db"
PAINEL_JSON = BASE_DIR / "bau_gerentes_painel.json"
TZ_SP       = ZoneInfo("America/Sao_Paulo")

CANAL_GERENTES_ID = 1502107652027715705
SLOTS_INICIAIS    = 10


# ── Banco de Dados ─────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bau_gerentes_slots (
                slot_numero INTEGER PRIMARY KEY,
                user_id     TEXT,
                user_nome   TEXT,
                definido_em TEXT
            )
        """)
    log.info("Tabela bau_gerentes_slots inicializada.")


def _seed_slots() -> None:
    with _get_conn() as conn:
        for i in range(1, SLOTS_INICIAIS + 1):
            conn.execute(
                "INSERT OR IGNORE INTO bau_gerentes_slots (slot_numero) VALUES (?)",
                (i,),
            )
    log.info("Slots iniciais inseridos (INSERT OR IGNORE).")


def _get_slots() -> list:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT slot_numero, user_id, user_nome, definido_em "
            "FROM bau_gerentes_slots ORDER BY slot_numero"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_max_slot() -> int:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(slot_numero) AS m FROM bau_gerentes_slots"
        ).fetchone()
    return row["m"] or 0


def _add_slot() -> int:
    slots_existentes = {s["slot_numero"] for s in _get_slots()}
    novo = 1
    while novo in slots_existentes:
        novo += 1
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO bau_gerentes_slots (slot_numero) VALUES (?)", (novo,)
        )
    return novo


def _remove_slot(slot_numero: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM bau_gerentes_slots WHERE slot_numero = ?", (slot_numero,)
        )


def _definir_membro(slot_numero: int, user_id: str, user_nome: str) -> None:
    agora = datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO bau_gerentes_slots (slot_numero) VALUES (?)",
            (slot_numero,),
        )
        conn.execute(
            "UPDATE bau_gerentes_slots SET user_id=?, user_nome=?, definido_em=? "
            "WHERE slot_numero=?",
            (user_id, user_nome, agora, slot_numero),
        )


def _limpar_slot(slot_numero: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE bau_gerentes_slots "
            "SET user_id=NULL, user_nome=NULL, definido_em=NULL "
            "WHERE slot_numero=?",
            (slot_numero,),
        )


# ── Painel ref ─────────────────────────────────────────────────────────────────

def _load_painel_ref():
    if PAINEL_JSON.exists():
        try:
            data = json.loads(PAINEL_JSON.read_text(encoding="utf-8"))
            return int(data["channel_id"]), int(data["message_id"])
        except Exception as e:
            log.warning("Erro ao ler bau_gerentes_painel.json: %s", e)
    return None, None


def _save_painel_ref(channel_id: int, message_id: int) -> None:
    PAINEL_JSON.write_text(
        json.dumps({"channel_id": channel_id, "message_id": message_id}),
        encoding="utf-8",
    )


# ── Embed ──────────────────────────────────────────────────────────────────────

def _build_embed() -> discord.Embed:
    slots     = _get_slots()
    agora_str = datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M")
    total     = len(slots)
    ocupados  = sum(1 for s in slots if s["user_nome"])

    linhas = []
    for s in slots:
        num  = f"{s['slot_numero']:02d}"
        if s["user_nome"]:
            linhas.append(f"` {num} ` ▸  **{s['user_nome']}**")
        else:
            linhas.append(f"` {num} ` ▸  *─ Vazio ─*")

    desc = (
        "```\n"
        "╔══════════════════════════╗\n"
        "║   GERENTES DO BAÚ        ║\n"
        "╚══════════════════════════╝\n"
        "```\n"
    )
    desc += "\n".join(linhas) if linhas else "*Nenhum slot configurado.*"

    embed = discord.Embed(
        description=desc,
        color=0xFFD700,
    )
    embed.set_author(name="🏦  Slots de Gerentes — Morro do Mineiro")
    embed.set_footer(
        text=f"Morro do Mineiro — Baú da Gerência  ·  {ocupados}/{total} ocupados  ·  {agora_str}"
    )
    return embed


# ── Views auxiliares ───────────────────────────────────────────────────────────

class SlotSelect(discord.ui.Select):
    def __init__(self, slots: list, acao: str, placeholder: str) -> None:
        self.acao = acao
        options   = []
        for s in slots:
            num   = f"{s['slot_numero']:02d}"
            nome  = s["user_nome"] or "Vazio"
            label = f"Slot {num} — {nome}"
            options.append(
                discord.SelectOption(label=label[:100], value=str(s["slot_numero"]))
            )
        super().__init__(placeholder=placeholder, options=options[:25])

    async def callback(self, interaction: discord.Interaction) -> None:
        slot_num = int(self.values[0])
        cog      = interaction.client.get_cog("BauGerentesCog")

        if self.acao == "remove":
            _remove_slot(slot_num)
            if cog:
                await cog.atualizar_painel()
            await interaction.response.edit_message(
                content=f"✅ Slot **`{slot_num:02d}`** removido!", view=None
            )

        elif self.acao == "limpar":
            _limpar_slot(slot_num)
            if cog:
                await cog.atualizar_painel()
            await interaction.response.edit_message(
                content=f"✅ Slot **`{slot_num:02d}`** limpo!", view=None
            )

        elif self.acao == "definir":
            await interaction.response.edit_message(
                content=f"👤 **Slot `{slot_num:02d}`** — Selecione o membro do servidor:",
                view=MembroSelectView(slot_num),
            )

        elif self.acao == "editar":
            await interaction.response.edit_message(
                content=f"🔁 **Slot `{slot_num:02d}`** — Selecione o novo membro:",
                view=MembroSelectView(slot_num),
            )


class SlotSelectView(discord.ui.View):
    def __init__(self, slots: list, acao: str, placeholder: str) -> None:
        super().__init__(timeout=60)
        self.add_item(SlotSelect(slots, acao, placeholder))


class MembroUserSelect(discord.ui.UserSelect):
    def __init__(self, slot_num: int) -> None:
        self.slot_num = slot_num
        super().__init__(
            placeholder="Selecione o membro pelo apelido...",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        membro = self.values[0]
        _definir_membro(self.slot_num, str(membro.id), membro.display_name)
        cog = interaction.client.get_cog("BauGerentesCog")
        if cog:
            await cog.atualizar_painel()
        await interaction.response.edit_message(
            content=f"✅ Slot **`{self.slot_num:02d}`** definido para **{membro.display_name}**!",
            view=None,
        )


class MembroSelectView(discord.ui.View):
    def __init__(self, slot_num: int) -> None:
        super().__init__(timeout=60)
        self.add_item(MembroUserSelect(slot_num))


# ── Painel principal (persistente) ─────────────────────────────────────────────

class BauGerentesPainelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Adicionar Slot",
        emoji="➕",
        style=discord.ButtonStyle.success,
        custom_id="bau_gerentes:add",
        row=0,
    )
    async def add_slot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        novo = _add_slot()
        cog  = interaction.client.get_cog("BauGerentesCog")
        if cog:
            await cog.atualizar_painel()
        await interaction.response.send_message(
            f"✅ Slot **`{novo:02d}`** adicionado!", ephemeral=True
        )

    @discord.ui.button(
        label="Editar Slot",
        emoji="🔁",
        style=discord.ButtonStyle.primary,
        custom_id="bau_gerentes:editar",
        row=0,
    )
    async def editar_slot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        slots = _get_slots()
        if not slots:
            await interaction.response.send_message(
                "❌ Não há slots configurados.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🔁 Selecione o slot que deseja **trocar de membro**:",
            view=SlotSelectView(slots, "editar", "Selecione o slot..."),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remover Slot",
        emoji="➖",
        style=discord.ButtonStyle.danger,
        custom_id="bau_gerentes:remove",
        row=0,
    )
    async def remove_slot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        slots = _get_slots()
        if not slots:
            await interaction.response.send_message(
                "❌ Não há slots para remover.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🗑️ Selecione o slot que deseja **remover permanentemente**:",
            view=SlotSelectView(slots, "remove", "Selecione o slot..."),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Definir Membro",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        custom_id="bau_gerentes:definir",
        row=1,
    )
    async def definir_membro(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        slots = _get_slots()
        if not slots:
            await interaction.response.send_message(
                "❌ Não há slots configurados.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "✏️ Selecione o slot para atribuir um membro:",
            view=SlotSelectView(slots, "definir", "Selecione o slot..."),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Limpar Slot",
        emoji="🗑️",
        style=discord.ButtonStyle.secondary,
        custom_id="bau_gerentes:limpar",
        row=1,
    )
    async def limpar_slot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        slots = [s for s in _get_slots() if s["user_nome"]]
        if not slots:
            await interaction.response.send_message(
                "❌ Não há slots com membros definidos para limpar.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🗑️ Selecione o slot para **limpar o membro**:",
            view=SlotSelectView(slots, "limpar", "Selecione o slot..."),
            ephemeral=True,
        )


# ── Cog ────────────────────────────────────────────────────────────────────────

class BauGerentesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot                = bot
        self._painel_channel_id = None
        self._painel_message_id = None

    async def cog_load(self) -> None:
        _init_db()
        _seed_slots()
        ch_id, msg_id = _load_painel_ref()
        self._painel_channel_id = ch_id
        self._painel_message_id = msg_id
        self.bot.add_view(BauGerentesPainelView())
        log.info(
            "BauGerentesCog carregado (channel=%s, msg=%s).", ch_id, msg_id
        )

    async def atualizar_painel(self) -> None:
        if not self._painel_channel_id or not self._painel_message_id:
            return
        canal = self.bot.get_channel(self._painel_channel_id)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(self._painel_channel_id)
            except Exception as e:
                log.error("Canal do painel de gerentes não encontrado: %s", e)
                return
        embed = _build_embed()
        try:
            msg = await canal.fetch_message(self._painel_message_id)
            await msg.edit(embed=embed, view=BauGerentesPainelView())
        except discord.NotFound:
            log.warning("Mensagem do painel não encontrada; recriando...")
            try:
                msg = await canal.send(embed=embed, view=BauGerentesPainelView())
                self._painel_channel_id = msg.channel.id
                self._painel_message_id = msg.id
                _save_painel_ref(self._painel_channel_id, self._painel_message_id)
            except Exception as e:
                log.error("Erro ao recriar painel de gerentes: %s", e)
        except Exception as e:
            log.error("Erro ao editar painel de gerentes: %s", e)

    @app_commands.command(
        name="bau_gerentes_setup",
        description="Posta o painel de slots de gerentes no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bau_gerentes_setup(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        canal = self.bot.get_channel(CANAL_GERENTES_ID)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(CANAL_GERENTES_ID)
            except Exception:
                await interaction.followup.send(
                    "❌ Canal não encontrado. Verifique o ID configurado.",
                    ephemeral=True,
                )
                return
        embed = _build_embed()
        msg   = await canal.send(embed=embed, view=BauGerentesPainelView())
        self._painel_channel_id = msg.channel.id
        self._painel_message_id = msg.id
        _save_painel_ref(self._painel_channel_id, self._painel_message_id)
        log.info(
            "Painel de gerentes criado por %s (msg=%s, channel=%s).",
            interaction.user.id, msg.id, msg.channel.id,
        )
        await interaction.followup.send(
            f"✅ Painel postado em {canal.mention}!", ephemeral=True
        )

    @bau_gerentes_setup.error
    async def _setup_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
        else:
            log.error("Erro em /bau_gerentes_setup: %s", error, exc_info=True)
            try:
                await interaction.response.send_message(
                    "❌ Erro inesperado.", ephemeral=True
                )
            except discord.InteractionResponded:
                await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BauGerentesCog(bot))
    log.info("BauGerentesCog registrado.")
