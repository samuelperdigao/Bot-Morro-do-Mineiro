import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path

import services.db_service as db
from core.settings import get_guild_settings, get_legacy_channel_id
from services.db_schema import ensure_schema


class SchemaMigrationTests(unittest.TestCase):
    def test_versioned_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versioned.db"
            conn = sqlite3.connect(path)
            ensure_schema(conn, path, logging.getLogger("test"))
            ensure_schema(conn, path, logging.getLogger("test"))
            versions = [
                row[0]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            pending_table = conn.execute(
                """SELECT COUNT(*) FROM sqlite_master
                   WHERE type='table' AND name='pending_member_folders'"""
            ).fetchone()[0]
            conn.close()

            self.assertEqual(versions, [1, 2, 3, 4])
            self.assertEqual(pending_table, 1)

    def test_legacy_farm_ticket_data_is_preserved_without_table_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE farm_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    week_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    member_name TEXT NOT NULL,
                    channel_id TEXT,
                    status TEXT NOT NULL,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    UNIQUE (guild_id, week_id, user_id)
                );
                INSERT INTO farm_tickets (
                    guild_id, week_id, user_id, member_name,
                    channel_id, status, criado_em, atualizado_em
                ) VALUES ('guild-1', '2026-10-12', 'user-1', 'Membro',
                          'channel-1', 'aberto', 'now', 'now');
                """
            )
            ensure_schema(conn, path, logging.getLogger("test"))
            count, name = conn.execute(
                "SELECT COUNT(*), member_name FROM farm_tickets"
            ).fetchone()
            legacy_table = conn.execute(
                """SELECT COUNT(*) FROM sqlite_master
                   WHERE type='table' AND name='farm_tickets_legacy'"""
            ).fetchone()[0]
            conn.close()

            self.assertEqual((count, name), (1, "Membro"))
            self.assertEqual(legacy_table, 0)


class GuildSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "settings.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_settings_prioritize_system_config_and_keep_guild_fallbacks(self):
        db.db_set_guild_config(
            "guild-1",
            canal_ausencias_id="111",
            cargos_lideranca_farm="10, 11",
            painel_set_channel_id="222",
            painel_set_message_id="333",
        )
        db.db_set_system_config("guild-1", "ausencia", "444", "445")

        settings = get_guild_settings("guild-1")

        self.assertEqual(settings.channel_id("ausencia"), "444")
        self.assertEqual(settings.channel_id("ausencia", "log"), "445")
        self.assertEqual(settings.role_ids("cargos_lideranca_farm"), (10, 11))
        self.assertEqual(settings.panel_reference("set"), ("222", "333"))
        self.assertEqual(settings.fixed_id("bau_channel"), 1474869322387292357)
        self.assertIsNotNone(get_legacy_channel_id("entry_log"))

    def test_guild_config_rejects_unknown_dynamic_column(self):
        with self.assertRaises(ValueError):
            db.db_set_guild_config("guild-1", **{"nao_permitido": "x"})

        db.db_set_guild_config("guild-1", approval_channel_id="123")
        self.assertEqual(
            db.db_get_guild_config("guild-1")["approval_channel_id"],
            "123",
        )

    def test_pending_member_folder_state_is_idempotent_and_removable(self):
        db.db_pending_member_folder_set("guild-1", "user-1")
        db.db_pending_member_folder_set("guild-1", "user-1")

        self.assertTrue(db.db_pending_member_folder_exists("guild-1", "user-1"))
        self.assertEqual(db.db_pending_member_folders_all("guild-1"), ["user-1"])

        db.db_pending_member_folder_delete("guild-1", "user-1")

        self.assertFalse(db.db_pending_member_folder_exists("guild-1", "user-1"))
        self.assertEqual(db.db_pending_member_folders_all("guild-1"), [])


if __name__ == "__main__":
    unittest.main()
