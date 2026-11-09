"""
services/acao_service.py - Ações e inscritos persistidos no SQLite.

Antes a lista de inscritos ficava só na memória da view e se perdia a cada
restart; e duas ações abertas ao mesmo tempo compartilhavam o estado.
Agora cada ação é uma linha em `acoes`, identificada pela mensagem do painel.
"""

from __future__ import annotations

import sqlite3

from services.db_service import get_conn, now_tz

ABERTA = "aberta"
ENCERRADA = "encerrada"


def criar_acao(
    guild_id: str,
    channel_id: str,
    acao_key: str,
    criado_por: str,
    data: str | None,
    horario: str | None,
    tipo: str | None,
    message_id: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO acoes (guild_id, channel_id, message_id, acao_key, data, horario, tipo, "
        "status, criado_por, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (guild_id, channel_id, message_id, acao_key, data, horario, tipo, ABERTA,
         criado_por, now_tz().isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def salvar_mensagem(acao_id: int, channel_id: str, message_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE acoes SET channel_id=?, message_id=? WHERE id=?", (channel_id, message_id, acao_id),
    )
    conn.commit()


def excluir_acao(acao_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM acao_inscritos WHERE acao_id=?", (acao_id,))
    conn.execute("DELETE FROM acoes WHERE id=?", (acao_id,))
    conn.commit()


def get_acao(acao_id: int) -> sqlite3.Row | None:
    return get_conn().execute("SELECT * FROM acoes WHERE id=?", (acao_id,)).fetchone()


def get_por_mensagem(message_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM acoes WHERE message_id=?", (message_id,),
    ).fetchone()


def inscritos(acao_id: int) -> list[str]:
    rows = get_conn().execute(
        "SELECT user_id FROM acao_inscritos WHERE acao_id=? ORDER BY inscrito_em, rowid",
        (acao_id,),
    ).fetchall()
    return [r["user_id"] for r in rows]


def inscrever(acao_id: int, user_id: str, por: str, maximo: int | None) -> str:
    """Inscreve com checagem de vaga numa transação.

    Retorna "ok", "ja_inscrito", "lotada" ou "encerrada".
    """
    conn = get_conn()
    if conn.in_transaction:
        conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        acao = conn.execute("SELECT status FROM acoes WHERE id=?", (acao_id,)).fetchone()
        if acao is None or acao["status"] != ABERTA:
            conn.rollback()
            return "encerrada"
        existe = conn.execute(
            "SELECT 1 FROM acao_inscritos WHERE acao_id=? AND user_id=?", (acao_id, user_id),
        ).fetchone()
        if existe:
            conn.rollback()
            return "ja_inscrito"
        if maximo:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM acao_inscritos WHERE acao_id=?", (acao_id,),
            ).fetchone()["n"]
            if total >= maximo:
                conn.rollback()
                return "lotada"
        conn.execute(
            "INSERT INTO acao_inscritos (acao_id, user_id, adicionado_por, inscrito_em) VALUES (?,?,?,?)",
            (acao_id, user_id, por, now_tz().isoformat()),
        )
        conn.commit()
        return "ok"
    except Exception:
        conn.rollback()
        raise


def remover(acao_id: int, user_id: str) -> str:
    """Retorna "ok", "nao_inscrito" ou "encerrada"."""
    conn = get_conn()
    acao = get_acao(acao_id)
    if acao is None or acao["status"] != ABERTA:
        return "encerrada"
    cur = conn.execute(
        "DELETE FROM acao_inscritos WHERE acao_id=? AND user_id=?", (acao_id, user_id),
    )
    conn.commit()
    return "ok" if cur.rowcount else "nao_inscrito"


def encerrar(acao_id: int, por: str) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE acoes SET status=?, encerrado_por=?, encerrado_em=? WHERE id=? AND status=?",
        (ENCERRADA, por, now_tz().isoformat(), acao_id, ABERTA),
    )
    conn.commit()
    return cur.rowcount > 0
