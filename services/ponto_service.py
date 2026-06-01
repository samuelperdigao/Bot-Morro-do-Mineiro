"""Persistencia do sistema de ponto."""

from __future__ import annotations

from datetime import datetime

import sqlite3

from services.db_service import current_week_id, get_conn, now_tz

STATUS_ABERTO = "aberto"
STATUS_FECHADO = "fechado"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ponto_get_config(guild_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM ponto_config WHERE guild_id=?", (guild_id,),
    ).fetchone()


def ponto_set_config(
    guild_id: str,
    ponto_category_id: str,
    log_category_id: str,
    painel_channel_id: str,
    log_channel_id: str,
    ranking_channel_id: str,
    ranking_message_id: str | None,
    ranking_week_id: str | None,
) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO ponto_config (
               guild_id, ponto_category_id, log_category_id, painel_channel_id,
               log_channel_id, ranking_channel_id, ranking_message_id, ranking_week_id
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET
               ponto_category_id=excluded.ponto_category_id,
               log_category_id=excluded.log_category_id,
               painel_channel_id=excluded.painel_channel_id,
               log_channel_id=excluded.log_channel_id,
               ranking_channel_id=excluded.ranking_channel_id,
               ranking_message_id=excluded.ranking_message_id,
               ranking_week_id=excluded.ranking_week_id""",
        (
            guild_id,
            ponto_category_id,
            log_category_id,
            painel_channel_id,
            log_channel_id,
            ranking_channel_id,
            ranking_message_id,
            ranking_week_id,
        ),
    )
    conn.commit()


def ponto_atualizar_ranking_message(
    guild_id: str,
    ranking_channel_id: str,
    ranking_message_id: str,
    ranking_week_id: str,
) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE ponto_config
           SET ranking_channel_id=?, ranking_message_id=?, ranking_week_id=?
           WHERE guild_id=?""",
        (ranking_channel_id, ranking_message_id, ranking_week_id, guild_id),
    )
    conn.commit()


def ponto_get_aberto(guild_id: str, user_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        """SELECT * FROM ponto_sessoes
           WHERE guild_id=? AND user_id=? AND status=?
           ORDER BY id DESC LIMIT 1""",
        (guild_id, user_id, STATUS_ABERTO),
    ).fetchone()


def ponto_abrir(guild_id: str, user_id: str, observacao: str | None = None) -> sqlite3.Row:
    conn = get_conn()
    aberto = ponto_get_aberto(guild_id, user_id)
    if aberto:
        return aberto

    cur = conn.execute(
        """INSERT INTO ponto_sessoes
           (guild_id, week_id, user_id, entrada_em, observacao_entrada, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            guild_id,
            current_week_id(),
            user_id,
            now_tz().isoformat(),
            observacao,
            STATUS_ABERTO,
        ),
    )
    conn.commit()
    return ponto_get_sessao(cur.lastrowid)


def ponto_get_sessao(sessao_id: int) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM ponto_sessoes WHERE id=?", (sessao_id,),
    ).fetchone()


def ponto_fechar(
    guild_id: str,
    user_id: str,
    observacao: str | None = None,
    fechado_por: str | None = None,
) -> sqlite3.Row | None:
    conn = get_conn()
    aberto = ponto_get_aberto(guild_id, user_id)
    if not aberto:
        return None

    saida = now_tz()
    entrada = _parse_dt(aberto["entrada_em"])
    duracao = max(int((saida - entrada).total_seconds()), 0)

    conn.execute(
        """UPDATE ponto_sessoes
           SET saida_em=?, duracao_segundos=?, observacao_saida=?,
               fechado_por=?, status=?
           WHERE id=?""",
        (
            saida.isoformat(),
            duracao,
            observacao,
            fechado_por,
            STATUS_FECHADO,
            aberto["id"],
        ),
    )
    conn.commit()
    return ponto_get_sessao(aberto["id"])


def ponto_total_usuario_semana(guild_id: str, week_id: str, user_id: str) -> int:
    row = get_conn().execute(
        """SELECT COALESCE(SUM(duracao_segundos), 0) AS total
           FROM ponto_sessoes
           WHERE guild_id=? AND week_id=? AND user_id=? AND status=?""",
        (guild_id, week_id, user_id, STATUS_FECHADO),
    ).fetchone()
    return int(row["total"] or 0)


def ponto_sessoes_usuario_semana(guild_id: str, week_id: str, user_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT * FROM ponto_sessoes
           WHERE guild_id=? AND week_id=? AND user_id=?
           ORDER BY id DESC""",
        (guild_id, week_id, user_id),
    ).fetchall()


def ponto_ranking_semana(guild_id: str, week_id: str, limit: int = 25) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT user_id,
                  COUNT(*) AS sessoes,
                  COALESCE(SUM(duracao_segundos), 0) AS total_segundos
           FROM ponto_sessoes
           WHERE guild_id=? AND week_id=? AND status=?
           GROUP BY user_id
           HAVING total_segundos > 0
           ORDER BY total_segundos DESC, sessoes DESC
           LIMIT ?""",
        (guild_id, week_id, STATUS_FECHADO, limit),
    ).fetchall()


def ponto_sessoes_abertas(guild_id: str) -> list[sqlite3.Row]:
    return get_conn().execute(
        """SELECT * FROM ponto_sessoes
           WHERE guild_id=? AND status=?
           ORDER BY entrada_em ASC""",
        (guild_id, STATUS_ABERTO),
    ).fetchall()


def ponto_resumo_semana(guild_id: str, week_id: str) -> dict[str, int]:
    conn = get_conn()
    fechadas = conn.execute(
        """SELECT COUNT(*) AS sessoes,
                  COUNT(DISTINCT user_id) AS usuarios,
                  COALESCE(SUM(duracao_segundos), 0) AS total_segundos
           FROM ponto_sessoes
           WHERE guild_id=? AND week_id=? AND status=?""",
        (guild_id, week_id, STATUS_FECHADO),
    ).fetchone()
    abertas = conn.execute(
        "SELECT COUNT(*) AS total FROM ponto_sessoes WHERE guild_id=? AND status=?",
        (guild_id, STATUS_ABERTO),
    ).fetchone()
    return {
        "sessoes": int(fechadas["sessoes"] or 0),
        "usuarios": int(fechadas["usuarios"] or 0),
        "total_segundos": int(fechadas["total_segundos"] or 0),
        "abertas": int(abertas["total"] or 0),
    }
