import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import services.db_service as db
from cogs.farm import EditarUltimoModal

GUILD = "1"
WEEK = "2026-06-15"
USER = "10"
META = {"Folha": 100, "Ópio": 100, "Seringa": 100, "Agulha": 100}


class ReaberturaBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "reabertura.db"
        db._db_conn = None
        db.init_db()
        db.db_set_meta(GUILD, WEEK, META, "99")

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def _concluir(self):
        db.db_lancar(GUILD, WEEK, USER, dict(META))
        self.assertEqual(db.db_verificar_conclusao(GUILD, WEEK, USER), "concluiu")

    def _progresso(self):
        return db.db_get_progresso(GUILD, WEEK, USER)


class VerificarConclusaoTests(ReaberturaBase):
    def test_returns_none_while_status_does_not_change(self):
        db.db_lancar(GUILD, WEEK, USER, {"Folha": 10})
        self.assertIsNone(db.db_verificar_conclusao(GUILD, WEEK, USER))
        self.assertIsNone(db.db_verificar_conclusao(GUILD, WEEK, "sem-progresso"))

    def test_second_check_after_completion_keeps_original_date(self):
        self._concluir()
        concluida_em = self._progresso()["concluida_em"]

        self.assertIsNone(db.db_verificar_conclusao(GUILD, WEEK, USER))
        self.assertEqual(self._progresso()["concluida_em"], concluida_em)

    def test_editing_below_the_goal_reopens(self):
        self._concluir()
        db.db_editar_ultimo_evento(GUILD, WEEK, USER, {**META, "Folha": 50})

        self.assertEqual(db.db_verificar_conclusao(GUILD, WEEK, USER), "reabriu")
        progresso = self._progresso()
        self.assertEqual(progresso["status"], "em_andamento")
        self.assertIsNone(progresso["concluida_em"])

    def test_editing_below_the_goal_clears_approval(self):
        self._concluir()
        db.db_aprovar(GUILD, WEEK, USER, "42", antecipada=True, nivel="elite")
        db.db_editar_ultimo_evento(GUILD, WEEK, USER, {**META, "Folha": 50})

        db.db_verificar_conclusao(GUILD, WEEK, USER)

        progresso = self._progresso()
        self.assertEqual(progresso["aprovada"], 0)
        self.assertIsNone(progresso["aprovada_por"])
        self.assertIsNone(progresso["aprovada_em"])
        self.assertEqual(progresso["aprovacao_antecipada"], 0)
        self.assertIsNone(progresso["aprovacao_nivel"])
        self.assertEqual(db.db_ranking_semana(GUILD, WEEK)[0]["classificacao"], "parcial")

    def test_reopening_is_audited(self):
        self._concluir()
        db.db_editar_ultimo_evento(GUILD, WEEK, USER, {**META, "Folha": 50})

        with self.assertLogs("audit", level="INFO") as logs:
            db.db_verificar_conclusao(GUILD, WEEK, USER)

        self.assertIn("action=META_REABERTA", logs.output[0])

    def test_early_approval_of_unfinished_progress_is_preserved(self):
        db.db_lancar(GUILD, WEEK, USER, {"Folha": 10})
        db.db_aprovar(GUILD, WEEK, USER, "42", antecipada=True, nivel="parcial")

        self.assertIsNone(db.db_verificar_conclusao(GUILD, WEEK, USER))

        progresso = self._progresso()
        self.assertEqual(progresso["aprovada"], 1)
        self.assertEqual(progresso["aprovacao_nivel"], "parcial")


class MudancaDeMetaTests(ReaberturaBase):
    def test_raising_the_goal_reopens_whoever_no_longer_covers_it(self):
        self._concluir()
        db.db_aprovar(GUILD, WEEK, USER, "42")
        db.db_lancar(GUILD, WEEK, "11", {nome: 300 for nome in META})
        db.db_verificar_conclusao(GUILD, WEEK, "11")

        db.db_set_meta(GUILD, WEEK, {nome: 200 for nome in META}, "99")

        progresso = self._progresso()
        self.assertEqual(progresso["status"], "em_andamento")
        self.assertEqual(progresso["aprovada"], 0)
        self.assertEqual(db.db_get_progresso(GUILD, WEEK, "11")["status"], "concluida")

    def test_lowering_the_goal_concludes_whoever_now_covers_it(self):
        db.db_lancar(GUILD, WEEK, USER, {nome: 50 for nome in META})

        db.db_set_meta(GUILD, WEEK, {nome: 50 for nome in META}, "99")

        progresso = self._progresso()
        self.assertEqual(progresso["status"], "concluida")
        self.assertIsNotNone(progresso["concluida_em"])

    def test_money_goal_change_recalculates_the_week(self):
        db.db_set_meta_dinheiro(GUILD, WEEK, {db.DINHEIRO_SUJO_ITEM: 100}, "99")
        db.db_lancar(GUILD, WEEK, USER, {db.DINHEIRO_SUJO_ITEM: 100})
        self.assertEqual(db.db_verificar_conclusao(GUILD, WEEK, USER), "concluiu")

        db.db_set_meta_dinheiro(GUILD, WEEK, {db.DINHEIRO_SUJO_ITEM: 200}, "99")

        self.assertEqual(self._progresso()["status"], "em_andamento")


class CorrecaoDeTicketTests(ReaberturaBase):
    def _criar_ticket(self):
        ticket, _created = db.db_ticket_reserve(GUILD, WEEK, USER, "Membro")
        return ticket

    def test_correction_below_the_goal_clears_approval(self):
        ticket = self._criar_ticket()
        self._concluir()
        db.db_aprovar(GUILD, WEEK, USER, "42")
        db.db_editar_ultimo_evento(GUILD, WEEK, USER, {**META, "Folha": 50})

        db.db_ticket_recalculate_completion(int(ticket["id"]))

        progresso = self._progresso()
        self.assertEqual(progresso["status"], "em_andamento")
        self.assertEqual(progresso["aprovada"], 0)

    def test_correction_above_the_goal_keeps_original_completion_date(self):
        ticket = self._criar_ticket()
        self._concluir()
        concluida_em = self._progresso()["concluida_em"]
        db.db_editar_ultimo_evento(GUILD, WEEK, USER, {**META, "Folha": 150})

        db.db_ticket_recalculate_completion(int(ticket["id"]))

        self.assertEqual(self._progresso()["concluida_em"], concluida_em)


class EditarUltimoModalTests(ReaberturaBase):
    def _submeter(self, valores: dict):
        async def invoke():
            cog = SimpleNamespace(
                _atualizar_painel=AsyncMock(),
                _atualizar_ranking_fixo=AsyncMock(),
                _notificar_conclusao=AsyncMock(),
            )
            modal = EditarUltimoModal(cog, WEEK, GUILD, USER, valores)
            ticket_cog = SimpleNamespace(refresh_week=AsyncMock())
            interaction = SimpleNamespace(
                guild=SimpleNamespace(),
                user=SimpleNamespace(id=int(USER)),
                client=SimpleNamespace(get_cog=lambda name: ticket_cog),
                response=SimpleNamespace(send_message=AsyncMock()),
            )
            await modal.on_submit(interaction)
            return cog, ticket_cog, interaction

        return asyncio.run(invoke())

    def test_labels_identify_the_launch_and_fit_discord_limit(self):
        async def build():
            return EditarUltimoModal(
                SimpleNamespace(), WEEK, GUILD, USER, {"Folha": 10, "X" * 60: 5}
            )

        modal = asyncio.run(build())

        self.assertEqual(modal._inputs[0].label, "Folha (deste lançamento)")
        self.assertEqual(modal._inputs[0].default, "10")
        self.assertTrue(all(len(item.label) <= 45 for item in modal._inputs))
        self.assertTrue(all(len(item.placeholder) <= 100 for item in modal._inputs))

    def test_reopening_does_not_notify_completion(self):
        self._concluir()

        cog, ticket_cog, interaction = self._submeter({**META, "Folha": 50})

        cog._notificar_conclusao.assert_not_awaited()
        ticket_cog.refresh_week.assert_awaited_once_with(GUILD, WEEK)
        self.assertIn("aprovação foi zerada", interaction.response.send_message.await_args.args[0])

    def test_completing_through_edit_notifies(self):
        db.db_lancar(GUILD, WEEK, USER, {**META, "Folha": 50})

        cog, ticket_cog, _interaction = self._submeter(dict(META))

        cog._notificar_conclusao.assert_awaited_once()
        ticket_cog.refresh_week.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
