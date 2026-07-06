import tempfile
import unittest
from pathlib import Path

import services.db_service as db
from cogs.acao import (
    calcular_pagamento,
    normalizar_horario,
    normalize_resultado,
    parse_money_centavos,
)


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


if __name__ == "__main__":
    unittest.main()
