import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import services.db_service as db
from cogs.farm_advertencias import (
    PANEL_TITLE,
    FarmAdvertenciasCog,
    build_farm_warning_preview,
    build_panel_embed,
    is_farm_warning_eligible,
)


class FakeRole:
    def __init__(self, role_id, name=""):
        self.id = role_id
        self.name = name


class FakeMember:
    def __init__(self, user_id, name, roles, *, administrator=False, joined_at=None):
        self.id = user_id
        self.display_name = name
        self.roles = roles
        self.bot = False
        self.joined_at = joined_at
        self.guild_permissions = SimpleNamespace(
            administrator=administrator,
            manage_guild=False,
        )


class FakeGuild:
    def __init__(self, members):
        self.members = members


class FarmAdvertenciasTests(unittest.TestCase):
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

    def test_preview_warns_only_zero_without_absence(self):
        guild_id = "1"
        week_id = "2026-06-15"
        farm_role = FakeRole(50)
        adv1 = FakeRole(101)
        adv2 = FakeRole(102)

        completo = FakeMember(10, "Completo", [farm_role])
        parcial = FakeMember(20, "Parcial", [farm_role])
        ausente = FakeMember(30, "Ausente", [farm_role])
        zerado = FakeMember(40, "Zerado", [farm_role])
        recorrente = FakeMember(50, "Recorrente", [farm_role, adv1])
        ja_pd = FakeMember(60, "Ja PD", [farm_role, adv2, FakeRole(103)])

        db.db_set_guild_config(
            guild_id,
            cargos_permitidos_farm="50",
            cargos_lideranca_farm="70",
            farm_adv1_role_id="101",
            farm_adv2_role_id="102",
            farm_adv3_role_id="103",
        )
        db.db_set_meta(guild_id, week_id, {"Borracha": 100}, "99")
        db.db_lancar(guild_id, week_id, "10", {"Borracha": 100})
        db.db_lancar(guild_id, week_id, "20", {"Borracha": 40})
        db.db_farm_ausencia_registrar(guild_id, week_id, "30", "viagem")

        snapshot = build_farm_warning_preview(
            FakeGuild([completo, parcial, ausente, zerado, recorrente, ja_pd]),
            guild_id,
            week_id,
        )

        self.assertEqual([item["user_id"] for item in snapshot["entregaram"]], ["10"])
        self.assertEqual([item["user_id"] for item in snapshot["parciais"]], ["20"])
        self.assertEqual([item["user_id"] for item in snapshot["ausentes"]], ["30"])
        self.assertEqual(
            [(item["user_id"], item["nivel"]) for item in snapshot["pendentes"]],
            [("60", 1), ("50", 1), ("40", 1)],
        )

    def test_warning_counter_uses_new_database_history(self):
        guild_id = "1"
        week_id = "2026-06-15"
        farm_role = FakeRole(50)
        member = FakeMember(10, "Recorrente", [farm_role, FakeRole(101)])

        db.db_set_guild_config(
            guild_id,
            cargos_permitidos_farm="50",
            cargos_lideranca_farm="70",
            farm_adv1_role_id="101",
            farm_adv2_role_id="102",
            farm_adv3_role_id="103",
        )
        db.db_set_meta(guild_id, week_id, {"Borracha": 100}, "99")
        db.db_farm_advertencia_criar(
            guild_id, "2026-06-08", "10", 1, "falta", 300000, 3, "99"
        )

        snapshot = build_farm_warning_preview(FakeGuild([member]), guild_id, week_id)

        self.assertEqual(snapshot["pendentes"][0]["nivel"], 2)

    def test_members_below_role_02_are_eligible_even_without_farm_role(self):
        guild_id = "1"
        week_id = "2026-06-15"
        below_02 = FakeMember(10, "Cargo 03", [FakeRole(80, "| 03")])
        role_02 = FakeMember(20, "Cargo 02", [FakeRole(90, "| 02")])

        db.db_set_guild_config(
            guild_id,
            cargos_permitidos_farm="50",
            cargos_lideranca_farm="70",
            farm_adv1_role_id="101",
            farm_adv2_role_id="102",
            farm_adv3_role_id="103",
        )
        db.db_set_meta(guild_id, week_id, {"Borracha": 100}, "99")

        snapshot = build_farm_warning_preview(FakeGuild([below_02, role_02]), guild_id, week_id)

        self.assertEqual([item["user_id"] for item in snapshot["pendentes"]], ["10"])

    def test_administrator_without_farm_or_hierarchy_role_is_not_eligible(self):
        member = FakeMember(10, "Administrador", [], administrator=True)

        self.assertFalse(is_farm_warning_eligible(member, [50]))

    def test_member_who_joined_during_week_is_exempt_from_warning(self):
        guild_id = "1"
        week_id = "2026-06-15"
        newcomer = FakeMember(
            10,
            "Novato",
            [FakeRole(50)],
            joined_at=datetime(
                2026, 6, 18, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
            ),
        )
        db.db_set_guild_config(
            guild_id,
            cargos_permitidos_farm="50",
            farm_adv1_role_id="101",
            farm_adv2_role_id="102",
            farm_adv3_role_id="103",
        )
        db.db_set_meta(guild_id, week_id, {"Borracha": 100}, "99")

        snapshot = build_farm_warning_preview(FakeGuild([newcomer]), guild_id, week_id)

        self.assertEqual(snapshot["pendentes"], [])
        self.assertEqual([item["user_id"] for item in snapshot["isentos"]], ["10"])

    def test_panel_uses_stable_title_for_message_recovery(self):
        embed = build_panel_embed(SimpleNamespace(), "1")

        self.assertEqual(embed.title, PANEL_TITLE)
        self.assertIn("prévia", embed.description.casefold())

    def test_absence_is_unique_per_week(self):
        created, _ = db.db_farm_ausencia_registrar("1", "2026-06-15", "10", "motivo")
        duplicated, _ = db.db_farm_ausencia_registrar("1", "2026-06-15", "10", "outro")
        other_week, _ = db.db_farm_ausencia_registrar("1", "2026-06-22", "10", "outro")

        self.assertTrue(created)
        self.assertFalse(duplicated)
        self.assertTrue(other_week)

    def test_active_warning_is_unique_per_week(self):
        first, _ = db.db_farm_advertencia_criar(
            "1", "2026-06-15", "10", 1, "falta", 300000, 3, "99"
        )
        second, _ = db.db_farm_advertencia_criar(
            "1", "2026-06-15", "10", 2, "falta", 500000, 5, "99"
        )

        self.assertTrue(first)
        self.assertFalse(second)

    def test_failed_closure_can_be_claimed_again(self):
        row = db.db_farm_adv_fechamento_criar(
            "1",
            "2026-06-15",
            {"guild_id": "1", "week_id": "2026-06-15", "role_ids": {}},
            "99",
        )
        fechamento_id = int(row["id"])

        self.assertTrue(db.db_farm_adv_fechamento_claim(fechamento_id, "99"))
        self.assertFalse(db.db_farm_adv_fechamento_claim(fechamento_id, "99"))
        db.db_farm_adv_fechamento_finalizar(fechamento_id, {}, status="erro")
        self.assertTrue(db.db_farm_adv_fechamento_claim(fechamento_id, "99"))


class FarmAdvertenciasInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_ignores_member_who_left_after_preview(self):
        cog = FarmAdvertenciasCog.__new__(FarmAdvertenciasCog)
        interaction = SimpleNamespace(
            guild=SimpleNamespace(get_member=lambda _user_id: None),
        )

        result = await cog._apply_warning_item(
            interaction,
            {"guild_id": "1", "week_id": "2026-06-15"},
            {"user_id": "10", "display_name": "Saiu", "nivel": 1},
            {1: "101", 2: "102", 3: "103"},
        )

        self.assertEqual(result["status"], "saiu_do_servidor")

    async def test_apply_failure_marks_preview_for_retry(self):
        cog = FarmAdvertenciasCog.__new__(FarmAdvertenciasCog)
        cog.bot = SimpleNamespace()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=99),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        with (
            patch.object(cog, "_is_lideranca", AsyncMock(return_value=True)),
            patch("cogs.farm_advertencias.db_farm_adv_fechamento_claim", return_value=True),
            patch("cogs.farm_advertencias.db_farm_adv_fechamento_get", return_value=None),
            patch("cogs.farm_advertencias.db_farm_adv_fechamento_finalizar") as finalize,
        ):
            await cog.aplicar_fechamento(interaction, 123)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        finalize.assert_called_once()
        self.assertEqual(finalize.call_args.kwargs["status"], "erro")
        interaction.followup.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
