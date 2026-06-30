"""
services/db_service.py - Todas as funções de acesso ao banco SQLite do farm.
"""

import json
import sqlite3
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import DB_PATH, TZ_STR
from core.date_utils import format_datetime_br
from services.db_schema import ensure_schema

log = logging.getLogger("farm")

TZ = ZoneInfo(TZ_STR)
PRODUTOS     = ["Folha", "Ópio", "Seringa", "Agulha"]
PRODUTO_KEYS = ["folha", "opio", "seringa", "agulha"]
DINHEIRO_SUJO_ITEM = "Dinheiro Sujo"
DINHEIRO_LIMPO_ITEM = "Dinheiro Limpo"
DINHEIRO_ITEMS = (DINHEIRO_SUJO_ITEM, DINHEIRO_LIMPO_ITEM)

_LEGACY_KEY_TO_NOME = {
    "folha": "Folha",
    "opio": "Ópio",
    "seringa": "Seringa",
    "agulha": "Agulha",
}


# ── Helpers de tempo ──────────────────────────────────────────────────────────

def now_tz() -> datetime:
    return datetime.now(TZ)

def week_id_from(dt: datetime) -> str:
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.isoformat()

def current_week_id() -> str:
    return week_id_from(now_tz())

def janela_valida() -> bool:
    return 0 <= now_tz().weekday() <= 6

def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    return format_datetime_br(iso, fallback="—")


# ── Conexão ───────────────────────────────────────────────────────────────────

_db_conn: sqlite3.Connection | None = None

def get_conn() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn

def _ensure_column(conn: sqlite3.Connection, table: str, col: str, definition: str):
    """Adiciona coluna à tabela se ainda não existir."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

def init_db():
    conn = get_conn()
    ensure_schema(conn, DB_PATH, log)


def classificar_resultado(meta_itens: dict, prog_itens: dict) -> str:
    """
    Classifica o resultado com base no percentual individual de cada item.

    🔥 Elite      → TODOS os itens individualmente >= 130% da meta
    ✅ Meta Batida → TODOS os itens individualmente >= 100% da meta
    ⚠️ Parcial    → pelo menos 1 item com entrega > 0 (qualquer quantidade)
    ❌ Zero       → NENHUM item entregue (tudo = 0) OU sem registro
    """
    if not meta_itens:
        return "zero"

    # Verifica se há qualquer entrega (total > 0 em qualquer item)
    total_entregue = sum(prog_itens.get(nome, 0) for nome in meta_itens)
    if total_entregue == 0:
        return "zero"

    pcts = []
    for nome, meta_val in meta_itens.items():
        if meta_val <= 0:
            continue
        prog_val = prog_itens.get(nome, 0)
        pcts.append(prog_val / meta_val * 100)

    if not pcts:
        # Meta sem valores definidos, mas entregou algo → parcial
        return "parcial"

    if all(p >= 130 for p in pcts):
        return "elite"
    if all(p >= 100 for p in pcts):
        return "meta_batida"
    # Entregou qualquer coisa (total > 0) → mínimo é parcial
    return "parcial"


CLASSIFICACAO_LABEL = {
    "elite":       "🔥 Elite",
    "meta_batida": "✅ Meta Batida",
    "parcial":     "⚠️ Parcial",
    "zero":        "❌ Zero",
}


# ── Helpers de itens (legado + JSON) ──────────────────────────────────────────

def db_meta_itens(meta) -> dict:
    """Retorna {nome: quantidade} para uma linha de metas (JSON ou colunas fixas)."""
    if meta is None:
        return {}
    if meta["itens_json"]:
        return json.loads(meta["itens_json"])
    return {
        "Folha":   meta["folha"]   or 0,
        "Ópio":    meta["opio"]    or 0,
        "Seringa": meta["seringa"] or 0,
        "Agulha":  meta["agulha"]  or 0,
    }

def db_meta_tipo(meta) -> str:
    """Retorna o tipo salvo da meta. Rows legadas sem tipo são tratadas como itens."""
    if meta is None:
        return "itens"
    try:
        return meta["meta_tipo"] or "itens"
    except (IndexError, KeyError):
        return "itens"

def db_meta_tipo_efetivo(meta) -> str:
    """
    Retorna o tipo que deve contar para progresso/ranking.

    Novas metas sao exclusivas: itens OU dinheiro. Linhas antigas marcadas
    como "misto" continuam intactas no banco, mas sao interpretadas como
    itens quando ainda carregam metas de produto.
    """
    tipo = db_meta_tipo(meta)
    if tipo in {"itens", "colete", "dinheiro"}:
        return tipo
    itens = db_meta_itens(meta)
    if itens and any((qtd or 0) > 0 for qtd in itens.values()):
        return "itens"
    return "dinheiro"

def db_meta_itens_ativos(meta) -> dict:
    """Itens que contam para a meta ativa."""
    if db_meta_tipo_efetivo(meta) not in {"itens", "colete"}:
        return {}
    return db_meta_itens(meta)

def db_meta_dinheiro_ativo(meta) -> float:
    """Valor em dinheiro que conta para a meta ativa."""
    if meta is None or db_meta_tipo_efetivo(meta) != "dinheiro":
        return 0
    itens = db_meta_itens(meta)
    valores = [
        float(itens.get(nome, 0) or 0)
        for nome in DINHEIRO_ITEMS
    ]
    total_itens = sum(valores)
    return total_itens if total_itens > 0 else (meta["meta_dinheiro"] or 0)

def db_meta_dinheiro_itens_ativos(meta) -> dict:
    """Retorna metas separadas de dinheiro sujo/limpo quando definidas."""
    if meta is None or db_meta_tipo_efetivo(meta) != "dinheiro":
        return {}
    itens = db_meta_itens(meta)
    return {
        nome: float(itens.get(nome, 0) or 0)
        for nome in DINHEIRO_ITEMS
        if float(itens.get(nome, 0) or 0) > 0
    }

def db_prog_itens(prog) -> dict:
    """Retorna {nome: quantidade_atual} para uma linha de progresso (JSON ou colunas fixas)."""
    if prog is None:
        return {}
    if prog["itens_prog_json"]:
        return json.loads(prog["itens_prog_json"])
    return {nome: (prog[key] or 0) for key, nome in _LEGACY_KEY_TO_NOME.items()}

def db_evento_itens(ev) -> dict:
    """Retorna {nome: quantidade} para uma linha de eventos (JSON ou colunas fixas)."""
    if ev is None:
        return {}
    if ev["itens_json"]:
        return json.loads(ev["itens_json"])
    result = {}
    for key, nome in _LEGACY_KEY_TO_NOME.items():
        val = ev[key] or 0
        if val:
            result[nome] = val
    return result


# ── Guild Config ───────────────────────────────────────────────────────────────

def db_get_guild_config(guild_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)
    ).fetchone()

def db_set_guild_config(guild_id: str, **fields):
    """Upsert parcial de guild_config. Passa apenas os campos a atualizar."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT guild_id FROM guild_config WHERE guild_id=?", (guild_id,)
    ).fetchone()
    if not existing:
        conn.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        conn.commit()
    for col, val in fields.items():
        conn.execute(
            f"UPDATE guild_config SET {col}=? WHERE guild_id=?", (val, guild_id)
        )
    conn.commit()

def db_is_bot_configured(guild_id: str) -> bool:
    cfg = db_get_guild_config(guild_id)
    if not cfg:
        return False
    return all([
        cfg["approval_channel_id"],
        cfg["log_channel_id"],
        cfg["private_category_id"],
        cfg["member_role_id"],
    ])

def db_is_farm_configured(guild_id: str) -> bool:
    cfg = db_get_guild_config(guild_id)
    if not cfg:
        return False
    return bool(cfg["cargos_lideranca_farm"] and cfg["cargos_permitidos_farm"])

def db_is_encomenda_configured(guild_id: str) -> bool:
    cfg = db_get_guild_config(guild_id)
    if not cfg:
        return False
    return bool(cfg["canal_encomendas_id"])

def db_is_ausencia_configured(guild_id: str) -> bool:
    cfg = db_get_guild_config(guild_id)
    if not cfg:
        return False
    return bool(cfg["canal_ausencias_id"])

def db_get_approver_role_ids(guild_id: str) -> list[int]:
    cfg = db_get_guild_config(guild_id)
    if not cfg or not cfg["approver_role_ids"]:
        return []
    return [int(x.strip()) for x in cfg["approver_role_ids"].split(",") if x.strip()]

def db_get_lideranca_role_ids(guild_id: str) -> list[int]:
    cfg = db_get_guild_config(guild_id)
    if not cfg or not cfg["cargos_lideranca_farm"]:
        return []
    return [int(x.strip()) for x in cfg["cargos_lideranca_farm"].split(",") if x.strip()]

def db_get_permitidos_role_ids(guild_id: str) -> list[int]:
    cfg = db_get_guild_config(guild_id)
    if not cfg:
        return []
    role_ids = [
        int(x.strip())
        for x in (cfg["cargos_permitidos_farm"] or "").split(",")
        if x.strip()
    ]
    if cfg["flanelinha_auto_promote"] and cfg["flanelinha_role_id"]:
        flanelinha_role_id = int(cfg["flanelinha_role_id"])
        if flanelinha_role_id not in role_ids:
            role_ids.append(flanelinha_role_id)
    return role_ids

def db_get_editores_farm_role_ids(guild_id: str) -> list[int]:
    cfg = db_get_guild_config(guild_id)
    if not cfg or not cfg["cargos_editar_farm"]:
        return []
    return [int(x.strip()) for x in cfg["cargos_editar_farm"].split(",") if x.strip()]

def db_all_configured_guilds() -> list[str]:
    """Retorna todos os guild_ids que têm ao menos uma configuração salva."""
    rows = get_conn().execute("SELECT guild_id FROM guild_config").fetchall()
    return [r["guild_id"] for r in rows]


# ── Channel Map (substitui channel_map.json) ──────────────────────────────────

def db_channel_map_get(guild_id: str, user_id: str) -> int | None:
    row = get_conn().execute(
        "SELECT channel_id FROM channel_map WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()
    return int(row["channel_id"]) if row else None

def db_channel_map_set(guild_id: str, user_id: str, channel_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO channel_map (guild_id, user_id, channel_id)
        VALUES (?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET channel_id=excluded.channel_id
    """, (guild_id, user_id, str(channel_id)))
    conn.commit()

def db_channel_map_delete(guild_id: str, user_id: str):
    conn = get_conn()
    conn.execute(
        "DELETE FROM channel_map WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    )
    conn.commit()

def db_channel_map_all(guild_id: str) -> list[tuple[str, int]]:
    """Retorna todas as entradas (user_id, channel_id) de uma guild."""
    rows = get_conn().execute(
        "SELECT user_id, channel_id FROM channel_map WHERE guild_id=?", (guild_id,)
    ).fetchall()
    return [(r["user_id"], int(r["channel_id"])) for r in rows]


# ── Ausências (substitui ausencias.json) ──────────────────────────────────────

def db_ausencia_get(guild_id: str, user_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM ausencias WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()

def db_ausencia_set(guild_id: str, user_id: str, dados: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO ausencias (guild_id, user_id, nome, dias, motivo, inicio, fim, avisado, message_id)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            nome=excluded.nome, dias=excluded.dias, motivo=excluded.motivo,
            inicio=excluded.inicio, fim=excluded.fim,
            avisado=excluded.avisado, message_id=excluded.message_id
    """, (
        guild_id, user_id,
        dados.get("nome"), dados.get("dias"), dados.get("motivo"),
        dados.get("inicio"), dados.get("fim"),
        1 if dados.get("avisado") else 0,
        dados.get("message_id"),
    ))
    conn.commit()

def db_ausencias_ativos(guild_id: str) -> list[sqlite3.Row]:
    agora = datetime.utcnow().isoformat()
    return get_conn().execute(
        "SELECT * FROM ausencias WHERE guild_id=? AND fim > ?", (guild_id, agora)
    ).fetchall()

def db_ausencias_todos(guild_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM ausencias WHERE guild_id=?", (guild_id,)
    ).fetchall()

def db_ausencia_marcar_avisado(guild_id: str, user_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE ausencias SET avisado=1 WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    )
    conn.commit()

def db_ausencia_atualizar_message_id(guild_id: str, user_id: str, message_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE ausencias SET message_id=? WHERE guild_id=? AND user_id=?",
        (message_id, guild_id, user_id)
    )
    conn.commit()


# ── Migração de JSON → DB (não-destrutiva) ────────────────────────────────────

def db_migrate_from_json(guild_id: str, channel_map_file: Path, ausencias_file: Path):
    """
    Migra dados existentes de channel_map.json e ausencias.json para o banco.
    Executar uma única vez após o /setup_bot da guild existente.
    Não remove os arquivos JSON originais.
    """
    migrados_cm = 0
    migrados_au = 0

    if channel_map_file.exists():
        try:
            with open(channel_map_file, "r", encoding="utf-8") as f:
                cm = json.load(f)
            for user_id, channel_id in cm.items():
                existing = get_conn().execute(
                    "SELECT 1 FROM channel_map WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id)
                ).fetchone()
                if not existing:
                    db_channel_map_set(guild_id, user_id, int(channel_id))
                    migrados_cm += 1
            log.info(f"Migração channel_map: {migrados_cm} entradas para guild {guild_id}")
        except Exception as e:
            log.error(f"Erro na migração de channel_map.json: {e}")

    if ausencias_file.exists():
        try:
            with open(ausencias_file, "r", encoding="utf-8") as f:
                au = json.load(f)
            for user_id, dados in au.items():
                existing = get_conn().execute(
                    "SELECT 1 FROM ausencias WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id)
                ).fetchone()
                if not existing:
                    db_ausencia_set(guild_id, user_id, dados)
                    migrados_au += 1
            log.info(f"Migração ausências: {migrados_au} entradas para guild {guild_id}")
        except Exception as e:
            log.error(f"Erro na migração de ausencias.json: {e}")

    return migrados_cm, migrados_au


# ── Metas ─────────────────────────────────────────────────────────────────────

def db_get_meta(guild_id: str, week_id: str) -> sqlite3.Row | None:
    """
    Retorna a meta da semana. Se não houver meta cadastrada para week_id,
    busca a meta mais recente disponível (persiste indefinidamente até ser alterada).
    Os lançamentos dos membros zeram normalmente a cada semana.
    """
    meta = get_conn().execute(
        "SELECT * FROM metas WHERE guild_id=? AND week_id=?", (guild_id, week_id)
    ).fetchone()
    if meta is not None:
        return meta
    # Fallback: busca a meta mais recente anterior à semana atual
    return get_conn().execute(
        "SELECT * FROM metas WHERE guild_id=? AND week_id<=? ORDER BY week_id DESC LIMIT 1",
        (guild_id, week_id)
    ).fetchone()

def db_set_meta(
    guild_id: str,
    week_id: str,
    valores: dict,
    definido_por: str,
    meta_tipo: str = "itens",
):
    """
    valores: dict {nome: quantidade}, ex: {"Folha": 500, "Ópio": 300}
    Armazena os itens como JSON. Mantém colunas legadas preenchidas quando
    os nomes coincidem com os itens padrão (para compatibilidade com dados antigos).
    """
    conn = get_conn()
    if meta_tipo not in {"itens", "colete"}:
        raise ValueError(f"Tipo de meta de itens invalido: {meta_tipo}")
    meta_dinheiro = 0
    itens_json = json.dumps(valores, ensure_ascii=False)
    # Popula colunas legadas se os nomes coincidirem (case-insensitive)
    nome_to_key = {v.lower(): k for k, v in _LEGACY_KEY_TO_NOME.items()}
    legacy = {"folha": 0, "opio": 0, "seringa": 0, "agulha": 0}
    for nome, qtd in valores.items():
        key = nome_to_key.get(nome.lower())
        if key:
            legacy[key] = qtd
    conn.execute("""
        INSERT INTO metas (guild_id, week_id, meta_tipo, meta_dinheiro,
                           itens_json, folha, opio, seringa, agulha, definido_por, definido_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id, week_id) DO UPDATE SET
            meta_tipo=excluded.meta_tipo, meta_dinheiro=excluded.meta_dinheiro,
            itens_json=excluded.itens_json,
            folha=excluded.folha, opio=excluded.opio,
            seringa=excluded.seringa, agulha=excluded.agulha,
            definido_por=excluded.definido_por, definido_em=excluded.definido_em
    """, (guild_id, week_id, meta_tipo, meta_dinheiro, itens_json,
          legacy["folha"], legacy["opio"], legacy["seringa"], legacy["agulha"],
          definido_por, now_tz().isoformat()))
    conn.commit()

def db_set_meta_dinheiro(guild_id: str, week_id: str, valores: dict | float, definido_por: str):
    """Salva a meta de dinheiro em R$, com suporte a sujo/limpo separados."""
    conn = get_conn()
    if isinstance(valores, dict):
        dinheiro_itens = {
            nome: float(qtd or 0)
            for nome, qtd in valores.items()
            if nome in DINHEIRO_ITEMS and float(qtd or 0) > 0
        }
        valor = sum(dinheiro_itens.values())
        itens_json = json.dumps(dinheiro_itens, ensure_ascii=False)
    else:
        valor = float(valores or 0)
        itens_json = None
    meta_tipo = "dinheiro"
    legacy = {"folha": 0, "opio": 0, "seringa": 0, "agulha": 0}
    conn.execute("""
        INSERT INTO metas (guild_id, week_id, meta_tipo, meta_dinheiro,
                           itens_json, folha, opio, seringa, agulha, definido_por, definido_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id, week_id) DO UPDATE SET
            meta_tipo=excluded.meta_tipo, meta_dinheiro=excluded.meta_dinheiro,
            itens_json=excluded.itens_json,
            folha=excluded.folha, opio=excluded.opio,
            seringa=excluded.seringa, agulha=excluded.agulha,
            definido_por=excluded.definido_por, definido_em=excluded.definido_em
    """, (guild_id, week_id, meta_tipo, valor, itens_json,
          legacy["folha"], legacy["opio"], legacy["seringa"], legacy["agulha"],
          definido_por, now_tz().isoformat()))
    conn.commit()


# ── Progresso ─────────────────────────────────────────────────────────────────

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

def db_get_ultimo_evento(guild_id: str, week_id: str, user_id: str) -> sqlite3.Row | None:
    return get_conn().execute("""
        SELECT * FROM eventos WHERE guild_id=? AND week_id=? AND user_id=?
        ORDER BY id DESC LIMIT 1
    """, (guild_id, week_id, user_id)).fetchone()

def db_get_evento(guild_id: str, week_id: str, user_id: str, event_id: int) -> sqlite3.Row | None:
    return get_conn().execute("""
        SELECT * FROM eventos
        WHERE id=? AND guild_id=? AND week_id=? AND user_id=?
    """, (event_id, guild_id, week_id, user_id)).fetchone()

def _db_lancar_conn(
    conn: sqlite3.Connection,
    guild_id: str,
    week_id: str,
    user_id: str,
    valores: dict,
) -> tuple[int, str]:
    """Acumula progresso e cria o evento sem realizar commit."""
    agora = now_tz().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO progresso (guild_id, week_id, user_id) VALUES (?,?,?)",
        (guild_id, week_id, user_id),
    )
    prog = conn.execute(
        "SELECT * FROM progresso WHERE guild_id=? AND week_id=? AND user_id=?",
        (guild_id, week_id, user_id),
    ).fetchone()

    # Inicializa itens do progresso: JSON existente, ou migra das colunas fixas
    if prog and prog["itens_prog_json"]:
        itens_atuais = json.loads(prog["itens_prog_json"])
    else:
        itens_atuais = {}
        if prog:
            for key, nome in _LEGACY_KEY_TO_NOME.items():
                val = prog[key] or 0
                if val:
                    itens_atuais[nome] = val

    for nome, qtd in valores.items():
        itens_atuais[nome] = itens_atuais.get(nome, 0) + qtd

    conn.execute("""
        UPDATE progresso SET itens_prog_json=?, ultimo_lancamento_em=?
        WHERE guild_id=? AND week_id=? AND user_id=?
    """, (json.dumps(itens_atuais, ensure_ascii=False), agora, guild_id, week_id, user_id))

    cursor = conn.execute("""
        INSERT INTO eventos (guild_id, week_id, user_id, criado_em, itens_json)
        VALUES (?,?,?,?,?)
    """, (guild_id, week_id, user_id, agora, json.dumps(valores, ensure_ascii=False)))

    return int(cursor.lastrowid), agora


def db_lancar(guild_id: str, week_id: str, user_id: str, valores: dict) -> int:
    """Registra um lançamento normal e retorna o ID do evento criado."""
    conn = get_conn()
    try:
        event_id, _ = _db_lancar_conn(conn, guild_id, week_id, user_id, valores)
        conn.commit()
        return event_id
    except Exception:
        conn.rollback()
        raise

def db_editar_ultimo_evento(guild_id: str, week_id: str, user_id: str, valores: dict) -> bool:
    """valores: dict {nome: novo_total}, ex: {"Folha": 80}"""
    ultimo = db_get_ultimo_evento(guild_id, week_id, user_id)
    if not ultimo:
        return False
    return db_editar_evento(guild_id, week_id, user_id, int(ultimo["id"]), valores)

def db_editar_evento(guild_id: str, week_id: str, user_id: str, event_id: int, valores: dict) -> bool:
    """Edita um lançamento específico e aplica o delta no progresso acumulado."""
    conn = get_conn()
    evento = db_get_evento(guild_id, week_id, user_id, event_id)
    if not evento:
        return False

    old_itens = db_evento_itens(evento)
    prog = db_get_progresso(guild_id, week_id, user_id)

    # Garante que itens_prog_json está inicializado (migra de colunas fixas se necessário)
    if prog and prog["itens_prog_json"]:
        prog_itens = json.loads(prog["itens_prog_json"])
    else:
        prog_itens = {}
        if prog:
            for key, nome in _LEGACY_KEY_TO_NOME.items():
                prog_itens[nome] = prog[key] or 0

    for nome, novo_val in valores.items():
        old_val = old_itens.get(nome, 0)
        delta = novo_val - old_val
        prog_itens[nome] = max(0, prog_itens.get(nome, 0) + delta)

    conn.execute(
        "UPDATE eventos SET itens_json=? WHERE id=?",
        (json.dumps(valores, ensure_ascii=False), event_id)
    )
    conn.execute(
        "UPDATE progresso SET itens_prog_json=? WHERE guild_id=? AND week_id=? AND user_id=?",
        (json.dumps(prog_itens, ensure_ascii=False), guild_id, week_id, user_id)
    )
    conn.commit()
    return True

def db_verificar_conclusao(guild_id: str, week_id: str, user_id: str):
    meta = db_get_meta(guild_id, week_id)
    prog = db_get_progresso(guild_id, week_id, user_id)
    if not meta or not prog:
        return
    if prog["status"] == "concluida":
        return

    meta_tipo = db_meta_tipo_efetivo(meta)
    meta_itens = db_meta_itens_ativos(meta)
    meta_valor = db_meta_dinheiro_ativo(meta)
    meta_dinheiro_itens = db_meta_dinheiro_itens_ativos(meta)
    prog_itens = db_prog_itens(prog)

    if meta_tipo == "dinheiro":
        if meta_valor <= 0:
            return
        if meta_dinheiro_itens:
            concluido = all(
                prog_itens.get(nome, 0) >= qtd
                for nome, qtd in meta_dinheiro_itens.items()
            )
        else:
            concluido = sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS) >= meta_valor
    else:
        if not meta_itens:
            return
        concluido = all(
            prog_itens.get(nome, 0) >= qtd
            for nome, qtd in meta_itens.items()
        )

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
    conn = get_conn()
    conn.execute(
        "UPDATE progresso SET painel_channel_id=NULL, painel_message_id=NULL WHERE guild_id=? AND week_id=? AND user_id=?",
        (guild_id, week_id, user_id)
    )
    conn.commit()

def db_aprovar(
    guild_id: str, week_id: str, user_id: str, aprovador_id: str,
    antecipada: bool = False, nivel: str | None = None,
):
    """
    Aprova a meta de um membro.
    nivel: nível da aprovação antecipada ("elite", "meta_batida", "parcial").
           Quando definido, o membro aparece no ranking/fechamento com esse nível.
    """
    conn = get_conn()
    conn.execute("""
        UPDATE progresso SET aprovada=1, aprovada_por=?, aprovada_em=?,
            aprovacao_antecipada=?, aprovacao_nivel=?
        WHERE guild_id=? AND week_id=? AND user_id=?
    """, (aprovador_id, now_tz().isoformat(), 1 if antecipada else 0, nivel,
          guild_id, week_id, user_id))
    conn.commit()

def db_lista_progresso(guild_id: str, week_id: str) -> list:
    rows = get_conn().execute(
        "SELECT * FROM progresso WHERE guild_id=? AND week_id=?",
        (guild_id, week_id)
    ).fetchall()

    meta = db_get_meta(guild_id, week_id)
    meta_tipo = db_meta_tipo_efetivo(meta)
    meta_itens = db_meta_itens_ativos(meta)

    def _total(row):
        prog_itens = db_prog_itens(row)
        if meta_tipo == "dinheiro":
            return sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
        return sum(prog_itens.get(nome, 0) for nome in meta_itens)

    return sorted(rows, key=_total, reverse=True)

def db_eventos_usuario(guild_id: str, week_id: str, user_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM eventos WHERE guild_id=? AND week_id=? AND user_id=? ORDER BY id ASC",
        (guild_id, week_id, user_id)
    ).fetchall()

def db_ranking_semana(guild_id: str, week_id: str, user_ids: list[str] | None = None) -> list[dict]:
    meta = db_get_meta(guild_id, week_id)
    if not meta:
        return []
    meta_tipo = db_meta_tipo_efetivo(meta)
    meta_itens = db_meta_itens_ativos(meta)
    meta_dinheiro = db_meta_dinheiro_ativo(meta)
    total_meta = (meta_dinheiro if meta_tipo == "dinheiro" else sum(meta_itens.values())) or 1

    rows = get_conn().execute(
        "SELECT * FROM progresso WHERE guild_id=? AND week_id=?",
        (guild_id, week_id)
    ).fetchall()
    rows_by_uid = {str(row["user_id"]): row for row in rows}
    ranking_user_ids = set(rows_by_uid)
    if user_ids:
        ranking_user_ids.update(str(uid) for uid in user_ids)

    # Ordem de classificação para ordenar o ranking
    _ordem = {"elite": 4, "meta_batida": 3, "parcial": 2, "zero": 1}

    result = []
    for user_id in ranking_user_ids:
        row = rows_by_uid.get(str(user_id))
        prog_itens = db_prog_itens(row) if row else {}
        total_itens = sum(prog_itens.get(nome, 0) for nome in meta_itens)
        total_dinheiro = sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
        total_prog = total_dinheiro if meta_tipo == "dinheiro" else total_itens
        pct        = round(total_prog / total_meta * 100, 1)

        # Aprovação antecipada com nível escolhido → usar esse nível diretamente
        if row and row["aprovacao_antecipada"] and row["aprovacao_nivel"]:
            classificacao = row["aprovacao_nivel"]
        elif meta_tipo == "dinheiro":
            meta_dinheiro_itens = db_meta_dinheiro_itens_ativos(meta)
            if meta_dinheiro_itens:
                classificacao = classificar_resultado(meta_dinheiro_itens, prog_itens)
            elif pct >= 130:
                classificacao = "elite"
            elif pct >= 100:
                classificacao = "meta_batida"
            elif total_prog > 0:
                classificacao = "parcial"
            else:
                classificacao = "zero"
        else:
            classificacao = classificar_resultado(meta_itens, prog_itens)

        result.append({
            "user_id":       str(user_id),
            "status":        row["status"] if row else "em_andamento",
            "aprovada":      row["aprovada"] if row else 0,
            "pct":           pct,
            "classificacao": classificacao,
            "total":         total_prog,
        })

    result.sort(key=lambda x: (_ordem.get(x["classificacao"], 0), x["pct"]), reverse=True)
    return result


def db_get_painel_ranking(guild_id: str) -> tuple[str | None, str | None, str | None]:
    row = get_conn().execute(
        "SELECT painel_ranking_channel_id, painel_ranking_message_id, painel_ranking_week_id "
        "FROM guild_config WHERE guild_id=?",
        (guild_id,),
    ).fetchone()
    if not row:
        return None, None, None
    return (
        row["painel_ranking_channel_id"],
        row["painel_ranking_message_id"],
        row["painel_ranking_week_id"],
    )


def db_set_painel_ranking(guild_id: str, channel_id: str, message_id: str, week_id: str):
    db_set_guild_config(
        guild_id,
        painel_ranking_channel_id=channel_id,
        painel_ranking_message_id=message_id,
        painel_ranking_week_id=week_id,
    )


# ── Parcerias ─────────────────────────────────────────────────────────────────

def db_get_parcerias_config(guild_id: str) -> tuple[str | None, str | None, str | None, str | None]:
    row = get_conn().execute(
        """SELECT parceria_category_id, parceria_registrar_channel_id,
                  parceria_ativas_channel_id, parceria_panel_message_id
           FROM guild_config WHERE guild_id=?""",
        (guild_id,),
    ).fetchone()
    if not row:
        return None, None, None, None
    return (
        row["parceria_category_id"],
        row["parceria_registrar_channel_id"],
        row["parceria_ativas_channel_id"],
        row["parceria_panel_message_id"],
    )


def db_set_parcerias_config(
    guild_id: str,
    *,
    category_id: str | None = None,
    registrar_channel_id: str | None = None,
    ativas_channel_id: str | None = None,
    panel_message_id: str | None = None,
) -> None:
    fields = {}
    if category_id is not None:
        fields["parceria_category_id"] = category_id
    if registrar_channel_id is not None:
        fields["parceria_registrar_channel_id"] = registrar_channel_id
    if ativas_channel_id is not None:
        fields["parceria_ativas_channel_id"] = ativas_channel_id
    if panel_message_id is not None:
        fields["parceria_panel_message_id"] = panel_message_id
    if fields:
        db_set_guild_config(guild_id, **fields)


def db_parceria_nome_existe(
    guild_id: str,
    nome_familia: str,
    *,
    exclude_id: int | None = None,
) -> bool:
    params: list[object] = [guild_id, nome_familia.strip()]
    sql = "SELECT 1 FROM parcerias WHERE guild_id=? AND nome_familia=?"
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    return get_conn().execute(sql + " LIMIT 1", params).fetchone() is not None


def db_parceria_criar(
    guild_id: str,
    nome_familia: str,
    produto: str,
    contato_01: str | None,
    contato_02: str | None,
    mensagem_lista_id: int,
    nome_arquivo_imagem: str,
    registrado_por: int,
) -> int:
    conn = get_conn()
    cursor = conn.execute(
        """INSERT INTO parcerias
           (guild_id, nome_familia, produto, contato_01, contato_02,
            mensagem_lista_id, nome_arquivo_imagem, registrado_por)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            guild_id,
            nome_familia.strip(),
            produto.strip(),
            contato_01 or None,
            contato_02 or None,
            mensagem_lista_id,
            nome_arquivo_imagem,
            registrado_por,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def db_parcerias_ativas(guild_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT * FROM parcerias
           WHERE guild_id=? AND ativo=1
           ORDER BY nome_familia COLLATE NOCASE
           LIMIT 25""",
        (guild_id,),
    ).fetchall()


def db_parceria_get(guild_id: str, parceria_id: int) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM parcerias WHERE guild_id=? AND id=?",
        (guild_id, parceria_id),
    ).fetchone()


def db_parceria_atualizar_texto(
    parceria_id: int,
    nome_familia: str,
    produto: str,
    contato_01: str | None,
    contato_02: str | None,
) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE parcerias
           SET nome_familia=?, produto=?, contato_01=?, contato_02=?,
               atualizado_em=?
           WHERE id=?""",
        (
            nome_familia.strip(),
            produto.strip(),
            contato_01 or None,
            contato_02 or None,
            now_tz().isoformat(),
            parceria_id,
        ),
    )
    conn.commit()


def db_parceria_atualizar_imagem(parceria_id: int, nome_arquivo_imagem: str) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE parcerias
           SET nome_arquivo_imagem=?, atualizado_em=?
           WHERE id=?""",
        (nome_arquivo_imagem, now_tz().isoformat(), parceria_id),
    )
    conn.commit()


def db_parceria_desativar(parceria_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE parcerias SET ativo=0, atualizado_em=? WHERE id=?",
        (now_tz().isoformat(), parceria_id),
    )
    conn.commit()


# ── Coletes ───────────────────────────────────────────────────────────────────

def db_get_painel_colete(guild_id: str) -> tuple[str | None, str | None]:
    """Retorna (channel_id, message_id) do painel fixo de coletes."""
    row = get_conn().execute(
        "SELECT painel_colete_channel_id, painel_colete_message_id "
        "FROM guild_config WHERE guild_id=?",
        (guild_id,),
    ).fetchone()
    if not row:
        return None, None
    return row["painel_colete_channel_id"], row["painel_colete_message_id"]


def db_registrar_fabricacao_colete(
    guild_id: str,
    user_id: str,
    user_name: str,
    quantidade: int,
    ferro: int,
    plastico: int,
    tecido: int,
    aluminio: int,
    borracha: int,
    custo: int,
) -> dict:
    conn = get_conn()
    bau_operation_id = f"fabricacao-colete-{uuid.uuid4().hex}"
    cursor = conn.execute(
        """INSERT INTO fabricacoes_colete
           (guild_id, user_id, user_name, quantidade, ferro, plastico,
            tecido, aluminio, borracha, custo, timestamp, bau_operation_id,
            bau_sincronizado)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            guild_id,
            user_id,
            user_name,
            quantidade,
            ferro,
            plastico,
            tecido,
            aluminio,
            borracha,
            custo,
            now_tz().isoformat(),
            bau_operation_id,
        ),
    )
    conn.commit()
    return {
        "id": cursor.lastrowid,
        "guild_id": guild_id,
        "user_id": user_id,
        "user_name": user_name,
        "quantidade": quantidade,
        "bau_operation_id": bau_operation_id,
    }


def db_get_fabricacoes_colete_pendentes(limit: int = 100) -> list[dict]:
    rows = get_conn().execute(
        """SELECT id, guild_id, user_id, user_name, quantidade, bau_operation_id
           FROM fabricacoes_colete
           WHERE bau_operation_id IS NOT NULL AND bau_sincronizado=0
           ORDER BY id
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def db_marcar_fabricacao_colete_sincronizada(fabricacao_id: int) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE fabricacoes_colete
           SET bau_sincronizado=1, bau_sincronizado_em=?
           WHERE id=?""",
        (now_tz().isoformat(), fabricacao_id),
    )
    conn.commit()


# ── Dashboard: system_config ─────────────────────────────────────────────────

def db_get_system_config(guild_id: str, sistema: str):
    return get_conn().execute(
        "SELECT * FROM system_config WHERE guild_id=? AND sistema=?",
        (guild_id, sistema),
    ).fetchone()


def db_set_system_config(
    guild_id: str,
    sistema: str,
    canal_interacao_id: str | None,
    canal_log_id: str | None,
):
    conn = get_conn()
    conn.execute(
        """INSERT INTO system_config (guild_id, sistema, canal_interacao_id, canal_log_id)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(guild_id, sistema) DO UPDATE SET
               canal_interacao_id=excluded.canal_interacao_id,
               canal_log_id=excluded.canal_log_id""",
        (guild_id, sistema, canal_interacao_id, canal_log_id),
    )
    conn.commit()


def db_get_all_system_configs(guild_id: str):
    return get_conn().execute(
        "SELECT * FROM system_config WHERE guild_id=?", (guild_id,),
    ).fetchall()


# ── Recolhimento — Ciclos ─────────────────────────────────────────────────────

def db_recolhimento_ciclo_aberto(guild_id: str, channel_id: str, tipo: str, semana_inicio: str):
    return get_conn().execute(
        "SELECT * FROM recolhimento_ciclos "
        "WHERE guild_id=? AND channel_id=? AND tipo=? AND semana_inicio=? AND encerrado=0",
        (guild_id, channel_id, tipo, semana_inicio),
    ).fetchone()


def db_recolhimento_ciclo_aberto_por_mensagem(
    guild_id: str,
    channel_id: str,
    tipo: str,
    message_id: str,
):
    return get_conn().execute(
        "SELECT * FROM recolhimento_ciclos "
        "WHERE guild_id=? AND channel_id=? AND tipo=? AND message_id=? AND encerrado=0",
        (guild_id, channel_id, tipo, message_id),
    ).fetchone()


def db_recolhimento_criar_ciclo(
    guild_id: str, member_id: str, channel_id: str, tipo: str,
    semana_inicio: str, semana_fim: str,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO recolhimento_ciclos "
        "(guild_id, member_id, channel_id, tipo, semana_inicio, semana_fim) "
        "VALUES (?,?,?,?,?,?)",
        (guild_id, member_id, channel_id, tipo, semana_inicio, semana_fim),
    )
    conn.commit()
    return cur.lastrowid


def db_recolhimento_salvar_message_id(ciclo_id: int, message_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE recolhimento_ciclos SET message_id=? WHERE id=?", (message_id, ciclo_id),
    )
    conn.commit()


def db_recolhimento_get_ciclo(ciclo_id: int):
    return get_conn().execute(
        "SELECT * FROM recolhimento_ciclos WHERE id=?", (ciclo_id,),
    ).fetchone()


def db_recolhimento_marcar_pago(ciclo_id: int, pago_por: str, observacao: str):
    conn = get_conn()
    conn.execute(
        "UPDATE recolhimento_ciclos "
        "SET pago=1, pago_por=?, data_pagamento=?, observacao_pagamento=? WHERE id=?",
        (pago_por, now_tz().isoformat(), observacao, ciclo_id),
    )
    conn.commit()


def db_recolhimento_encerrar(ciclo_id: int):
    conn = get_conn()
    conn.execute("UPDATE recolhimento_ciclos SET encerrado=1 WHERE id=?", (ciclo_id,))
    conn.commit()


def db_recolhimento_ciclos_para_encerrar(semana_fim: str) -> list:
    return get_conn().execute(
        "SELECT * FROM recolhimento_ciclos WHERE semana_fim=? AND encerrado=0", (semana_fim,),
    ).fetchall()


# ── Recolhimento — Entregas ───────────────────────────────────────────────────

def db_recolhimento_add_entrega_dinheiro(
    ciclo_id: int,
    registrado_por: str,
    valor: float,
    alvo_user_id: str | None = None,
    alvo_nome: str | None = None,
    alvo_pasta_id: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO recolhimento_entregas "
        "(ciclo_id, data, registrado_por, alvo_user_id, alvo_nome, alvo_pasta_id, valor) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            ciclo_id,
            now_tz().isoformat(),
            registrado_por,
            alvo_user_id,
            alvo_nome,
            alvo_pasta_id,
            valor,
        ),
    )
    conn.commit()
    return cur.lastrowid


def db_recolhimento_add_entrega_farm(
    ciclo_id: int, registrado_por: str,
    folha: int, opio: int, seringa: int, agulha: int,
    alvo_user_id: str | None = None,
    alvo_nome: str | None = None,
    alvo_pasta_id: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO recolhimento_entregas "
        "(ciclo_id, data, registrado_por, alvo_user_id, alvo_nome, alvo_pasta_id, "
        "folha, opio, seringa, agulha) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ciclo_id,
            now_tz().isoformat(),
            registrado_por,
            alvo_user_id,
            alvo_nome,
            alvo_pasta_id,
            folha,
            opio,
            seringa,
            agulha,
        ),
    )
    conn.commit()
    return cur.lastrowid


def db_recolhimento_add_entrega_itens(
    ciclo_id: int,
    registrado_por: str,
    itens: dict[str, int | float],
    alvo_user_id: str | None = None,
    alvo_nome: str | None = None,
    alvo_pasta_id: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO recolhimento_entregas "
        "(ciclo_id, data, registrado_por, alvo_user_id, alvo_nome, alvo_pasta_id, itens_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            ciclo_id,
            now_tz().isoformat(),
            registrado_por,
            alvo_user_id,
            alvo_nome,
            alvo_pasta_id,
            json.dumps(itens, ensure_ascii=False),
        ),
    )
    conn.commit()
    return cur.lastrowid


def db_recolhimento_entrega_itens(entrega) -> dict:
    itens_json = entrega["itens_json"] if "itens_json" in entrega.keys() else None
    if itens_json:
        return json.loads(itens_json)
    if entrega["valor"]:
        return {"Dinheiro": entrega["valor"]}
    return {
        nome: entrega[key] or 0
        for key, nome in {
            "folha": "Borracha",
            "opio": "Aluminio",
            "seringa": "Cobre",
            "agulha": "Plastico",
        }.items()
        if entrega[key]
    }


def db_recolhimento_get_entregas(ciclo_id: int) -> list:
    return get_conn().execute(
        "SELECT * FROM recolhimento_entregas WHERE ciclo_id=? ORDER BY id ASC", (ciclo_id,),
    ).fetchall()


# Lideranca - Pendencias

def db_lideranca_criar_pendencia(
    guild_id: str,
    titulo: str,
    descricao: str,
    categoria: str,
    prioridade: str,
    prazo: str,
    criado_por_id: str,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO lideranca_pendencias
           (guild_id, titulo, descricao, categoria, prioridade, status,
            criado_por_id, criado_em, prazo)
           VALUES (?, ?, ?, ?, ?, 'aberta', ?, ?, ?)""",
        (
            guild_id,
            titulo,
            descricao,
            categoria,
            prioridade,
            criado_por_id,
            now_tz().isoformat(),
            prazo,
        ),
    )
    conn.commit()
    return cur.lastrowid


def db_lideranca_get_pendencia(guild_id: str, pendencia_id: int):
    return get_conn().execute(
        "SELECT * FROM lideranca_pendencias WHERE guild_id=? AND id=?",
        (guild_id, pendencia_id),
    ).fetchone()


def db_lideranca_listar_pendencias(
    guild_id: str,
    status: tuple[str, ...] = ("aberta", "em_andamento"),
    responsavel_id: str | None = None,
    limit: int = 10,
) -> list:
    params: list = [guild_id]
    where = ["guild_id=?"]

    if status:
        placeholders = ",".join("?" for _ in status)
        where.append(f"status IN ({placeholders})")
        params.extend(status)

    if responsavel_id is not None:
        where.append("responsavel_id=?")
        params.append(responsavel_id)

    params.append(limit)
    return get_conn().execute(
        f"""SELECT * FROM lideranca_pendencias
            WHERE {' AND '.join(where)}
            ORDER BY
                CASE prioridade
                    WHEN 'urgente' THEN 0
                    WHEN 'alta' THEN 1
                    WHEN 'media' THEN 2
                    WHEN 'baixa' THEN 3
                    ELSE 4
                END,
                id DESC
            LIMIT ?""",
        params,
    ).fetchall()


def db_lideranca_assumir_pendencia(guild_id: str, pendencia_id: int, responsavel_id: str) -> bool:
    row = db_lideranca_get_pendencia(guild_id, pendencia_id)
    if not row or row["status"] == "concluida":
        return False

    conn = get_conn()
    conn.execute(
        """UPDATE lideranca_pendencias
           SET responsavel_id=?, status='em_andamento'
           WHERE guild_id=? AND id=?""",
        (responsavel_id, guild_id, pendencia_id),
    )
    conn.commit()
    return True


def db_lideranca_concluir_pendencia(guild_id: str, pendencia_id: int, resolvida_por_id: str) -> bool:
    row = db_lideranca_get_pendencia(guild_id, pendencia_id)
    if not row or row["status"] == "concluida":
        return False

    conn = get_conn()
    conn.execute(
        """UPDATE lideranca_pendencias
           SET status='concluida', resolvida_por_id=?, resolvida_em=?
           WHERE guild_id=? AND id=?""",
        (resolvida_por_id, now_tz().isoformat(), guild_id, pendencia_id),
    )
    conn.commit()
    return True


def db_lideranca_resumo(guild_id: str) -> dict:
    rows = get_conn().execute(
        """SELECT status, prioridade, COUNT(*) AS total
           FROM lideranca_pendencias
           WHERE guild_id=?
           GROUP BY status, prioridade""",
        (guild_id,),
    ).fetchall()

    resumo = {
        "abertas": 0,
        "andamento": 0,
        "concluidas": 0,
        "urgentes_abertas": 0,
    }
    for row in rows:
        status = row["status"]
        prioridade = row["prioridade"]
        total = row["total"]
        if status == "aberta":
            resumo["abertas"] += total
            if prioridade == "urgente":
                resumo["urgentes_abertas"] += total
        elif status == "em_andamento":
            resumo["andamento"] += total
        elif status == "concluida":
            resumo["concluidas"] += total
    return resumo


# ── Tickets semanais de farm ─────────────────────────────────────────────────

def db_ticket_config_get(guild_id: str) -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM farm_ticket_config WHERE guild_id=?", (guild_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "guild_id": guild_id,
        "category_ids": json.loads(row["category_ids_json"]),
        "admin_role_ids": json.loads(row["admin_role_ids_json"]),
        "atualizado_em": row["atualizado_em"],
    }


def db_ticket_config_set(guild_id: str, category_ids: list[int], admin_role_ids: list[int]) -> None:
    get_conn().execute(
        """INSERT INTO farm_ticket_config
           (guild_id, category_ids_json, admin_role_ids_json, atualizado_em)
           VALUES (?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
             category_ids_json=excluded.category_ids_json,
             admin_role_ids_json=excluded.admin_role_ids_json,
             atualizado_em=excluded.atualizado_em""",
        (
            guild_id,
            json.dumps([str(x) for x in category_ids]),
            json.dumps([str(x) for x in admin_role_ids]),
            now_tz().isoformat(),
        ),
    )
    get_conn().commit()


def db_farm_report_get(guild_id: str) -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM farm_pending_report WHERE guild_id=?", (guild_id,)
    ).fetchone()
    if not row:
        return None
    try:
        members = json.loads(row["snapshot_members_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        members = []
    return {
        "guild_id": guild_id,
        "channel_id": row["channel_id"],
        "panel_message_id": row["panel_message_id"],
        "report_message_id": row["report_message_id"],
        "snapshot_week_id": row["snapshot_week_id"],
        "snapshot_members": members,
        "snapshot_created_at": row["snapshot_created_at"],
        "atualizado_em": row["atualizado_em"],
    }


def db_farm_report_set_panel(
    guild_id: str,
    channel_id: str,
    panel_message_id: str,
    report_message_id: str | None = None,
) -> None:
    agora = now_tz().isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO farm_pending_report
           (guild_id, channel_id, panel_message_id, report_message_id, atualizado_em)
           VALUES (?,?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
             channel_id=excluded.channel_id,
             panel_message_id=excluded.panel_message_id,
             report_message_id=excluded.report_message_id,
             atualizado_em=excluded.atualizado_em""",
        (guild_id, channel_id, panel_message_id, report_message_id, agora),
    )
    conn.commit()


def db_farm_report_set_report_message(guild_id: str, message_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE farm_pending_report SET report_message_id=?, atualizado_em=? WHERE guild_id=?",
        (message_id, now_tz().isoformat(), guild_id),
    )
    conn.commit()


def db_farm_report_set_snapshot(
    guild_id: str, week_id: str, members: list[dict[str, str]]
) -> None:
    agora = now_tz().isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO farm_pending_report
           (guild_id, snapshot_week_id, snapshot_members_json,
            snapshot_created_at, atualizado_em)
           VALUES (?,?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
             snapshot_week_id=excluded.snapshot_week_id,
             snapshot_members_json=excluded.snapshot_members_json,
             snapshot_created_at=excluded.snapshot_created_at,
             atualizado_em=excluded.atualizado_em""",
        (
            guild_id,
            week_id,
            json.dumps(members, ensure_ascii=False),
            agora,
            agora,
        ),
    )
    conn.commit()


def db_ticket_approved_user_ids(guild_id: str, week_id: str) -> set[str]:
    rows = get_conn().execute(
        """SELECT DISTINCT t.user_id
           FROM farm_tickets t
           JOIN farm_ticket_actions a ON a.ticket_id=t.id
           WHERE t.guild_id=? AND t.week_id=? AND a.action='aprovacao'""",
        (guild_id, week_id),
    ).fetchall()
    return {str(row["user_id"]) for row in rows}


def db_ticket_get(ticket_id: int):
    return get_conn().execute(
        "SELECT * FROM farm_tickets WHERE id=?", (ticket_id,)
    ).fetchone()


def db_ticket_get_week(guild_id: str, week_id: str, user_id: str):
    return get_conn().execute(
        """SELECT * FROM farm_tickets
           WHERE guild_id=? AND week_id=? AND user_id=?
             AND status IN ('criando','aberto','revisao')
           ORDER BY id DESC LIMIT 1""",
        (guild_id, week_id, user_id),
    ).fetchone()


def db_ticket_get_channel(guild_id: str, channel_id: str):
    return get_conn().execute(
        "SELECT * FROM farm_tickets WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ).fetchone()


def db_ticket_list_week(guild_id: str, week_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM farm_tickets WHERE guild_id=? AND week_id=? AND excluido_em IS NULL",
        (guild_id, week_id),
    ).fetchall()


def db_ticket_active() -> list[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM farm_tickets WHERE status IN ('aberto','revisao') AND excluido_em IS NULL"
    ).fetchall()


def db_ticket_list_existing(guild_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT * FROM farm_tickets
           WHERE guild_id=? AND channel_id IS NOT NULL AND excluido_em IS NULL
           ORDER BY week_id DESC, id DESC""",
        (guild_id,),
    ).fetchall()


def db_ticket_expired(current_week: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT * FROM farm_tickets
           WHERE week_id < ? AND status IN ('aberto','revisao') AND excluido_em IS NULL""",
        (current_week,),
    ).fetchall()


def db_ticket_has_pending_logs(ticket_id: int) -> bool:
    return get_conn().execute(
        "SELECT 1 FROM farm_ticket_actions WHERE ticket_id=? AND log_enviado_em IS NULL LIMIT 1",
        (ticket_id,),
    ).fetchone() is not None


def db_ticket_reserve(
    guild_id: str,
    week_id: str,
    user_id: str,
    member_name: str,
    *,
    folder_channel_id: str | None = None,
    folder_slot: int | None = None,
    game_id: str | None = None,
    folder_nickname: str | None = None,
):
    """Reserva um ticket se o membro ainda não tiver outro ativo na semana."""
    conn = get_conn()
    agora = now_tz().isoformat()
    cursor = conn.execute(
        """INSERT OR IGNORE INTO farm_tickets
           (guild_id, week_id, user_id, member_name, folder_channel_id,
            folder_slot, game_id, folder_nickname, status, criado_em, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            guild_id, week_id, user_id, member_name, folder_channel_id,
            folder_slot, game_id, folder_nickname, "criando", agora, agora,
        ),
    )
    conn.commit()
    return db_ticket_get_week(guild_id, week_id, user_id), cursor.rowcount == 1


def db_ticket_activate(ticket_id: int, channel_id: str, message_id: str) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE farm_tickets SET channel_id=?, panel_message_id=?, status='aberto',
           atualizado_em=? WHERE id=?""",
        (channel_id, message_id, now_tz().isoformat(), ticket_id),
    )
    conn.commit()


def db_ticket_release_failed(ticket_id: int) -> None:
    """Remove somente uma reserva que nunca chegou a criar canal ou lançamentos."""
    conn = get_conn()
    conn.execute(
        """DELETE FROM farm_tickets WHERE id=? AND status='criando' AND channel_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM farm_ticket_lancamentos WHERE ticket_id=?)""",
        (ticket_id, ticket_id),
    )
    conn.commit()


def db_ticket_add_action(
    ticket_id: int,
    action: str,
    actor_id: str,
    *,
    event_id: int | None = None,
    payload: dict | None = None,
) -> int:
    conn = get_conn()
    cursor = conn.execute(
        """INSERT INTO farm_ticket_actions
           (ticket_id, action, actor_id, event_id, payload_json, criado_em)
           VALUES (?,?,?,?,?,?)""",
        (
            ticket_id, action, actor_id, event_id,
            json.dumps(payload or {}, ensure_ascii=False), now_tz().isoformat(),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def db_ticket_launch(
    ticket_id: int,
    actor_id: str,
    valores: dict,
    proof_channel_id: str,
    proof_message_id: str,
    proof_url: str,
    observacao: str | None,
) -> tuple[int, int]:
    """Cria evento, vínculo e auditoria na mesma transação."""
    conn = get_conn()
    ticket = db_ticket_get(ticket_id)
    if not ticket or ticket["status"] not in {"aberto", "revisao"}:
        raise ValueError("Ticket não está aberto para lançamentos.")
    try:
        event_id, agora = _db_lancar_conn(
            conn, ticket["guild_id"], ticket["week_id"], ticket["user_id"], valores
        )
        conn.execute(
            """INSERT INTO farm_ticket_lancamentos
               (event_id, ticket_id, proof_channel_id, proof_message_id, proof_url,
                observacao, status, criado_em)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                event_id, ticket_id, proof_channel_id, proof_message_id, proof_url,
                observacao, "registrado", agora,
            ),
        )
        action = conn.execute(
            """INSERT INTO farm_ticket_actions
               (ticket_id, action, actor_id, event_id, payload_json, criado_em)
               VALUES (?,?,?,?,?,?)""",
            (
                ticket_id, "lancamento", actor_id, event_id,
                json.dumps({"valores": valores, "observacao": observacao}, ensure_ascii=False),
                agora,
            ),
        )
        conn.execute(
            "UPDATE farm_tickets SET atualizado_em=? WHERE id=?", (agora, ticket_id)
        )
        conn.commit()
        return event_id, int(action.lastrowid)
    except Exception:
        conn.rollback()
        raise


def db_ticket_launches(ticket_id: int) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT e.*, l.ticket_id, l.proof_channel_id, l.proof_message_id,
                  l.proof_url, l.log_proof_url, l.observacao,
                  l.status AS ticket_status, l.revisado_por, l.revisado_em,
                  l.revisao_motivo
           FROM farm_ticket_lancamentos l
           JOIN eventos e ON e.id=l.event_id
           WHERE l.ticket_id=? ORDER BY e.id ASC""",
        (ticket_id,),
    ).fetchall()


def db_ticket_set_log_result(
    action_id: int,
    *,
    message_id: str | None = None,
    event_id: int | None = None,
    proof_url: str | None = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE farm_ticket_actions SET log_enviado_em=?, log_message_id=?,
           tentativas_log=tentativas_log+1 WHERE id=?""",
        (now_tz().isoformat(), message_id, action_id),
    )
    if event_id and proof_url:
        conn.execute(
            "UPDATE farm_ticket_lancamentos SET log_proof_url=? WHERE event_id=?",
            (proof_url, event_id),
        )
    conn.commit()


def db_ticket_mark_log_attempt(action_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE farm_ticket_actions SET tentativas_log=tentativas_log+1 WHERE id=?",
        (action_id,),
    )
    conn.commit()


def db_ticket_pending_actions(limit: int = 50) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT a.*, t.guild_id, t.channel_id, t.user_id, t.week_id
           FROM farm_ticket_actions a JOIN farm_tickets t ON t.id=a.ticket_id
           WHERE a.log_enviado_em IS NULL ORDER BY a.id ASC LIMIT ?""",
        (limit,),
    ).fetchall()


def db_ticket_latest_action(ticket_id: int, action: str):
    return get_conn().execute(
        """SELECT * FROM farm_ticket_actions
           WHERE ticket_id=? AND action=? ORDER BY id DESC LIMIT 1""",
        (ticket_id, action),
    ).fetchone()


def db_ticket_claim(ticket_id: int, admin_id: str) -> bool:
    conn = get_conn()
    agora = now_tz().isoformat()
    cursor = conn.execute(
        """UPDATE farm_tickets SET assigned_to=?, atualizado_em=?
           WHERE id=? AND assigned_to IS NULL AND status IN ('aberto','revisao')""",
        (admin_id, agora, ticket_id),
    )
    conn.commit()
    return cursor.rowcount == 1


def db_ticket_set_review(ticket_id: int, event_id: int, admin_id: str, motivo: str) -> None:
    conn = get_conn()
    agora = now_tz().isoformat()
    conn.execute(
        """UPDATE farm_ticket_lancamentos SET status='revisao', revisado_por=?,
           revisado_em=?, revisao_motivo=? WHERE ticket_id=? AND event_id=?""",
        (admin_id, agora, motivo, ticket_id, event_id),
    )
    conn.execute(
        "UPDATE farm_tickets SET status='revisao', atualizado_em=? WHERE id=?",
        (agora, ticket_id),
    )
    conn.commit()


def db_ticket_resolve_review(ticket_id: int, event_id: int, admin_id: str) -> None:
    conn = get_conn()
    agora = now_tz().isoformat()
    conn.execute(
        """UPDATE farm_ticket_lancamentos SET status='revisado', revisado_por=?,
           revisado_em=? WHERE ticket_id=? AND event_id=?""",
        (admin_id, agora, ticket_id, event_id),
    )
    pending = conn.execute(
        "SELECT 1 FROM farm_ticket_lancamentos WHERE ticket_id=? AND status='revisao'",
        (ticket_id,),
    ).fetchone()
    if not pending:
        conn.execute(
            "UPDATE farm_tickets SET status='aberto', atualizado_em=? WHERE id=?",
            (agora, ticket_id),
        )
    conn.commit()


def db_ticket_mark_corrected(ticket_id: int, event_id: int, admin_id: str, motivo: str) -> None:
    conn = get_conn()
    agora = now_tz().isoformat()
    conn.execute(
        """UPDATE farm_ticket_lancamentos SET status='corrigido', revisado_por=?,
           revisado_em=?, revisao_motivo=? WHERE ticket_id=? AND event_id=?""",
        (admin_id, agora, motivo, ticket_id, event_id),
    )
    pending = conn.execute(
        "SELECT 1 FROM farm_ticket_lancamentos WHERE ticket_id=? AND status='revisao'",
        (ticket_id,),
    ).fetchone()
    if not pending:
        conn.execute(
            "UPDATE farm_tickets SET status='aberto', atualizado_em=? WHERE id=?",
            (agora, ticket_id),
        )
    conn.commit()


def db_ticket_recalculate_completion(ticket_id: int) -> None:
    """Reabre somente o progresso ligado ao ticket antes de recalcular a meta."""
    ticket = db_ticket_get(ticket_id)
    if not ticket:
        return
    conn = get_conn()
    conn.execute(
        """UPDATE progresso SET status='em_andamento', concluida_em=NULL
           WHERE guild_id=? AND week_id=? AND user_id=?""",
        (ticket["guild_id"], ticket["week_id"], ticket["user_id"]),
    )
    conn.commit()
    db_verificar_conclusao(ticket["guild_id"], ticket["week_id"], ticket["user_id"])


def db_ticket_finalize(ticket_id: int, admin_id: str, motivo: str | None) -> bool:
    conn = get_conn()
    agora = now_tz().isoformat()
    cursor = conn.execute(
        """UPDATE farm_tickets SET status='finalizado', finalizado_em=?,
           finalizado_por=?, finalizacao_motivo=?, atualizado_em=?
           WHERE id=? AND status IN ('aberto','revisao')""",
        (agora, admin_id, motivo, agora, ticket_id),
    )
    conn.commit()
    return cursor.rowcount == 1


def db_ticket_deletion_candidates(current_week: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT t.* FROM farm_tickets t
           WHERE t.status='finalizado' AND t.excluido_em IS NULL AND t.week_id < ?
             AND NOT EXISTS (
               SELECT 1 FROM farm_ticket_actions a
               WHERE a.ticket_id=t.id AND a.log_enviado_em IS NULL
             )""",
        (current_week,),
    ).fetchall()


def db_ticket_mark_deleted(ticket_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE farm_tickets SET excluido_em=?, channel_id=NULL WHERE id=?",
        (now_tz().isoformat(), ticket_id),
    )
    conn.commit()


def db_ticket_mark_manual_deleted(ticket_id: int, admin_id: str, reason: str) -> None:
    conn = get_conn()
    agora = now_tz().isoformat()
    conn.execute(
        """UPDATE farm_tickets SET status='finalizado', finalizado_em=COALESCE(finalizado_em, ?),
           finalizado_por=COALESCE(finalizado_por, ?),
           finalizacao_motivo=COALESCE(finalizacao_motivo, ?),
           excluido_em=?, channel_id=NULL, atualizado_em=? WHERE id=?""",
        (agora, admin_id, reason, agora, agora, ticket_id),
    )
    conn.commit()
