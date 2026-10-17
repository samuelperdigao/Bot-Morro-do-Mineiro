import tempfile
import unittest
from pathlib import Path

import services.db_service as db
from services.acao_service import acao_service
from services.set_requests import set_request_service


class DomainServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "domain.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_set_service_owns_request_state_transitions(self):
        request_id = set_request_service.create(
            "guild-1", "user-1", "Nome", "123", "approval-channel"
        )
        set_request_service.attach_message(request_id, "approval-message")

        self.assertEqual(
            set_request_service.pending_for_user("guild-1", "user-1")["request_id"],
            request_id,
        )
        self.assertTrue(set_request_service.claim(request_id, "leader-1", "approved"))
        self.assertFalse(set_request_service.claim(request_id, "leader-2", "approved"))
        self.assertTrue(set_request_service.complete(request_id, "approved"))
        self.assertFalse(set_request_service.complete(request_id, "approved"))

    def test_action_service_enforces_open_duplicate_and_capacity_rules(self):
        action_id = acao_service.create(
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
            acao_service.add_participant(
                action_id, "member-1", "Membro 1", "self", "member-1", 1
            ).added
        )
        self.assertEqual(
            acao_service.add_participant(
                action_id, "member-1", "Membro 1", "self", "member-1", 1
            ).reason,
            "duplicate",
        )
        self.assertEqual(
            acao_service.add_participant(
                action_id, "member-2", "Membro 2", "self", "member-2", 1
            ).reason,
            "full",
        )
        self.assertTrue(acao_service.finalize(action_id, "perdida", "leader-1"))
        self.assertEqual(
            acao_service.add_participant(
                action_id, "member-3", "Membro 3", "self", "member-3", 1
            ).reason,
            "closed",
        )
        self.assertFalse(acao_service.finalize(action_id, "ganha", "leader-2"))


if __name__ == "__main__":
    unittest.main()
