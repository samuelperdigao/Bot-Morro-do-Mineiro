import tempfile
import unittest
from pathlib import Path

import services.db_service as db

GUILD = "1"
WEEK = "2026-06-15"
META = {"Folha": 100, "Ópio": 100, "Seringa": 100, "Agulha": 100}


class CalcularPctMetaTests(unittest.TestCase):
    def test_excess_in_one_product_does_not_cover_another(self):
        self.assertEqual(db.calcular_pct_meta(META, {"Folha": 300}), 25)

    def test_complete_delivery_is_capped_at_one_hundred(self):
        entregue = {"Folha": 500, "Ópio": 100, "Seringa": 100, "Agulha": 100}
        self.assertEqual(db.calcular_pct_meta(META, entregue), 100)

    def test_targets_without_positive_value_are_ignored(self):
        self.assertEqual(db.calcular_pct_meta({"Folha": 100, "Ópio": 0}, {"Folha": 50}), 50)

    def test_without_targets_result_is_zero(self):
        self.assertEqual(db.calcular_pct_meta({}, {"Folha": 50}), 0)
        self.assertEqual(db.calcular_pct_meta({"Folha": 0}, {"Folha": 50}), 0)


class RankingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "ranking.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def _set_concluida_em(self, user_id: str, value: str):
        conn = db.get_conn()
        conn.execute(
            "UPDATE progresso SET status='concluida', concluida_em=? "
            "WHERE guild_id=? AND week_id=? AND user_id=?",
            (value, GUILD, WEEK, user_id),
        )
        conn.commit()

    def test_excess_in_one_product_ranks_behind_full_delivery(self):
        db.db_set_meta(GUILD, WEEK, META, "99")
        db.db_lancar(GUILD, WEEK, "10", {"Folha": 300})
        db.db_lancar(GUILD, WEEK, "11", dict(META))

        ranking = db.db_ranking_semana(GUILD, WEEK)

        self.assertEqual([row["user_id"] for row in ranking], ["11", "10"])
        self.assertEqual(ranking[0]["pct"], 100)
        self.assertEqual(ranking[1]["pct"], 25)

    def test_partial_with_higher_coverage_ranks_first_even_with_lower_total(self):
        db.db_set_meta(GUILD, WEEK, META, "99")
        db.db_lancar(GUILD, WEEK, "10", {"Folha": 300})
        db.db_lancar(GUILD, WEEK, "11", {"Folha": 60, "Ópio": 60})

        ranking = db.db_ranking_semana(GUILD, WEEK)

        self.assertEqual([row["user_id"] for row in ranking], ["11", "10"])

    def test_tie_is_broken_by_earliest_completion(self):
        db.db_set_meta(GUILD, WEEK, META, "99")
        for user_id in ("10", "11", "12"):
            db.db_lancar(GUILD, WEEK, user_id, dict(META))
        self._set_concluida_em("10", "2026-06-17T20:00:00-03:00")
        self._set_concluida_em("12", "2026-06-16T20:00:00-03:00")

        ranking = db.db_ranking_semana(GUILD, WEEK)

        self.assertEqual([row["user_id"] for row in ranking], ["12", "10", "11"])
        self.assertEqual(ranking[0]["concluida_em"], "2026-06-16T20:00:00-03:00")
        self.assertIsNone(ranking[2]["concluida_em"])

    def test_elite_stays_ahead_of_goal_met_with_capped_percentage(self):
        db.db_set_meta(GUILD, WEEK, {"Folha": 100}, "99")
        db.db_lancar(GUILD, WEEK, "10", {"Folha": 100})
        db.db_lancar(GUILD, WEEK, "11", {"Folha": 130})

        ranking = db.db_ranking_semana(GUILD, WEEK)

        self.assertEqual([row["user_id"] for row in ranking], ["11", "10"])
        self.assertEqual(ranking[0]["classificacao"], "elite")
        self.assertEqual(ranking[0]["pct"], 100)

    def test_money_goal_with_single_value_keeps_elite_reachable(self):
        db.db_set_meta_dinheiro(GUILD, WEEK, 1000, "99")
        db.db_lancar(GUILD, WEEK, "10", {db.DINHEIRO_SUJO_ITEM: 1300})
        db.db_lancar(GUILD, WEEK, "11", {db.DINHEIRO_SUJO_ITEM: 400, db.DINHEIRO_LIMPO_ITEM: 100})

        ranking = {row["user_id"]: row for row in db.db_ranking_semana(GUILD, WEEK)}

        self.assertEqual(ranking["10"]["classificacao"], "elite")
        self.assertEqual(ranking["10"]["pct"], 100)
        self.assertEqual(ranking["11"]["classificacao"], "parcial")
        self.assertEqual(ranking["11"]["pct"], 50)

    def test_money_goal_with_separate_values_averages_both_targets(self):
        db.db_set_meta_dinheiro(
            GUILD, WEEK, {db.DINHEIRO_SUJO_ITEM: 1000, db.DINHEIRO_LIMPO_ITEM: 1000}, "99"
        )
        db.db_lancar(GUILD, WEEK, "10", {db.DINHEIRO_SUJO_ITEM: 5000})

        ranking = db.db_ranking_semana(GUILD, WEEK)

        self.assertEqual(ranking[0]["pct"], 50)
        self.assertEqual(ranking[0]["classificacao"], "parcial")


if __name__ == "__main__":
    unittest.main()
