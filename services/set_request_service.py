"""
services/set_request_service.py - Solicitações de set persistidas no SQLite.

Antes o estado de cada pedido (quem pediu, nome, ID do jogo) ficava só na
memória da view de aprovação e se perdia a cada restart do bot. Agora cada
pedido é uma linha em set_solicitacoes e os botões carregam apenas o id.

Estados: pendente → processando → aprovado | reprovado.
"processando" é um "trava" atômica: só um clique consegue sair de pendente.
"""

from __future__ import annotations

import sqlite3

from services.db_service import get_conn, now_tz

PENDENTE = "pendente"
PROCESSANDO = "processando"
APROVADO = "aprovado"
REPROVADO = "reprovado"


def criar_solicitacao(guild_id: str, user_id: str, nome: str, id_jogo: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO set_solicitacoes (guild_id, user_id, nome, id_jogo, status, criado_em) "
        "VALUES (?,?,?,?,?,?)",
        (guild_id, user_id, nome, id_jogo, PENDENTE, now_tz().isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def salvar_mensagem(solicitacao_id: int, channel_id: str, message_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE set_solicitacoes SET channel_id=?, message_id=? WHERE id=?",
        (channel_id, message_id, solicitacao_id),
    )
    conn.commit()


def excluir_solicitacao(solicitacao_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM set_solicitacoes WHERE id=? AND status=?", (solicitacao_id, PENDENTE))
    conn.commit()


def get_solicitacao(solicitacao_id: int) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM set_solicitacoes WHERE id=?", (solicitacao_id,),
    ).fetchone()


def get_por_mensagem(guild_id: str, message_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM set_solicitacoes WHERE guild_id=? AND message_id=? ORDER BY id DESC LIMIT 1",
        (guild_id, message_id),
    ).fetchone()


def pendente_do_usuario(guild_id: str, user_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM set_solicitacoes WHERE guild_id=? AND user_id=? AND status IN (?, ?) "
        "ORDER BY id DESC LIMIT 1",
        (guild_id, user_id, PENDENTE, PROCESSANDO),
    ).fetchone()


def reservar(solicitacao_id: int, por: str) -> bool:
    """Tenta assumir o pedido para decisão. Só um clique vence."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE set_solicitacoes SET status=?, decidido_por=? WHERE id=? AND status=?",
        (PROCESSANDO, por, solicitacao_id, PENDENTE),
    )
    conn.commit()
    return cur.rowcount > 0


def liberar(solicitacao_id: int) -> None:
    """Devolve o pedido para pendente (ex.: erro no meio do processamento)."""
    conn = get_conn()
    conn.execute(
        "UPDATE set_solicitacoes SET status=?, decidido_por=NULL WHERE id=? AND status=?",
        (PENDENTE, solicitacao_id, PROCESSANDO),
    )
    conn.commit()


def concluir(solicitacao_id: int, status: str, por: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE set_solicitacoes SET status=?, decidido_por=?, decidido_em=? WHERE id=?",
        (status, por, now_tz().isoformat(), solicitacao_id),
    )
    conn.commit()
