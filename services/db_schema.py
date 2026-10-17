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
    flanelinha_notify_user_id TEXT,
    farm_adv1_role_id TEXT,
    farm_adv2_role_id TEXT,
    farm_adv3_role_id TEXT,
    farm_adv_panel_channel_id TEXT,
    farm_adv_panel_message_id TEXT,
    parceria_category_id TEXT,
    parceria_registrar_channel_id TEXT,
    parceria_ativas_channel_id TEXT,
    parceria_panel_message_id TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS set_requests (
    request_id            TEXT PRIMARY KEY,
    guild_id              TEXT NOT NULL,
    requester_user_id     TEXT NOT NULL,
    target_name           TEXT NOT NULL,
    id_jogo               TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending',
    approval_channel_id   TEXT NOT NULL,
    approval_message_id   TEXT,
    decided_by            TEXT,
    created_at            TEXT NOT NULL,
    completed_at          TEXT,
    processing_started_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_set_requests_pending_user
ON set_requests (guild_id, requester_user_id, status);

CREATE INDEX IF NOT EXISTS idx_set_requests_approval_message
ON set_requests (guild_id, approval_channel_id, approval_message_id);

CREATE TABLE IF NOT EXISTS acoes (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id                        TEXT NOT NULL,
    acao_key                        TEXT NOT NULL,
    tipo                            TEXT NOT NULL,
    data                            TEXT NOT NULL,
    horario                         TEXT NOT NULL,
    criado_por                      TEXT NOT NULL,
    status                          TEXT NOT NULL DEFAULT 'aberta',
    channel_id                      TEXT NOT NULL,
    message_id                      TEXT NOT NULL,
    resultado                       TEXT,
    valor_total_centavos            INTEGER,
    valor_faccao_centavos           INTEGER,
    valor_participantes_centavos    INTEGER,
    valor_por_participante_centavos INTEGER,
    observacao                      TEXT,
    criado_em                       TEXT NOT NULL,
    atualizado_em                   TEXT NOT NULL,
    finalizado_em                   TEXT,
    finalizado_por                  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_acoes_message
ON acoes (guild_id, message_id);

CREATE INDEX IF NOT EXISTS idx_acoes_status
ON acoes (guild_id, status, criado_em);

CREATE TABLE IF NOT EXISTS acao_participantes (
    acao_id       INTEGER NOT NULL,
    user_id       TEXT NOT NULL,
    user_name     TEXT NOT NULL,
    origem        TEXT NOT NULL,
    adicionado_por TEXT,
    criado_em     TEXT NOT NULL,
    PRIMARY KEY (acao_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_acao_participantes_acao
ON acao_participantes (acao_id, criado_em);

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
    agulha         INTEGER,
    itens_json     TEXT
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

CREATE TABLE IF NOT EXISTS farm_pending_report (
    guild_id               TEXT PRIMARY KEY,
    channel_id             TEXT,
    panel_message_id       TEXT,
    report_message_id      TEXT,
    snapshot_week_id       TEXT,
    snapshot_members_json  TEXT,
    snapshot_created_at    TEXT,
    atualizado_em          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_tickets (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id               TEXT NOT NULL,
    week_id                TEXT NOT NULL,
    user_id                TEXT NOT NULL,
    member_name            TEXT NOT NULL,
    folder_channel_id      TEXT,
    folder_slot            INTEGER,
    game_id                TEXT,
    folder_nickname        TEXT,
    channel_id             TEXT,
    panel_message_id       TEXT,
    log_message_id         TEXT,
    log_thread_id          TEXT,
    status                 TEXT NOT NULL DEFAULT 'criando',
    assigned_to            TEXT,
    criado_em              TEXT NOT NULL,
    atualizado_em          TEXT NOT NULL,
    finalizado_em          TEXT,
    finalizado_por         TEXT,
    finalizacao_motivo     TEXT,
    excluido_em            TEXT
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

CREATE TABLE IF NOT EXISTS farm_ticket_finalization_logs (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id              INTEGER NOT NULL,
    user_id                TEXT NOT NULL,
    meta_id                TEXT NOT NULL,
    item                   TEXT NOT NULL,
    quantidade_meta        REAL NOT NULL DEFAULT 0,
    quantidade_entregue    REAL NOT NULL DEFAULT 0,
    status_final           TEXT NOT NULL,
    motivo                 TEXT NOT NULL,
    criado_em              TEXT NOT NULL,
    UNIQUE (ticket_id, meta_id, item)
);

CREATE INDEX IF NOT EXISTS idx_farm_tickets_channel
ON farm_tickets (guild_id, channel_id);

CREATE INDEX IF NOT EXISTS idx_farm_tickets_status_week
ON farm_tickets (status, week_id);

CREATE INDEX IF NOT EXISTS idx_farm_ticket_lancamentos_ticket
ON farm_ticket_lancamentos (ticket_id, event_id);

CREATE INDEX IF NOT EXISTS idx_farm_ticket_actions_pending
ON farm_ticket_actions (log_enviado_em, id);

CREATE INDEX IF NOT EXISTS idx_farm_ticket_finalization_logs_ticket
ON farm_ticket_finalization_logs (ticket_id, criado_em);

CREATE TABLE IF NOT EXISTS farm_ausencias (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id  TEXT NOT NULL,
    week_id   TEXT NOT NULL,
    user_id   TEXT NOT NULL,
    motivo    TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'registrada',
    criado_em TEXT NOT NULL,
    UNIQUE (guild_id, week_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_farm_ausencias_week
ON farm_ausencias (guild_id, week_id, status);

CREATE TABLE IF NOT EXISTS farm_advertencias (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id            TEXT NOT NULL,
    week_id             TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    nivel               INTEGER NOT NULL,
    motivo              TEXT NOT NULL,
    multa               INTEGER NOT NULL DEFAULT 0,
    dias_sem_desmanche  INTEGER NOT NULL DEFAULT 0,
    aplicado_por        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'ativa',
    criado_em           TEXT NOT NULL,
    removido_por        TEXT,
    removido_em         TEXT,
    motivo_remocao      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_farm_advertencias_active_week
ON farm_advertencias (guild_id, week_id, user_id)
WHERE status='ativa';

CREATE INDEX IF NOT EXISTS idx_farm_advertencias_user
ON farm_advertencias (guild_id, user_id, status, nivel);

CREATE TABLE IF NOT EXISTS farm_advertencia_fechamentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      TEXT NOT NULL,
    week_id       TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'previa',
    responsavel   TEXT NOT NULL,
    criado_em     TEXT NOT NULL,
    aplicado_por  TEXT,
    aplicado_em   TEXT
);

CREATE INDEX IF NOT EXISTS idx_farm_adv_fechamentos_week
ON farm_advertencia_fechamentos (guild_id, week_id, status, criado_em);

CREATE TABLE IF NOT EXISTS parcerias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    nome_familia TEXT NOT NULL COLLATE NOCASE,
    produto TEXT NOT NULL,
    cor_carro TEXT,
    area_risco TEXT,
    contato_01 TEXT,
    contato_02 TEXT,
    mensagem_lista_id INTEGER NOT NULL,
    nome_arquivo_imagem TEXT NOT NULL,
    registrado_por INTEGER NOT NULL,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT,
    ativo INTEGER DEFAULT 1,
    UNIQUE (guild_id, nome_familia)
);

CREATE INDEX IF NOT EXISTS idx_parcerias_guild_ativo
ON parcerias (guild_id, ativo, nome_familia);
"""

LEGACY_COLUMN_MIGRATIONS = (
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
    ("guild_config", "farm_adv1_role_id", "TEXT"),
    ("guild_config", "farm_adv2_role_id", "TEXT"),
    ("guild_config", "farm_adv3_role_id", "TEXT"),
    ("guild_config", "farm_adv_panel_channel_id", "TEXT"),
    ("guild_config", "farm_adv_panel_message_id", "TEXT"),
    ("guild_config", "parceria_category_id", "TEXT"),
    ("guild_config", "parceria_registrar_channel_id", "TEXT"),
    ("guild_config", "parceria_ativas_channel_id", "TEXT"),
    ("guild_config", "parceria_panel_message_id", "TEXT"),
    ("parcerias", "cor_carro", "TEXT"),
    ("parcerias", "area_risco", "TEXT"),
    ("recolhimento_entregas", "alvo_user_id", "TEXT"),
    ("recolhimento_entregas", "alvo_nome", "TEXT"),
    ("recolhimento_entregas", "alvo_pasta_id", "TEXT"),
    ("recolhimento_entregas", "itens_json", "TEXT"),
    ("fabricacoes_colete", "bau_operation_id", "TEXT"),
    ("fabricacoes_colete", "bau_sincronizado", "INTEGER DEFAULT 0"),
    ("fabricacoes_colete", "bau_sincronizado_em", "TEXT"),
    ("farm_tickets", "folder_channel_id", "TEXT"),
    ("farm_tickets", "folder_slot", "INTEGER"),
    ("farm_tickets", "game_id", "TEXT"),
    ("farm_tickets", "folder_nickname", "TEXT"),
    ("farm_tickets", "log_message_id", "TEXT"),
    ("farm_tickets", "log_thread_id", "TEXT"),
)

# Mantido como alias temporário para módulos externos que importavam o nome
# antigo. A execução agora é controlada por VERSIONED_MIGRATIONS abaixo.
MIGRATIONS = LEGACY_COLUMN_MIGRATIONS


GUILD_CONFIG_FIELDS = frozenset({
    "approval_channel_id",
    "log_channel_id",
    "private_category_id",
    "member_role_id",
    "approver_role_ids",
    "canal_ausencias_id",
    "cargos_lideranca_farm",
    "cargos_permitidos_farm",
    "canal_avisos_farm",
    "canal_notificacao_farm",
    "flanelinha_role_id",
    "flanelinha_auto_promote",
    "flanelinha_notify_user_id",
    "farm_adv1_role_id",
    "farm_adv2_role_id",
    "farm_adv3_role_id",
    "farm_adv_panel_channel_id",
    "farm_adv_panel_message_id",
    "parceria_category_id",
    "parceria_registrar_channel_id",
    "parceria_ativas_channel_id",
    "parceria_panel_message_id",
    "canal_encomendas_id",
    "canal_log_saida_id",
    "painel_operacoes_channel_id",
    "painel_operacoes_message_id",
    "painel_set_channel_id",
    "painel_set_message_id",
    "canal_adv_id",
    "painel_colete_channel_id",
    "painel_colete_message_id",
    "dashboard_channel_id",
    "dashboard_message_id",
    "canal_anuncio_id",
    "cargos_anuncio",
    "cargos_editar_farm",
    "painel_ranking_channel_id",
    "painel_ranking_message_id",
    "painel_ranking_week_id",
    "painel_lideranca_channel_id",
    "painel_lideranca_message_id",
})


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, definition: str) -> None:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")


def _apply_legacy_columns(conn: sqlite3.Connection) -> bool:
    for table, column, definition in LEGACY_COLUMN_MIGRATIONS:
        _ensure_column(conn, table, column, definition)
    return True


def _apply_set_request_schema(conn: sqlite3.Connection) -> bool:
    # A tabela também faz parte do SCHEMA_SQL para instalações novas. Estas
    # instruções tornam a etapa explícita e segura para bases existentes.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS set_requests (
            request_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            requester_user_id TEXT NOT NULL,
            target_name TEXT NOT NULL,
            id_jogo TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            approval_channel_id TEXT NOT NULL,
            approval_message_id TEXT,
            decided_by TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            processing_started_at TEXT
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_set_requests_pending_user
           ON set_requests (guild_id, requester_user_id, status)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_set_requests_approval_message
           ON set_requests (guild_id, approval_channel_id, approval_message_id)"""
    )
    return True


def _apply_farm_active_ticket_index(conn: sqlite3.Connection, log: logging.Logger) -> bool:
    try:
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_farm_tickets_active_member
               ON farm_tickets (guild_id, week_id, user_id)
               WHERE status IN ('criando', 'aberto', 'revisao')"""
        )
    except sqlite3.IntegrityError:
        # Dados conflitantes ficam intactos. A ausência do índice é registrada
        # para permitir correção manual e uma nova tentativa futura.
        log.warning(
            "Índice de ticket ativo não aplicado: existem membros duplicados "
            "na mesma guild/semana; nenhum dado foi removido."
        )
        return False
    return True


VERSIONED_MIGRATIONS = (
    (1, "ensure legacy columns", _apply_legacy_columns),
    (2, "ensure persistent set requests", _apply_set_request_schema),
    (3, "ensure active farm ticket index", _apply_farm_active_ticket_index),
)


def ensure_schema(conn: sqlite3.Connection, db_path: Path, log: logging.Logger) -> None:
    conn.executescript(SCHEMA_SQL)
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, name, migration in VERSIONED_MIGRATIONS:
        if version in applied:
            continue
        completed = migration(conn, log) if version == 3 else migration(conn)
        if not completed:
            continue
        conn.execute(
            """INSERT INTO schema_migrations (version, name, applied_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (version, name),
        )
    conn.commit()
    log.info("Banco inicializado: %s", db_path)
