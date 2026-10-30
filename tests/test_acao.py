import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

import services.db_service as db
from cogs.acao import (
    AcaoParticipantesView,
    AcaoSelectView,
    calcular_pagamento,
    normalizar_horario,
    normalize_resultado,
    parse_money_centavos,
)
from services.acao_service import AcaoService, acao_service


class AcaoHelpersTests(unittest.TestCase):
    def test_normalizar_horario_accepts_hh_mm(self):
        self.assertEqual(normalizar_horario("21:00"), "21:00")

    def test_normalizar_horario_rejects_invalid_values(self):
        for value in ["25:00", "21h", "", "texto"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalizar_horario(value)

    def test_parse_money_accepts_common_br_formats(self):
        self.assertEqual(parse_money_centavos("50000"), 5_000_000)
        self.assertEqual(parse_money_centavos("50.000"), 5_000_000)
        self.assertEqual(parse_money_centavos("R$ 50.000,00"), 5_000_000)

    def test_normalize_resultado_accepts_expected_words(self):
        self.assertEqual(normalize_resultado("vitória"), "ganha")
        self.assertEqual(normalize_resultado("ganha"), "ganha")
        self.assertEqual(normalize_resultado("derrota"), "perdida")
        self.assertEqual(normalize_resultado("perdida"), "perdida")

    def test_calcular_pagamento_splits_half_and_keeps_rounding_leftover_with_faction(self):
        result = calcular_pagamento(10_001, 3)

        self.assertEqual(result["valor_total_centavos"], 10_001)
        self.assertEqual(result["valor_por_participante_centavos"], 1_666)
        self.assertEqual(result["valor_participantes_centavos"], 4_998)
        self.assertEqual(result["valor_faccao_centavos"], 5_003)


class AcaoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "acao.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_acao_persistence_lifecycle(self):
        acao_id = db.db_acao_criar(
            "1",
            "fleeca",
            "fuga",
            "30/06/2026",
            "21:00",
            "10",
            "100",
            "200",
        )

        self.assertIsNotNone(db.db_acao_get_by_message("1", "200"))
        self.assertTrue(db.db_acao_participante_add(acao_id, "11", "Membro", "self", "11"))
        self.assertFalse(db.db_acao_participante_add(acao_id, "11", "Membro", "self", "11"))
        self.assertEqual(len(db.db_acao_participantes(acao_id)), 1)
        self.assertTrue(db.db_acao_participante_remove(acao_id, "11"))
        self.assertEqual(db.db_acao_participantes(acao_id), [])

        db.db_acao_finalizar(
            acao_id,
            "perdida",
            "10",
            "Sem contingente",
        )
        final = db.db_acao_get(acao_id)

        self.assertEqual(final["status"], "perdida")
        self.assertEqual(final["resultado"], "perdida")
        self.assertEqual(final["observacao"], "Sem contingente")

    def test_participant_insert_enforces_limit_and_open_status_in_the_database(self):
        acao_id = db.db_acao_criar(
            "1", "fleeca", "fuga", "30/06/2026", "21:00", "10", "100", "200"
        )

        self.assertTrue(db.db_acao_participante_add(acao_id, "11", "A", "self", "11", 1))
        self.assertFalse(db.db_acao_participante_add(acao_id, "12", "B", "self", "12", 1))
        self.assertTrue(db.db_acao_participante_add(acao_id, "12", "B", "self", "12"))

        db.db_acao_finalizar(acao_id, "perdida", "10")

        self.assertFalse(db.db_acao_participante_add(acao_id, "13", "C", "self", "13"))
        self.assertEqual(
            [row["user_id"] for row in db.db_acao_participantes(acao_id)],
            ["11", "12"],
        )


def _fake_interaction(user_id: int, message_id: int | None = 200):
    return SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(
            id=user_id,
            display_name=f"Membro {user_id}",
            mention=f"<@{user_id}>",
        ),
        message=SimpleNamespace(id=message_id, edit=AsyncMock(), delete=AsyncMock()),
        response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        original_response=AsyncMock(
            return_value=SimpleNamespace(id=900, channel=SimpleNamespace(id=800))
        ),
    )


class AcaoPanelInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "acao_view.db"
        db._db_conn = None
        db.init_db()
        # loja_tatuagens tem teto de 2; fleeca, de 8.
        self.acao_id = acao_service.create(
            "1", "fleeca", "fuga", "30/06/2026", "21:00", "10", "100", "200"
        )

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def _inscritos(self, acao_id=None):
        return [row["user_id"] for row in AcaoService().participants(acao_id or self.acao_id)]

    async def test_participants_survive_a_new_view_and_service_instance(self):
        view = AcaoParticipantesView()
        for user_id in (11, 12, 13):
            await AcaoParticipantesView.entrar(view, _fake_interaction(user_id), None)

        self.assertEqual(self._inscritos(), ["11", "12", "13"])

        # Sem estado em memória: uma view nova, como após um restart, enxerga a lista.
        interaction = _fake_interaction(12)
        await AcaoParticipantesView.sair(AcaoParticipantesView(), interaction, None)

        self.assertEqual(self._inscritos(), ["11", "13"])
        embed = interaction.response.edit_message.await_args.kwargs["embed"]
        campo = next(f for f in embed.fields if f.name.startswith("✅ Participantes"))
        self.assertEqual(campo.name, "✅ Participantes (2)")
        self.assertIn("<@11>", campo.value)
        self.assertNotIn("<@12>", campo.value)

    async def test_entry_beyond_the_limit_is_rejected(self):
        acao_id = acao_service.create(
            "1", "loja_tatuagens", "fuga", "30/06/2026", "21:00", "10", "100", "201"
        )
        view = AcaoParticipantesView()
        for user_id in (11, 12):
            await AcaoParticipantesView.entrar(view, _fake_interaction(user_id, 201), None)

        terceiro = _fake_interaction(13, 201)
        await AcaoParticipantesView.entrar(view, terceiro, None)

        self.assertEqual(self._inscritos(acao_id), ["11", "12"])
        terceiro.response.edit_message.assert_not_awaited()
        args, kwargs = terceiro.response.send_message.await_args
        self.assertIn("Vagas esgotadas", args[0])
        self.assertTrue(kwargs["ephemeral"])

    async def test_leaving_without_being_registered_changes_nothing(self):
        interaction = _fake_interaction(11)

        await AcaoParticipantesView.sair(AcaoParticipantesView(), interaction, None)

        args, kwargs = interaction.response.send_message.await_args
        self.assertIn("não está inscrito", args[0])
        self.assertTrue(kwargs["ephemeral"])

    async def test_finalized_action_rejects_entry_and_keeps_its_message(self):
        self.assertTrue(acao_service.finalize(self.acao_id, "perdida", "10"))
        interaction = _fake_interaction(11)

        await AcaoParticipantesView.entrar(AcaoParticipantesView(), interaction, None)

        self.assertEqual(self._inscritos(), [])
        args, kwargs = interaction.response.send_message.await_args
        self.assertIn("já finalizada", args[0])
        self.assertTrue(kwargs["ephemeral"])
        interaction.message.edit.assert_not_awaited()

    async def test_panel_without_database_row_reports_unavailable_and_loses_its_view(self):
        interaction = _fake_interaction(11, message_id=999)

        await AcaoParticipantesView.entrar(AcaoParticipantesView(), interaction, None)

        args, kwargs = interaction.response.send_message.await_args
        self.assertIn("Painel indisponível", args[0])
        self.assertTrue(kwargs["ephemeral"])
        interaction.message.edit.assert_awaited_once_with(view=None)

    async def test_panel_just_published_keeps_its_view_while_row_is_being_saved(self):
        interaction = _fake_interaction(11, message_id=999)
        interaction.message.created_at = discord.utils.utcnow()

        await AcaoParticipantesView.entrar(AcaoParticipantesView(), interaction, None)

        self.assertIn("Painel indisponível", interaction.response.send_message.await_args.args[0])
        interaction.message.edit.assert_not_awaited()

    async def test_selector_requires_leadership_to_create_a_panel(self):
        view = AcaoSelectView("21:00", "fuga", "30/06/2026", "10")
        select = SimpleNamespace(values=["fleeca"])

        membro = _fake_interaction(11, message_id=300)
        with patch("cogs.acao._is_lideranca", return_value=False):
            await AcaoSelectView.selecionar_acao(view, membro, select)

        args, kwargs = membro.response.send_message.await_args
        self.assertIn("Apenas liderança", args[0])
        self.assertTrue(kwargs["ephemeral"])
        membro.message.delete.assert_not_awaited()
        self.assertIsNone(acao_service.get_by_message("1", "900"))

        lider = _fake_interaction(10, message_id=300)
        with patch("cogs.acao._is_lideranca", return_value=True):
            await AcaoSelectView.selecionar_acao(view, lider, select)

        self.assertIsNotNone(acao_service.get_by_message("1", "900"))
        lider.message.delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
