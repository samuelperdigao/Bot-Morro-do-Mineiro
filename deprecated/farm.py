"""
farm.py - Extensão FARM: metas semanais, lançamentos e aprovações.
Melhorias: embeds aprimorados, emoji de progresso, cores semânticas,
           /historico, ranking semanal automático, otimizações de estabilidade,
           limpeza de painel órfão, logs rotativos integrados.
"""

import os
import asyncio
import sqlite3
import logging
import logging.handlers
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ── Carrega .env pelo caminho absoluto ────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ── Log rotativo específico do farm ──────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_farm_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "farm.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_farm_handler.setFormatter(_fmt)

log = logging.getLogger("farm")
log.addHandler(_farm_handler)

audit_log = logging.getLogger("audit")

def _farm_audit(action: str, executor_id: int, target_id: int | None = None, **kwargs):
    parts = [f"action={action}", f"executor={executor_id}"]
    if target_id:
        parts.append(f"target={target_id}")
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    audit_log.info(" | ".join(parts))

# ── Configurações ─────────────────────────────────────────────────────────────
def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _env_list(key: str) -> list[int]:
    raw = _env(key)
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]

CARGOS_LIDERANCA  = _env_list("CARGOS_LIDERANCA_FARM")
CARGOS_PERMITIDOS = _env_list("CARGOS_PERMITIDOS_FARM")
DB_PATH           = BASE_DIR / (_env("ARQUIVO_BANCO_FARM") or "farm.db")
TZ_STR            = _env("FUSO_HORARIO_FARM") or "America/Sao_Paulo"
CANAL_AVISOS_ID   = int(_env("CANAL_AVISOS_FARM") or 0) or None
GUILD_ID          = int(os.getenv("GUILD_ID", "0"))

TZ = ZoneInfo(TZ_STR)
PRODUTOS = ["Folha", "Ópio", "Seringa", "Agulha"]
PRODUTO_KEYS = ["folha", "opio", "seringa", "agulha"]  # chaves no banco

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE TEMPO
# ══════════════════════════════════════════════════════════════════════════════

def now_tz() -> datetime:
    return datetime.now(TZ)

def week_id_from(dt: datetime) -> str:
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.isoformat()

def current_week_id() -> str:
    return week_id_from(now_tz())

def janela_valida() -> bool:
    """Lançamentos válidos de segunda (0) a sexta (4)."""
    return now_tz().weekday() <= 4

def fmt_dt(iso: str | None) -> str:
    """Formata ISO para exibição amigável."""
    if not iso:
        return "—"
    return iso[:16].replace("T", " ")

# ══════════════════════════════════════════════════════════════════════════════
# BANCO DE DADOS
# ══════════════════════════════════════════════════════════════════════════════

# Conexão persistente por thread (thread-safe com check_same_thread=False)
_db_conn: sqlite3.Connection | None = None

def get_conn() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")  # melhor concorrência
    return _db_conn

def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS metas (
        guild_id     TEXT NOT NULL,
        week_id      TEXT NOT NULL,
        folha        INTEGER DEFAULT 0,
        opio         INTEGER DEFAULT 0,
        seringa      INTEGER DEFAULT 0,
        agulha       INTEGER DEFAULT 0,
        definido_por TEXT,
        definido_em  TEXT,
        PRIMARY KEY (guild_id, week_id)
    );

    CREATE TABLE IF NOT EXISTS progresso (
        guild_id             TEXT NOT NULL,
        week_id              TEXT NOT NULL,
        user_id              TEXT NOT NULL,
        folha                INTEGER DEFAULT 0,
        opio                 INTEGER DEFAULT 0,
        seringa              INTEGER DEFAULT 0,
        agulha               INTEGER DEFAULT 0,
        status               TEXT DEFAULT 'em_andamento',
        concluida_em         TEXT,
        aprovada             INTEGER DEFAULT 0,
        aprovada_por         TEXT,
        aprovada_em          TEXT,
        painel_channel_id    TEXT,
        painel_message_id    TEXT,
        ultimo_lancamento_em TEXT,
        PRIMARY KEY (guild_id, week_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS eventos (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id  TEXT NOT NULL,
        week_id   TEXT NOT NULL,
        user_id   TEXT NOT NULL,
        criado_em TEXT NOT NULL,
        folha     INTEGER DEFAULT 0,
        opio      INTEGER DEFAULT 0,
        seringa   INTEGER DEFAULT 0,
        agulha    INTEGER DEFAULT 0
    );
    """)
    conn.commit()
    log.info(f"Banco inicializado: {DB_PATH}")

# ── DB helpers ────────────────────────────────────────────────────────────────

def db_get_meta(guild_id: str, week_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM metas WHERE guild_id=? AND week_id=?", (guild_id, week_id)
    ).fetchone()

def db_set_meta(guild_id: str, week_id: str, valores: dict, definido_por: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO metas (guild_id, week_id, folha, opio, seringa, agulha, definido_por, definido_em)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id, week_id) DO UPDATE SET
            folha=excluded.folha, opio=excluded.opio,
            seringa=excluded.seringa, agulha=excluded.agulha,
            definido_por=excluded.definido_por, definido_em=excluded.definido_em
    """, (guild_id, week_id,
          valores["Folha"], valores["Ópio"], valores["Seringa"], valores["Agulha"],
          definido_por, now_tz().isoformat()))
    conn.commit()

def db_get_progresso(guild_id: str, week_id: str, user_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM progresso WHERE guild_id=? AND week_id=? AND user_id=?",
        (guild_id, week_id, user_id)
    ).fetchone()

def db_ensure_progresso(guild_id: str, week_id: str, user_id: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO progresso (guild_id, week_id, user_id) VALUES (?,?,?)",
        (guild_id, week_id, user_id)
    )
    conn.commit()

def db_lancar(guild_id: str, week_id: str, user_id: str, valores: dict):
    db_ensure_progresso(guild_id, week_id, user_id)
    agora = now_tz().isoformat()
    conn = get_conn()
    conn.execute("""
        UPDATE progresso SET
            folha  = folha  + ?,
            opio   = opio   + ?,
            seringa= seringa+ ?,
            agulha = agulha + ?,
            ultimo_lancamento_em = ?
        WHERE guild_id=? AND week_id=? AND user_id=?
    """, (valores["Folha"], valores["Ópio"], valores["Seringa"], valores["Agulha"],
          agora, guild_id, week_id, user_id))
    conn.execute("""
        INSERT INTO eventos (guild_id, week_id, user_id, criado_em, folha, opio, seringa, agulha)
        VALUES (?,?,?,?,?,?,?,?)
    """, (guild_id, week_id, user_id, agora,
          valores["Folha"], valores["Ópio"], valores["Seringa"], valores["Agulha"]))
    conn.commit()

def db_editar_ultimo_evento(guild_id: str, week_id: str, user_id: str, valores: dict) -> bool:
    conn = get_conn()
    ultimo = conn.execute("""
        SELECT * FROM eventos WHERE guild_id=? AND week_id=? AND user_id=?
        ORDER BY id DESC LIMIT 1
    """, (guild_id, week_id, user_id)).fetchone()
    if not ultimo:
        return False

    diff_f = valores["Folha"]   - ultimo["folha"]
    diff_o = valores["Ópio"]    - ultimo["opio"]
    diff_s = valores["Seringa"] - ultimo["seringa"]
    diff_a = valores["Agulha"]  - ultimo["agulha"]

    conn.execute(
        "UPDATE eventos SET folha=?, opio=?, seringa=?, agulha=? WHERE id=?",
        (valores["Folha"], valores["Ópio"], valores["Seringa"], valores["Agulha"], ultimo["id"])
    )
    conn.execute("""
        UPDATE progresso SET
            folha  = MAX(0, folha  + ?),
            opio   = MAX(0, opio   + ?),
            seringa= MAX(0, seringa+ ?),
            agulha = MAX(0, agulha + ?)
        WHERE guild_id=? AND week_id=? AND user_id=?
    """, (diff_f, diff_o, diff_s, diff_a, guild_id, week_id, user_id))
    conn.commit()
    return True

def db_verificar_conclusao(guild_id: str, week_id: str, user_id: str):
    meta = db_get_meta(guild_id, week_id)
    prog = db_get_progresso(guild_id, week_id, user_id)
    if not meta or not prog:
        return
    if prog["status"] == "concluida":
        return
    concluido = all([
        prog["folha"]   >= meta["folha"],
        prog["opio"]    >= meta["opio"],
        prog["seringa"] >= meta["seringa"],
        prog["agulha"]  >= meta["agulha"],
    ])
    if concluido:
        conn = get_conn()
        conn.execute(
            "UPDATE progresso SET status='concluida', concluida_em=? WHERE guild_id=? AND week_id=? AND user_id=?",
            (now_tz().isoformat(), guild_id, week_id, user_id)
        )
        conn.commit()

def db_salvar_painel(guild_id: str, week_id: str, user_id: str, ch_id: str, msg_id: str):
    db_ensure_progresso(guild_id, week_id, user_id)
    conn = get_conn()
    conn.execute(
        "UPDATE progresso SET painel_channel_id=?, painel_message_id=? WHERE guild_id=? AND week_id=? AND user_id=?",
        (ch_id, msg_id, guild_id, week_id, user_id)
    )
    conn.commit()

def db_limpar_painel(guild_id: str, week_id: str, user_id: str):
    """Apaga referência de painel quando a mensagem foi deletada."""
    conn = get_conn()
    conn.execute(
        "UPDATE progresso SET painel_channel_id=NULL, painel_message_id=NULL WHERE guild_id=? AND week_id=? AND user_id=?",
        (guild_id, week_id, user_id)
    )
    conn.commit()

def db_aprovar(guild_id: str, week_id: str, user_id: str, aprovador_id: str):
    conn = get_conn()
    conn.execute("""
        UPDATE progresso SET aprovada=1, aprovada_por=?, aprovada_em=?
        WHERE guild_id=? AND week_id=? AND user_id=?
    """, (aprovador_id, now_tz().isoformat(), guild_id, week_id, user_id))
    conn.commit()

def db_lista_progresso(guild_id: str, week_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM progresso WHERE guild_id=? AND week_id=? ORDER BY (folha+opio+seringa+agulha) DESC",
        (guild_id, week_id)
    ).fetchall()

def db_eventos_usuario(guild_id: str, week_id: str, user_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM eventos WHERE guild_id=? AND week_id=? AND user_id=? ORDER BY id ASC",
        (guild_id, week_id, user_id)
    ).fetchall()

def db_ranking_semana(guild_id: str, week_id: str) -> list[sqlite3.Row]:
    """Retorna participantes ordenados por percentual de conclusão."""
    meta = db_get_meta(guild_id, week_id)
    if not meta:
        return []
    total_meta = (meta["folha"] + meta["opio"] + meta["seringa"] + meta["agulha"]) or 1
    return get_conn().execute("""
        SELECT *, ROUND(CAST(folha+opio+seringa+agulha AS REAL) / ? * 100, 1) as pct
        FROM progresso
        WHERE guild_id=? AND week_id=?
        ORDER BY pct DESC
    """, (total_meta, guild_id, week_id)).fetchall()

# ══════════════════════════════════════════════════════════════════════════════
# EMBEDS
# ══════════════════════════════════════════════════════════════════════════════

def _progress_bar(pct: float, length: int = 10) -> str:
    filled = int(min(pct, 100) / 100 * length)
    return "█" * filled + "░" * (length - filled)

def _status_emoji(pct: float) -> str:
    """Retorna emoji de status baseado no percentual."""
    if pct >= 100:
        return "✅"
    if pct >= 50:
        return "🟡"
    return "🔴"

def _pct_produto(prog_val: int, meta_val: int) -> float:
    return (prog_val / meta_val * 100) if meta_val > 0 else 0.0

def build_farm_embed(
    meta: sqlite3.Row | None,
    prog: sqlite3.Row | None,
    member: discord.Member,
    week_id: str,
) -> discord.Embed:
    status_label = prog["status"] if prog else "em_andamento"
    aprovada = bool(prog and prog["aprovada"])

    # Cor do embed baseada no status
    if aprovada:
        color = discord.Color.gold()
    elif status_label == "concluida":
        color = discord.Color.green()
    else:
        color = discord.Color.blue()

    embed = discord.Embed(
        title=f"🌿 Farm — {member.display_name}",
        description=f"📅 Semana: `{week_id}`",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Progresso por produto com emoji semântico
    for produto, key in zip(PRODUTOS, PRODUTO_KEYS):
        meta_val = (meta[key] if meta else 0) or 0
        prog_val = (prog[key] if prog else 0) or 0
        pct = _pct_produto(prog_val, meta_val)
        bar = _progress_bar(pct)
        emoji = _status_emoji(pct)
        embed.add_field(
            name=f"{emoji} {produto}",
            value=f"{bar}\n`{prog_val}` / `{meta_val}` — **{pct:.0f}%**",
            inline=True,
        )

    # Linha separadora visual
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # Status geral
    status_map = {"em_andamento": "🔄 Em andamento", "concluida": "✅ Concluída"}
    status_txt = status_map.get(status_label, "🔄 Em andamento")
    aprov_txt = "🏆 Aprovada pela liderança" if aprovada else "⏳ Aguardando aprovação"
    ultimo = fmt_dt(prog["ultimo_lancamento_em"] if prog else None)

    embed.add_field(name="Status", value=status_txt, inline=True)
    embed.add_field(name="Aprovação", value=aprov_txt, inline=True)
    embed.add_field(name="Último lançamento", value=f"`{ultimo}`", inline=True)

    if not janela_valida():
        embed.set_footer(text="⚠️ Fora da janela de lançamento (Seg–Sex) • Atualizado")
    else:
        embed.set_footer(text="Atualizado")

    return embed

def build_meta_embed(meta: sqlite3.Row | None, week_id: str) -> discord.Embed:
    embed = discord.Embed(
        title="🎯 Metas da Semana",
        description=f"📅 Semana: `{week_id}`",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    if meta:
        for produto, key in zip(PRODUTOS, PRODUTO_KEYS):
            embed.add_field(name=produto, value=f"`{meta[key]}`", inline=True)
        embed.set_footer(text=f"Definido por ID {meta['definido_por']} • {fmt_dt(meta['definido_em'])}")
    else:
        embed.add_field(
            name="⚠️ Metas não definidas",
            value="Use o botão abaixo para definir as metas desta semana.",
            inline=False,
        )
    return embed

def build_ranking_embed(
    guild_id: str,
    week_id: str,
    participantes: list,
    guild: discord.Guild,
) -> discord.Embed:
    embed = discord.Embed(
        title="🏆 Ranking da Semana",
        description=f"📅 Semana: `{week_id}`",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )

    medalhas = ["🥇", "🥈", "🥉"]
    linhas = []
    for i, row in enumerate(participantes[:10]):
        medalha = medalhas[i] if i < 3 else f"`#{i+1}`"
        member = guild.get_member(int(row["user_id"]))
        nome = member.display_name if member else f"ID {row['user_id']}"
        pct = row["pct"] if "pct" in row.keys() else 0
        status = "✅" if row["status"] == "concluida" else "🔄"
        linhas.append(f"{medalha} **{nome}** — {pct:.0f}% {status}")

    embed.description += "\n\n" + ("\n".join(linhas) if linhas else "Nenhum participante ainda.")
    embed.set_footer(text="Ranking por % de conclusão total")
    return embed

# ══════════════════════════════════════════════════════════════════════════════
# MODALS
# ══════════════════════════════════════════════════════════════════════════════

class DefinirMetasModal(discord.ui.Modal, title="Definir Metas da Semana"):
    folha   = discord.ui.TextInput(label="Meta Folha",   placeholder="Ex: 500")
    opio    = discord.ui.TextInput(label="Meta Ópio",    placeholder="Ex: 300")
    seringa = discord.ui.TextInput(label="Meta Seringa", placeholder="Ex: 200")
    agulha  = discord.ui.TextInput(label="Meta Agulha",  placeholder="Ex: 150")

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str):
        super().__init__()
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valores = {
                "Folha":   int(self.folha.value),
                "Ópio":    int(self.opio.value),
                "Seringa": int(self.seringa.value),
                "Agulha":  int(self.agulha.value),
            }
            if any(v < 0 for v in valores.values()):
                raise ValueError("Negativos")
        except ValueError:
            await interaction.response.send_message(
                "❌ Insira apenas números inteiros positivos.", ephemeral=True
            )
            return

        db_set_meta(self.guild_id, self.week_id, valores, str(interaction.user.id))
        _farm_audit("META_DEFINIDA", interaction.user.id, week_id=self.week_id, valores=str(valores))
        await interaction.response.send_message(
            f"✅ Metas definidas para a semana `{self.week_id}`!", ephemeral=True
        )

    async def on_error(self, interaction, error):
        log.error(f"Erro no DefinirMetasModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao definir metas.")


class LancarModal(discord.ui.Modal, title="Lançar Produção"):
    folha   = discord.ui.TextInput(label="Folha",   placeholder="0", required=False, default="0")
    opio    = discord.ui.TextInput(label="Ópio",    placeholder="0", required=False, default="0")
    seringa = discord.ui.TextInput(label="Seringa", placeholder="0", required=False, default="0")
    agulha  = discord.ui.TextInput(label="Agulha",  placeholder="0", required=False, default="0")

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str, user_id: str):
        super().__init__()
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        if not janela_valida():
            await interaction.response.send_message(
                "❌ Fora da janela de lançamento (Segunda a Sexta).", ephemeral=True
            )
            return
        try:
            valores = {
                "Folha":   int(self.folha.value or 0),
                "Ópio":    int(self.opio.value or 0),
                "Seringa": int(self.seringa.value or 0),
                "Agulha":  int(self.agulha.value or 0),
            }
            if any(v < 0 for v in valores.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Valores inválidos. Use inteiros positivos.", ephemeral=True)
            return

        if all(v == 0 for v in valores.values()):
            await interaction.response.send_message("❌ Informe pelo menos um valor acima de zero.", ephemeral=True)
            return

        # ── Lê status ANTES de lançar para detectar mudança ──────────────────
        prog_antes = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        status_antes = prog_antes["status"] if prog_antes else "em_andamento"

        db_lancar(self.guild_id, self.week_id, self.user_id, valores)
        db_verificar_conclusao(self.guild_id, self.week_id, self.user_id)
        prog_depois = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        _farm_audit("LANCAMENTO", int(self.user_id), valores=str(valores))

        await interaction.response.send_message("✅ Produção lançada com sucesso!", ephemeral=True)
        await self.cog._atualizar_painel(self.guild_id, self.week_id, self.user_id)

        # Notifica na pasta se acabou de concluir a meta agora
        if status_antes != "concluida" and prog_depois and prog_depois["status"] == "concluida":
            await self.cog._notificar_conclusao(interaction.guild, self.user_id, self.week_id)

    async def on_error(self, interaction, error):
        log.error(f"Erro no LancarModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao lançar produção.")


class EditarUltimoModal(discord.ui.Modal, title="Editar Último Lançamento"):
    folha   = discord.ui.TextInput(label="Folha",   placeholder="Novo valor total", required=False, default="0")
    opio    = discord.ui.TextInput(label="Ópio",    placeholder="Novo valor total", required=False, default="0")
    seringa = discord.ui.TextInput(label="Seringa", placeholder="Novo valor total", required=False, default="0")
    agulha  = discord.ui.TextInput(label="Agulha",  placeholder="Novo valor total", required=False, default="0")

    def __init__(self, cog: "FarmCog", week_id: str, guild_id: str, user_id: str):
        super().__init__()
        self.cog = cog
        self.week_id = week_id
        self.guild_id = guild_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valores = {
                "Folha":   int(self.folha.value or 0),
                "Ópio":    int(self.opio.value or 0),
                "Seringa": int(self.seringa.value or 0),
                "Agulha":  int(self.agulha.value or 0),
            }
            if any(v < 0 for v in valores.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Valores inválidos.", ephemeral=True)
            return

        ok = db_editar_ultimo_evento(self.guild_id, self.week_id, self.user_id, valores)
        if not ok:
            await interaction.response.send_message(
                "❌ Nenhum lançamento encontrado para editar.", ephemeral=True
            )
            return

        db_verificar_conclusao(self.guild_id, self.week_id, self.user_id)
        _farm_audit("EDICAO", int(self.user_id), valores=str(valores))
        await interaction.response.send_message("✅ Último lançamento editado!", ephemeral=True)
        await self.cog._atualizar_painel(self.guild_id, self.week_id, self.user_id)

    async def on_error(self, interaction, error):
        log.error(f"Erro no EditarUltimoModal: {error}", exc_info=True)
        await _safe_respond(interaction, "❌ Erro ao editar lançamento.")

# ══════════════════════════════════════════════════════════════════════════════
# VIEWS (timeout=900s para evitar acúmulo de estado após restart)
# ══════════════════════════════════════════════════════════════════════════════

VIEW_TIMEOUT = 900  # 15 minutos

class MetaView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.guild_id = guild_id
        self.week_id = week_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="📝 Definir Metas", style=discord.ButtonStyle.primary)
    async def definir_metas(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
            await interaction.response.send_message("❌ Apenas liderança pode definir metas.", ephemeral=True)
            return
        await _safe_send_modal(interaction, DefinirMetasModal(self.cog, self.week_id, self.guild_id))

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary)
    async def atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        meta = db_get_meta(self.guild_id, self.week_id)
        embed = build_meta_embed(meta, self.week_id)
        await interaction.edit_original_response(embed=embed, view=MetaView(self.cog, self.guild_id, self.week_id))


class FarmView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, user_id: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.guild_id = guild_id
        self.week_id = week_id
        self.user_id = user_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    def _owns(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="📦 Lançar", style=discord.ButtonStyle.success)
    async def lancar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owns(interaction):
            await interaction.response.send_message("❌ Este painel não é seu.", ephemeral=True)
            return
        await _safe_send_modal(interaction, LancarModal(self.cog, self.week_id, self.guild_id, self.user_id))

    @discord.ui.button(label="✏️ Editar último", style=discord.ButtonStyle.secondary)
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owns(interaction):
            await interaction.response.send_message("❌ Este painel não é seu.", ephemeral=True)
            return
        await _safe_send_modal(interaction, EditarUltimoModal(self.cog, self.week_id, self.guild_id, self.user_id))

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary)
    async def atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        meta = db_get_meta(self.guild_id, self.week_id)
        prog = db_get_progresso(self.guild_id, self.week_id, self.user_id)
        embed = build_farm_embed(meta, prog, interaction.user, self.week_id)
        await interaction.edit_original_response(
            embed=embed,
            view=FarmView(self.cog, self.guild_id, self.week_id, self.user_id)
        )


class ResultadoView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, participantes: list, guild: discord.Guild = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.guild_id = guild_id
        self.week_id = week_id

        options = []
        for p in participantes:
            # Tenta pegar o nick do membro no servidor
            nome = f"ID: {p['user_id']}"
            if guild:
                member = guild.get_member(int(p["user_id"]))
                if member:
                    nome = member.display_name

            emoji = "✅" if p["status"] == "concluida" else "🔄"
            aprov = "Aprovado" if p["aprovada"] else "Pendente"
            options.append(discord.SelectOption(
                label=nome[:100],
                value=p["user_id"],
                description=f"{emoji} {p['status'].replace('_', ' ').title()} | {aprov}",
            ))

        if not options:
            options = [discord.SelectOption(label="Nenhum participante", value="none")]

        self.select = discord.ui.Select(
            placeholder="Selecione um membro para ver detalhes",
            options=options[:25],
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        user_id = self.select.values[0]
        if user_id == "none":
            await interaction.response.send_message("Nenhum participante.", ephemeral=True)
            return
        await interaction.response.defer()

        # Força re-verificação de conclusão (corrige status desatualizado)
        db_verificar_conclusao(self.guild_id, self.week_id, user_id)

        prog = db_get_progresso(self.guild_id, self.week_id, user_id)
        meta = db_get_meta(self.guild_id, self.week_id)
        member = interaction.guild.get_member(int(user_id)) or await _safe_fetch_member(interaction.guild, int(user_id))

        embed = build_farm_embed(meta, prog, member or interaction.user, self.week_id)
        embed.title = f"📊 Resultado — {member.display_name if member else user_id}"

        pode_aprovar = prog and prog["status"] == "concluida" and not prog["aprovada"]
        view = DetalheResultadoView(self.cog, self.guild_id, self.week_id, user_id, bool(pode_aprovar))
        await interaction.edit_original_response(embed=embed, view=view)


class DetalheResultadoView(discord.ui.View):
    def __init__(self, cog: "FarmCog", guild_id: str, week_id: str, user_id: str, pode_aprovar: bool):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.guild_id = guild_id
        self.week_id = week_id
        self.user_id = user_id

        btn_aprovar = discord.ui.Button(
            label="✅ Aprovar Meta",
            style=discord.ButtonStyle.success,
            disabled=not pode_aprovar,
        )
        btn_aprovar.callback = self._aprovar
        self.add_item(btn_aprovar)

        btn_voltar = discord.ui.Button(label="⬅️ Voltar", style=discord.ButtonStyle.secondary)
        btn_voltar.callback = self._voltar
        self.add_item(btn_voltar)

    async def _aprovar(self, interaction: discord.Interaction):
        if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
            await interaction.response.send_message("❌ Apenas liderança pode aprovar.", ephemeral=True)
            return
        db_aprovar(self.guild_id, self.week_id, self.user_id, str(interaction.user.id))
        _farm_audit("META_APROVADA", interaction.user.id, int(self.user_id))
        await interaction.response.send_message("✅ Meta aprovada!", ephemeral=True)
        await self.cog._notificar_aprovacao(interaction.guild, self.user_id, interaction.user)

    async def _voltar(self, interaction: discord.Interaction):
        await interaction.response.defer()
        participantes = db_lista_progresso(self.guild_id, self.week_id)
        view = ResultadoView(self.cog, self.guild_id, self.week_id, participantes, interaction.guild)
        embed = discord.Embed(
            title="📊 Resultados da Semana",
            description=f"📅 Semana: `{self.week_id}` — {len(participantes)} participante(s)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.edit_original_response(embed=embed, view=view)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS GERAIS
# ══════════════════════════════════════════════════════════════════════════════

def _tem_cargo(member: discord.Member, cargo_ids: list[int]) -> bool:
    if member.guild_permissions.administrator:
        return True
    return bool({r.id for r in member.roles} & set(cargo_ids))

async def _safe_send_modal(interaction: discord.Interaction, modal: discord.ui.Modal):
    """Envia modal; se interaction já respondida, avisa com followup."""
    try:
        await interaction.response.send_modal(modal)
    except discord.InteractionResponded:
        await interaction.followup.send(
            "⚠️ Sessão expirada. Use o comando novamente.", ephemeral=True
        )
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

async def _safe_fetch_member(guild: discord.Guild, member_id: int):
    try:
        return await guild.fetch_member(member_id)
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# COG PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class FarmCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()
        self._ranking_task.start()
        log.info("FarmCog inicializado.")

    def cog_unload(self):
        self._ranking_task.cancel()

    # ── Atualização automática do painel ──────────────────────────────────────

    async def _atualizar_painel(self, guild_id: str, week_id: str, user_id: str):
        """Atualiza o embed do /farm após lançamento. Limpa referência se mensagem foi deletada."""
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
            # Mensagem foi deletada: limpa referência no banco para não tentar novamente
            db_limpar_painel(guild_id, week_id, user_id)
            log.info(f"Painel órfão removido para user {user_id}")
        except Exception as e:
            log.warning(f"Falha ao atualizar painel {user_id}: {e}")

    # ── Notificação de aprovação ───────────────────────────────────────────────

    async def _notificar_aprovacao(self, guild: discord.Guild, user_id: str, aprovador: discord.Member):
        membro = guild.get_member(int(user_id)) or await _safe_fetch_member(guild, int(user_id))
        if not membro:
            return

        embed = discord.Embed(
            title="🏆 Meta Aprovada!",
            description=(
                f"Parabéns, **{membro.display_name}**!\n"
                f"Sua meta da semana foi aprovada por {aprovador.mention}."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=membro.display_avatar.url)

        # Tenta DM
        try:
            await membro.send(embed=embed)
            return
        except Exception:
            pass

        # Fallback: canal de avisos
        if CANAL_AVISOS_ID:
            try:
                canal = guild.get_channel(CANAL_AVISOS_ID) or await guild.fetch_channel(CANAL_AVISOS_ID)
                await canal.send(membro.mention, embed=embed)
            except Exception as e:
                log.warning(f"Falha ao notificar canal de avisos: {e}")

    # ── Notificação de meta concluída na pasta do usuário ────────────────────

    async def _notificar_conclusao(self, guild: discord.Guild, user_id: str, week_id: str):
        """Envia notificação na pasta privada do usuário quando ele bate a meta."""
        from pathlib import Path
        import json as _json

        membro = guild.get_member(int(user_id)) or await _safe_fetch_member(guild, int(user_id))
        if not membro:
            return

        # Busca o canal privado do membro no channel_map.json
        channel_map_path = Path(__file__).resolve().parent / "channel_map.json"
        canal_privado = None
        if channel_map_path.exists():
            try:
                with open(channel_map_path, "r", encoding="utf-8") as f:
                    channel_map = _json.load(f)
                ch_id = channel_map.get(str(user_id))
                if ch_id:
                    canal_privado = guild.get_channel(int(ch_id)) or await _safe_fetch_channel(guild, int(ch_id))
            except Exception as e:
                log.warning(f"Erro ao ler channel_map para notificação: {e}")

        embed = discord.Embed(
            title="🎯 Meta Concluída!",
            description=(
                f"{membro.mention} acabou de bater a meta da semana `{week_id}`!\n\n"
                f"Aguardando aprovação da liderança."
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.set_footer(text="Use /resultado para aprovar a meta")

        # Notifica na pasta privada do membro (visível para ele e liderança)
        if canal_privado:
            try:
                await canal_privado.send(embed=embed)
                log.info(f"Notificação de conclusão enviada para pasta de {user_id}")
                return
            except Exception as e:
                log.warning(f"Falha ao notificar pasta privada de {user_id}: {e}")

        # Fallback: canal de avisos
        if CANAL_AVISOS_ID:
            try:
                canal = guild.get_channel(CANAL_AVISOS_ID) or await guild.fetch_channel(CANAL_AVISOS_ID)
                await canal.send(embed=embed)
            except Exception as e:
                log.warning(f"Falha ao notificar canal de avisos: {e}")

    # ── Task: ranking automático toda sexta às 23h ────────────────────────────

    @tasks.loop(minutes=1)
    async def _ranking_task(self):
        """Verifica se é sexta às 23:00 para postar o ranking semanal."""
        dt = now_tz()
        # Sexta = weekday 4, às 23:00 (janela de 1 minuto)
        if dt.weekday() != 4 or dt.hour != 23 or dt.minute != 0:
            return
        if not CANAL_AVISOS_ID or not GUILD_ID:
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        week_id = current_week_id()
        participantes = db_ranking_semana(str(GUILD_ID), week_id)
        if not participantes:
            return

        try:
            canal = guild.get_channel(CANAL_AVISOS_ID) or await guild.fetch_channel(CANAL_AVISOS_ID)
            embed = build_ranking_embed(str(GUILD_ID), week_id, participantes, guild)
            await canal.send(embed=embed)
            log.info(f"Ranking semanal postado para semana {week_id}")
        except Exception as e:
            log.error(f"Erro ao postar ranking: {e}")

    @_ranking_task.before_loop
    async def _before_ranking(self):
        await self.bot.wait_until_ready()

    # ── Comandos slash ────────────────────────────────────────────────────────

    @app_commands.command(name="meta", description="Painel de metas semanais (liderança).")
    async def cmd_meta(self, interaction: discord.Interaction):
        if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
            await interaction.response.send_message("❌ Apenas liderança pode acessar o painel de metas.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        meta = db_get_meta(guild_id, week_id)
        embed = build_meta_embed(meta, week_id)
        await interaction.response.send_message(embed=embed, view=MetaView(self, guild_id, week_id), ephemeral=True)

    @app_commands.command(name="farm", description="Seu painel de farm semanal.")
    async def cmd_farm(self, interaction: discord.Interaction):
        if not _tem_cargo(interaction.user, CARGOS_PERMITIDOS):
            await interaction.response.send_message("❌ Você não tem permissão para usar o farm.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        user_id = str(interaction.user.id)

        db_ensure_progresso(guild_id, week_id, user_id)
        meta = db_get_meta(guild_id, week_id)
        prog = db_get_progresso(guild_id, week_id, user_id)
        embed = build_farm_embed(meta, prog, interaction.user, week_id)
        await interaction.response.send_message(embed=embed, view=FarmView(self, guild_id, week_id, user_id), ephemeral=True)

        # Salva referência do painel para atualização automática
        try:
            msg = await interaction.original_response()
            db_salvar_painel(guild_id, week_id, user_id, str(interaction.channel_id), str(msg.id))
        except Exception as e:
            log.warning(f"Não foi possível salvar referência do painel: {e}")

    @app_commands.command(name="resultado", description="Painel de resultados da semana (liderança).")
    async def cmd_resultado(self, interaction: discord.Interaction):
        if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
            await interaction.response.send_message("❌ Apenas liderança pode ver resultados.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        participantes = db_lista_progresso(guild_id, week_id)
        embed = discord.Embed(
            title="📊 Resultados da Semana",
            description=f"📅 Semana: `{week_id}` — {len(participantes)} participante(s)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, view=ResultadoView(self, guild_id, week_id, participantes, interaction.guild), ephemeral=True)

    @app_commands.command(name="historico", description="Histórico de lançamentos de um membro na semana.")
    @app_commands.describe(membro="Membro para consultar (deixe vazio para ver o seu próprio)")
    async def cmd_historico(self, interaction: discord.Interaction, membro: discord.Member = None):
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()

        # Se não especificou membro, mostra o próprio. Liderança pode ver qualquer um.
        alvo = membro or interaction.user
        if membro and str(interaction.user.id) != str(membro.id):
            if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
                await interaction.response.send_message(
                    "❌ Apenas liderança pode ver o histórico de outros membros.", ephemeral=True
                )
                return

        eventos = db_eventos_usuario(guild_id, week_id, str(alvo.id))

        embed = discord.Embed(
            title=f"📋 Histórico — {alvo.display_name}",
            description=f"📅 Semana: `{week_id}`",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=alvo.display_avatar.url)

        if not eventos:
            embed.add_field(name="Sem lançamentos", value="Nenhum lançamento encontrado nesta semana.", inline=False)
        else:
            linhas = []
            for i, ev in enumerate(eventos, 1):
                partes = []
                for p, k in zip(PRODUTOS, PRODUTO_KEYS):
                    if ev[k] > 0:
                        partes.append(f"{p}: `{ev[k]}`")
                conteudo = " | ".join(partes) if partes else "todos zerados"
                linhas.append(f"`#{i}` {fmt_dt(ev['criado_em'])} — {conteudo}")

            # Discord tem limite de 1024 por field; divide se necessário
            chunk = "\n".join(linhas[:15])
            embed.add_field(name=f"{len(eventos)} lançamento(s)", value=chunk or "—", inline=False)
            if len(eventos) > 15:
                embed.set_footer(text=f"Exibindo 15 de {len(eventos)} lançamentos")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ranking", description="Ranking manual da semana (liderança).")
    async def cmd_ranking(self, interaction: discord.Interaction):
        if not _tem_cargo(interaction.user, CARGOS_LIDERANCA):
            await interaction.response.send_message("❌ Apenas liderança pode ver o ranking.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        week_id = current_week_id()
        participantes = db_ranking_semana(guild_id, week_id)
        embed = build_ranking_embed(guild_id, week_id, participantes, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(FarmCog(bot))
    log.info("FarmCog adicionado ao bot.")