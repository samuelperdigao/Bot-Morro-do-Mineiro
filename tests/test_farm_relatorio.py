import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord
import services.db_service as db
from cogs.farm_relatorio import (
    FarmPendingReportView,
    build_pending_report_embeds,
    build_report_overwrites,
    can_generate_report,
    previous_week_id,
    snapshot_eligible_members,
)


class FarmReportDatabaseTests(unittest.TestCase):
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

    def test_snapshot_replaces_previous_week_without_losing_panel(self):
        db.db_farm_report_set_panel("1", "100", "200")
        db.db_farm_report_set_snapshot(
            "1", "2026-06-08", [{"user_id": "10", "display_name": "Antigo"}]
        )
        db.db_farm_report_set_snapshot(
            "1", "2026-06-15", [{"user_id": "20", "display_name": "Mineiro"}]
        )

        report = db.db_farm_report_get("1")
        self.assertEqual(report["channel_id"], "100")
        self.assertEqual(report["panel_message_id"], "200")
        self.assertEqual(report["snapshot_week_id"], "2026-06-15")
        self.assertEqual(
            report["snapshot_members"],
            [{"user_id": "20", "display_name": "Mineiro"}],
        )

    def test_only_ticket_approval_actions_count_for_the_same_week(self):
        approved, _ = db.db_ticket_reserve("1", "2026-06-15", "10", "Mineiro")
        pending, _ = db.db_ticket_reserve("1", "2026-06-15", "20", "Coringa")
        other_week, _ = db.db_ticket_reserve("1", "2026-06-08", "30", "Paulista")

        db.db_ticket_add_action(int(approved["id"]), "aprovacao", "99")
        db.db_ticket_add_action(int(approved["id"]), "aprovacao", "98")
        db.db_ticket_add_action(int(pending["id"]), "finalizacao", "99")
        db.db_ticket_add_action(int(other_week["id"]), "aprovacao", "99")

        self.assertEqual(
            db.db_ticket_approved_user_ids("1", "2026-06-15"), {"10"}
        )


class FarmReportLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_has_one_persistent_button(self):
        view = FarmPendingReportView()
        self.assertEqual(len(view.children), 1)
        self.assertEqual(view.children[0].custom_id, "farm_pending_report:generate")
        self.assertEqual(view.children[0].label, "Gerar Relatório de Pendentes")
        view.stop()

    async def test_report_lists_only_pending_nicknames_without_ids(self):
        meta = {
            "meta_tipo": "itens",
            "itens_json": '{"Borracha": 50}',
            "folha": 0,
            "opio": 0,
            "seringa": 0,
            "agulha": 0,
            "meta_dinheiro": 0,
        }
        required = [
            {"user_id": "111111111111111111", "display_name": "Mineiro"},
            {"user_id": "222222222222222222", "display_name": "Coringa"},
        ]

        embeds = build_pending_report_embeds(
            meta, "2026-06-15", required, {"111111111111111111"}
        )
        rendered = str([embed.to_dict() for embed in embeds])
        pending_list = "\n".join(field.value for embed in embeds for field in embed.fields)

        self.assertIn("15/06 a 21/06", rendered)
        self.assertIn("Coringa", pending_list)
        self.assertNotIn("Mineiro", pending_list)
        self.assertNotIn("111111111111111111", rendered)
        self.assertNotIn("222222222222222222", rendered)

    async def test_report_shows_success_when_everyone_delivered(self):
        meta = {
            "meta_tipo": "dinheiro",
            "itens_json": None,
            "folha": 0,
            "opio": 0,
            "seringa": 0,
            "agulha": 0,
            "meta_dinheiro": 100,
        }
        members = [{"user_id": "10", "display_name": "Mineiro"}]

        embeds = build_pending_report_embeds(meta, "2026-06-15", members, {"10"})

        self.assertIn(
            "Todos os membros obrigados entregaram",
            embeds[0].description,
        )
        self.assertEqual(embeds[0].fields, [])


class FarmReportPermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "farm.db"
        db._db_conn = None
        db.init_db()
        db.db_ticket_config_set("1", [100], [200])

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_button_permission_reuses_ticket_admin_roles(self):
        manager = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False),
            roles=[SimpleNamespace(id=200)],
        )
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False),
            roles=[SimpleNamespace(id=300)],
        )
        admin = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=True), roles=[]
        )

        self.assertTrue(can_generate_report(manager, "1"))
        self.assertTrue(can_generate_report(admin, "1"))
        self.assertFalse(can_generate_report(member, "1"))

    def test_channel_overwrites_hide_everyone_and_allow_only_configured_roles(self):
        everyone = object()
        allowed_role = object()
        bot_member = object()
        guild = SimpleNamespace(
            default_role=everyone,
            me=bot_member,
            get_role=lambda role_id: allowed_role if role_id == 200 else None,
        )

        overwrites = build_report_overwrites(guild, ["200", "999"])

        self.assertFalse(overwrites[everyone].view_channel)
        self.assertTrue(overwrites[allowed_role].view_channel)
        self.assertFalse(overwrites[allowed_role].send_messages)
        self.assertTrue(overwrites[bot_member].view_channel)
        self.assertTrue(overwrites[bot_member].send_messages)

    def test_previous_week_is_immediately_closed_week(self):
        self.assertEqual(previous_week_id("2026-06-22"), "2026-06-15")

    def test_snapshot_uses_permitted_members_and_ignores_bots(self):
        db.db_set_guild_config("1", cargos_permitidos_farm="50")
        permitted_role = SimpleNamespace(id=50)
        other_role = SimpleNamespace(id=60)

        def member(user_id, name, role, *, bot=False):
            return SimpleNamespace(
                id=user_id,
                display_name=name,
                roles=[role],
                bot=bot,
                guild_permissions=SimpleNamespace(administrator=False),
            )

        guild = SimpleNamespace(members=[
            member(10, "Mineiro", permitted_role),
            member(20, "Sem Cargo", other_role),
            member(30, "Bot Farm", permitted_role, bot=True),
        ])

        self.assertEqual(
            snapshot_eligible_members(guild, "1"),
            [{"user_id": "10", "display_name": "Mineiro"}],
        )


if __name__ == "__main__":
    unittest.main()
