import tempfile
import unittest
from pathlib import Path

import discord
from discord.ext import commands

from cogs.set_views import register_persistent_views
import services.db_service as db


class PersistentStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "persistent.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_set_request_lifecycle_is_atomic_and_duplicate_decision_is_rejected(self):
        request_id = db.db_set_request_create(
            "guild-1", "user-1", "Nome", "123", "approval-channel"
        )
        db.db_set_request_attach_message(request_id, "approval-message")

        self.assertEqual(
            db.db_set_request_get_by_message(
                "guild-1", "approval-channel", "approval-message"
            )["request_id"],
            request_id,
        )
        self.assertTrue(db.db_set_request_claim(request_id, "approver-1", "approved"))
        self.assertFalse(db.db_set_request_claim(request_id, "approver-2", "approved"))
        self.assertTrue(db.db_set_request_complete(request_id, "approved"))
        self.assertFalse(db.db_set_request_complete(request_id, "approved"))
        self.assertEqual(db.db_set_request_get(request_id)["status"], "approved")

    def test_interrupted_set_processing_is_reopened_without_deleting_history(self):
        request_id = db.db_set_request_create(
            "guild-1", "user-1", "Nome", "123", "approval-channel"
        )
        db.db_set_request_claim(request_id, "approver-1", "approved")

        self.assertEqual(db.db_set_request_recover_interrupted(), 1)
        row = db.db_set_request_get(request_id)
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["decided_by"])

    def test_action_finalization_is_compare_and_set(self):
        action_id = db.db_acao_criar(
            "guild-1",
            "fleeca",
            "fuga",
            "30/06/2026",
            "21:00",
            "creator-1",
            "channel-1",
            "message-1",
        )

        self.assertTrue(db.db_acao_finalizar(action_id, "perdida", "leader-1"))
        self.assertFalse(db.db_acao_finalizar(action_id, "ganha", "leader-2"))
        self.assertEqual(db.db_acao_get(action_id)["finalizado_por"], "leader-1")


class PersistentViewRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "views.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    async def test_registers_current_panel_fallback_and_recoverable_request(self):
        request_id = db.db_set_request_create(
            "guild-1", "123456789012345678", "Nome", "123", "987654321098765432"
        )
        db.db_set_request_attach_message(request_id, "876543210987654321")
        bot = commands.Bot(
            command_prefix="!",
            intents=discord.Intents.none(),
            application_id=1,
        )

        register_persistent_views(bot)

        self.assertEqual(len(bot.persistent_views), 3)
        await bot.close()


if __name__ == "__main__":
    unittest.main()
