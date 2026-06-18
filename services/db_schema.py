"""Schema e migracoes do SQLite."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id               TEXT PRIMARY KEY,
    approval_channel_id    TEXT,
    log_channel_id         TEXT,
    private_category_id    TEXT,
    member_role_id         TEXT,
    approver_role_ids      TEXT,
    canal_ausencias_id     TEXT,
    cargos_lideranca_farm  TEXT,
    cargos_permitidos_farm TEXT,
    canal_avisos_farm      TEXT,
    canal_notificacao_farm TEXT,
    flanelinha_role_id     TEXT,
    flanelinha_auto_promote INTEGER DEFAULT 0,
    flanelinha_notify_user_id TEXT
);

CREATE TABLE IF NOT EXISTS channel_map (
    guild_id   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS ausencias (
    guild_id   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    nome       TEXT,
    dias       INTEGER,
    motivo     TEXT,
    inicio     TEXT,
    fim        TEXT,
    avisado    INTEGER DEFAULT 0,
    message_id TEXT,
    PRIMARY KEY (guild_id, user_id)
);

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

CREATE TABLE IF NOT EXISTS fabricacoes_colete (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    user_name  TEXT NOT NULL,
    quantidade INTEGER NOT NULL,
    ferro      INTEGER NOT NULL,
    plastico   INTEGER NOT NULL,
    tecido     INTEGER NOT NULL,
    aluminio   INTEGER NOT NULL,
    borracha   INTEGER NOT NULL,
    custo      INTEGER NOT NULL,
    timestamp  TEXT NOT NULL,
    bau_operation_id TEXT,
    bau_sincronizado INTEGER DEFAULT 0,
    bau_sincronizado_em TEXT
);

CREATE TABLE IF NOT EXISTS system_config (
    guild_id           TEXT NOT NULL,
    sistema            TEXT NOT NULL,
    canal_interacao_id TEXT,
    canal_log_id       TEXT,
    PRIMARY KEY (guild_id, sistema)
);

CREATE TABLE IF NOT EXISTS recolhimento_ciclos (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id             TEXT NOT NULL,
    member_id            TEXT NOT NULL,
    channel_id           TEXT NOT NULL,
    message_id           TEXT,
    tipo                 TEXT NOT NULL,
    semana_inicio        TEXT NOT NULL,
    semana_fim           TEXT NOT NULL,
    pago                 INTEGER DEFAULT 0,
    pago_por             TEXT,
    data_pagamento       TEXT,
    observacao_pagamento TEXT,
    encerrado            INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recolhimento_entregas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ciclo_id       INTEGER NOT NULL,
    data           TEXT NOT NULL,
    registrado_por TEXT NOT NULL,
    alvo_user_id   TEXT,
    alvo_nome      TEXT,
    alvo_pasta_id  TEXT,
    valor          REAL,
    folha          INTEGER,
    opio           INTEGER,
    seringa        INTEGER,
    agulha         INTEGER
);

CREATE TABLE IF NOT EXISTS lideranca_pendencias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        TEXT NOT NULL,
    titulo          TEXT NOT NULL,
    descricao       TEXT,
    categoria       TEXT,
    prioridade      TEXT,
    status          TEXT DEFAULT 'aberta',
    responsavel_id  TEXT,
    criado_por_id   TEXT NOT NULL,
    criado_em       TEXT NOT NULL,
    prazo           TEXT,
    resolvida_por_id TEXT,
    resolvida_em    TEXT
);

CREATE INDEX IF NOT EXISTS idx_lideranca_pendencias_guild_status
ON lideranca_pendencias (guild_id, status);

CREATE TABLE IF NOT EXISTS farm_ticket_config (
    guild_id               TEXT PRIMARY KEY,
    category_ids_json      TEXT NOT NULL,
    admin_role_ids_json    TEXT NOT NULL,
    atualizado_em          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_tickets (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id               TEXT NOT NULL,
    week_id                TEXT NOT NULL,
    user_id                TEXT NOT NULL,
    member_name            TEXT NOT NULL,
    channel_id             TEXT,
    panel_message_id       TEXT,
    status                 TEXT NOT NULL DEFAULT 'criando',
    assigned_to            TEXT,
    criado_em              TEXT NOT NULL,
    atualizado_em          TEXT NOT NULL,
    finalizado_em          TEXT,
    finalizado_por         TEXT,
    finalizacao_motivo     TEXT,
    excluido_em            TEXT,
    UNIQUE (guild_id, week_id, user_id)
);

CREATE TABLE IF NOT EXISTS farm_ticket_lancamentos (
    event_id               INTEGER PRIMARY KEY,
    ticket_id              INTEGER NOT NULL,
    proof_channel_id       TEXT NOT NULL,
    proof_message_id       TEXT NOT NULL,
    proof_url              TEXT NOT NULL,
    log_proof_url          TEXT,
    observacao             TEXT,
    status                 TEXT NOT NULL DEFAULT 'registrado',
    revisado_por           TEXT,
    revisado_em            TEXT,
    revisao_motivo         TEXT,
    criado_em              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_ticket_actions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id              INTEGER NOT NULL,
    action                 TEXT NOT NULL,
    actor_id               TEXT NOT NULL,
    event_id               INTEGER,
    payload_json           TEXT,
    criado_em              TEXT NOT NULL,
    log_enviado_em         TEXT,
    log_message_id         TEXT,
    tentativas_log         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_farm_tickets_channel
ON farm_tickets (guild_id, channel_id);

CREATE INDEX IF NOT EXISTS idx_farm_tickets_status_week
ON farm_tickets (status, week_id);

CREATE INDEX IF NOT EXISTS idx_farm_ticket_lancamentos_ticket
ON farm_ticket_lancamentos (ticket_id, event_id);

CREATE INDEX IF NOT EXISTS idx_farm_ticket_actions_pending
ON farm_ticket_actions (log_enviado_em, id);
"""

MIGRATIONS = (
    ("metas", "itens_json", "TEXT"),
    ("metas", "meta_tipo", "TEXT DEFAULT 'itens'"),
    ("metas", "meta_dinheiro", "REAL DEFAULT 0"),
    ("progresso", "itens_prog_json", "TEXT"),
    ("progresso", "aprovacao_antecipada", "INTEGER DEFAULT 0"),
    ("progresso", "aprovacao_nivel", "TEXT"),
    ("eventos", "itens_json", "TEXT"),
    ("guild_config", "canal_encomendas_id", "TEXT"),
    ("guild_config", "canal_log_saida_id", "TEXT"),
    ("guild_config", "painel_operacoes_channel_id", "TEXT"),
    ("guild_config", "painel_operacoes_message_id", "TEXT"),
    ("guild_config", "painel_set_channel_id", "TEXT"),
    ("guild_config", "painel_set_message_id", "TEXT"),
    ("guild_config", "canal_adv_id", "TEXT"),
    ("guild_config", "painel_colete_channel_id", "TEXT"),
    ("guild_config", "painel_colete_message_id", "TEXT"),
    ("guild_config", "dashboard_channel_id", "TEXT"),
    ("guild_config", "dashboard_message_id", "TEXT"),
    ("guild_config", "canal_anuncio_id", "TEXT"),
    ("guild_config", "cargos_anuncio", "TEXT"),
    ("guild_config", "cargos_editar_farm", "TEXT"),
    ("guild_config", "painel_ranking_channel_id", "TEXT"),
    ("guild_config", "painel_ranking_message_id", "TEXT"),
    ("guild_config", "painel_ranking_week_id", "TEXT"),
    ("guild_config", "painel_lideranca_channel_id", "TEXT"),
    ("guild_config", "painel_lideranca_message_id", "TEXT"),
    ("guild_config", "flanelinha_role_id", "TEXT"),
    ("guild_config", "flanelinha_auto_promote", "INTEGER DEFAULT 0"),
    ("guild_config", "flanelinha_notify_user_id", "TEXT"),
    ("recolhimento_entregas", "alvo_user_id", "TEXT"),
    ("recolhimento_entregas", "alvo_nome", "TEXT"),
    ("recolhimento_entregas", "alvo_pasta_id", "TEXT"),
    ("fabricacoes_colete", "bau_operation_id", "TEXT"),
    ("fabricacoes_colete", "bau_sincronizado", "INTEGER DEFAULT 0"),
    ("fabricacoes_colete", "bau_sincronizado_em", "TEXT"),
)


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, definition: str) -> None:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")


def ensure_schema(conn: sqlite3.Connection, db_path: Path, log: logging.Logger) -> None:
    conn.executescript(SCHEMA_SQL)
    for table, column, definition in MIGRATIONS:
        _ensure_column(conn, table, column, definition)
    conn.commit()
    log.info("Banco inicializado: %s", db_path)
