"""Caracterização dos fluxos críticos antes da reorganização do bot.

Estes testes usam SQLite temporário e as classes reais das views. Eles não
substituem o teste manual no Discord, mas registram os contratos que a
refatoração precisa preservar.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import services.db_service as db
from cogs.acao import AcaoParticipantesView
from cogs.set_views import ApprovalView, SetPanelView
from services.paineis_service import PainelSetView


class TemporaryDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "baseline.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()


class CriticalViewCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_panels_keep_legacy_persistent_custom_ids(self):
        panel = SetPanelView()
        approval = ApprovalView(
            target_user_id=10,
            target_name="Membro",
            requester=SimpleNamespace(id=10),
            id_jogo="123",
        )

        self.assertIsNone(panel.timeout)
        self.assertIsNone(approval.timeout)
        self.assertEqual(
            {item.custom_id for item in panel.children},
            {"set_panel:fazer_set"},
        )
        self.assertEqual(
            {item.custom_id for item in approval.children},
            {"approval:aprovar", "approval:reprovar"},
        )

    async def test_action_panel_keeps_persistent_actions_and_custom_ids(self):
        view = AcaoParticipantesView()

        self.assertIsNone(view.timeout)
        self.assertEqual(
            {item.custom_id for item in view.children},
            {
                "acao:entrar",
                "acao:sair",
                "acao:adicionar",
                "acao:remover",
                "acao:encerrar",
            },
        )

    async def test_legacy_set_panel_view_keeps_its_compatibility_button(self):
        view = PainelSetView()

        self.assertIsNone(view.timeout)
        self.assertEqual(
            {item.custom_id for item in view.children},
            {"painel_set:pedir"},
        )


class CriticalDatabaseCharacterizationTests(
    TemporaryDatabaseTestCase, unittest.IsolatedAsyncioTestCase
):
    async def test_initialization_creates_core_tables_and_is_idempotent(self):
        db.init_db()
        tables = {
            row[0]
            for row in db.get_conn().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        self.assertTrue(
            {
                "guild_config",
                "system_config",
                "acoes",
                "acao_participantes",
                "farm_tickets",
            }.issubset(tables)
        )

        db.init_db()
        self.assertEqual(
            db.get_conn().execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='acoes'"
            ).fetchone()[0],
            1,
        )

    async def test_current_guild_and_system_configuration_can_be_read_back(self):
        db.db_set_guild_config(
            "guild-1",
            approval_channel_id="100",
            log_channel_id="101",
            private_category_id="102",
            member_role_id="103",
            approver_role_ids="200, 201",
        )
        db.db_set_system_config("guild-1", "acao", "300", "301")

        config = db.db_get_guild_config("guild-1")
        system = db.db_get_system_config("guild-1", "acao")

        self.assertEqual(config["approval_channel_id"], "100")
        self.assertEqual(db.db_get_approver_role_ids("guild-1"), [200, 201])
        self.assertEqual(system["canal_interacao_id"], "300")
        self.assertEqual(system["canal_log_id"], "301")

    async def test_action_creation_and_duplicate_participant_protection_survive_reload(self):
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

        self.assertTrue(
            db.db_acao_participante_add(
                action_id, "member-1", "Membro", "self", "member-1"
            )
        )
        self.assertFalse(
            db.db_acao_participante_add(
                action_id, "member-1", "Membro", "self", "member-1"
            )
        )

        # Uma nova View não depende da lista em memória da View anterior.
        reloaded_view = AcaoParticipantesView()
        self.assertIsNone(reloaded_view.timeout)
        persisted = db.db_acao_participantes(action_id)
        self.assertEqual([row["user_id"] for row in persisted], ["member-1"])
        self.assertEqual(
            db.db_acao_get_by_message("guild-1", "message-1")["id"],
            action_id,
        )


if __name__ == "__main__":
    unittest.main()
