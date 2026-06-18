import asyncio
import tempfile
import unittest
from pathlib import Path

import services.db_service as db
from config.paineis import BOTOES_LIDERANCA
from cogs.farm import FarmView
from cogs.farm_painel import FarmPainelView, LegacyFarmLaunchView
from cogs.farm_tickets import _progress


class FarmTicketDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "farm.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def _create_ticket(self):
        ticket, created = db.db_ticket_reserve("1", "2026-06-15", "10", "Membro")
        self.assertTrue(created)
        db.db_ticket_activate(int(ticket["id"]), "100", "200")
        return db.db_ticket_get(int(ticket["id"]))

    def test_ticket_is_unique_per_member_and_week(self):
        first, created = db.db_ticket_reserve("1", "2026-06-15", "10", "Membro")
        second, created_again = db.db_ticket_reserve("1", "2026-06-15", "10", "Outro nome")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])

    def test_ticket_launch_adds_to_general_progress_without_claiming_legacy_event(self):
        db.db_lancar("1", "2026-06-15", "10", {"Borracha": 100})
        ticket = self._create_ticket()
        event_id, _ = db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", "parcial",
        )

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(db.db_prog_itens(progress)["Borracha"], 150)
        launches = db.db_ticket_launches(int(ticket["id"]))
        self.assertEqual([row["id"] for row in launches], [event_id])
        self.assertEqual(db.db_evento_itens(launches[0]), {"Borracha": 50})
        self.assertEqual(len(db.db_eventos_usuario("1", "2026-06-15", "10")), 2)

    def test_legacy_and_ticket_launches_share_weekly_goal_progress(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 150}, "99")
        db.db_lancar("1", "2026-06-15", "10", {"Borracha": 100})
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(db.db_prog_itens(progress), {"Borracha": 150})
        self.assertEqual(len(db.db_ticket_launches(int(ticket["id"]))), 1)
        _, delivered, percentage, completed, _ = _progress(
            ticket, db.db_get_meta("1", "2026-06-15")
        )
        self.assertEqual(delivered, {"Borracha": 150})
        self.assertEqual(percentage, 100)
        self.assertTrue(completed)

    def test_failed_reservation_cleanup_does_not_remove_ticket_with_launches(self):
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 1},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        db.db_ticket_release_failed(int(ticket["id"]))
        self.assertIsNotNone(db.db_ticket_get(int(ticket["id"])))

    def test_config_is_separate_from_existing_farm_configuration(self):
        db.db_ticket_config_set("1", [11, 12], [21, 22])
        config = db.db_ticket_config_get("1")
        self.assertEqual(config["category_ids"], ["11", "12"])
        self.assertEqual(config["admin_role_ids"], ["21", "22"])
        self.assertIsNone(db.db_get_guild_config("1"))

    def test_completed_ticket_can_be_approved_without_listing_other_members(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        ticket = db.db_ticket_get(int(ticket["id"]))
        meta = db.db_get_meta("1", "2026-06-15")
        self.assertTrue(_progress(ticket, meta)[3])

        db.db_aprovar("1", "2026-06-15", "10", "20")
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovada_por"], "20")

    def test_operations_panel_no_longer_contains_general_approval(self):
        custom_ids = {button["custom_id"] for button in BOTOES_LIDERANCA}
        self.assertNotIn("painel:aprovar_farm", custom_ids)

    def test_current_farm_panels_only_offer_ticket_launch(self):
        async def labels():
            fixed = {item.label for item in FarmPainelView().children}
            personal = {
                item.label for item in FarmView(None, "1", "2026-06-15", "10").children
            }
            return fixed, personal

        fixed_labels, personal_labels = asyncio.run(labels())
        self.assertIn("🎫 Abrir Ticket Semanal", fixed_labels)
        self.assertIn("🎫 Abrir Ticket de Farm", personal_labels)
        self.assertNotIn("🚜 Lançar Farm", fixed_labels)
        self.assertNotIn("💵 Lançar Dinheiro", fixed_labels | personal_labels)

    def test_legacy_fixed_panel_ids_remain_registered_as_blockers(self):
        async def ids():
            return {item.custom_id for item in LegacyFarmLaunchView().children}

        custom_ids = asyncio.run(ids())
        self.assertEqual(
            custom_ids,
            {"farm_painel:lancar", "farm_painel:lancar_dinheiro"},
        )


if __name__ == "__main__":
    unittest.main()
