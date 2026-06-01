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
    canal_notificacao_farm TEXT
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

CREATE TABLE IF NOT EXISTS producoes_heroina (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    user_name  TEXT NOT NULL,
    quantidade INTEGER NOT NULL,
    opio       REAL NOT NULL,
    agulha     REAL NOT NULL,
    folha      REAL NOT NULL,
    seringa    REAL NOT NULL,
    custo      REAL NOT NULL,
    timestamp  TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS ponto_config (
    guild_id           TEXT PRIMARY KEY,
    ponto_category_id  TEXT,
    log_category_id    TEXT,
    painel_channel_id  TEXT,
    log_channel_id     TEXT,
    ranking_channel_id TEXT,
    ranking_message_id TEXT,
    ranking_week_id    TEXT
);

CREATE TABLE IF NOT EXISTS ponto_sessoes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id           TEXT NOT NULL,
    week_id            TEXT NOT NULL,
    user_id            TEXT NOT NULL,
    entrada_em         TEXT NOT NULL,
    saida_em           TEXT,
    duracao_segundos   INTEGER DEFAULT 0,
    observacao_entrada TEXT,
    observacao_saida   TEXT,
    fechado_por        TEXT,
    status             TEXT DEFAULT 'aberto'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ponto_sessoes_abertas
ON ponto_sessoes (guild_id, user_id)
WHERE status = 'aberto';

CREATE INDEX IF NOT EXISTS idx_ponto_sessoes_guild_week_status
ON ponto_sessoes (guild_id, week_id, status);
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
    ("guild_config", "painel_heroina_channel_id", "TEXT"),
    ("guild_config", "painel_heroina_message_id", "TEXT"),
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
    ("recolhimento_entregas", "alvo_user_id", "TEXT"),
    ("recolhimento_entregas", "alvo_nome", "TEXT"),
    ("recolhimento_entregas", "alvo_pasta_id", "TEXT"),
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
