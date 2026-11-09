import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

import sqlite3

from services import ponto_service
from services.db_schema import SCHEMA_SQL


class PontoAutoFechamentoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(os.path.join(self._tmp.name, "ponto.db"))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._patch = patch.object(ponto_service, "get_conn", return_value=self.conn)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.conn.close()
        self._tmp.cleanup()

    def _abrir(self, user_id: str, horas_atras: float):
        entrada = ponto_service.now_tz() - timedelta(hours=horas_atras)
        self.conn.execute(
            "INSERT INTO ponto_sessoes (guild_id, week_id, user_id, entrada_em, status) VALUES (?,?,?,?,?)",
            ("1", "2026-11-09", user_id, entrada.isoformat(), ponto_service.STATUS_ABERTO),
        )
        self.conn.commit()

    def test_fecha_so_pontos_acima_do_limite_e_limita_a_duracao(self):
        self._abrir("10", horas_atras=30)
        self._abrir("20", horas_atras=2)

        fechadas = ponto_service.ponto_fechar_expiradas(12 * 3600)

        self.assertEqual([s["user_id"] for s in fechadas], ["10"])
        self.assertEqual(fechadas[0]["duracao_segundos"], 12 * 3600)
        self.assertEqual(fechadas[0]["fechado_por"], "sistema")
        self.assertIsNone(ponto_service.ponto_get_aberto("1", "10"))
        self.assertIsNotNone(ponto_service.ponto_get_aberto("1", "20"))

    def test_rodar_de_novo_nao_fecha_duas_vezes(self):
        self._abrir("10", horas_atras=30)
        self.assertEqual(len(ponto_service.ponto_fechar_expiradas(12 * 3600)), 1)
        self.assertEqual(ponto_service.ponto_fechar_expiradas(12 * 3600), [])


if __name__ == "__main__":
    unittest.main()


class PontoRankingEmbedTests(unittest.TestCase):
    def test_ranking_com_25_nomes_longos_respeita_limite(self):
        from types import SimpleNamespace

        from cogs import ponto as ponto_cog

        ranking = [
            {"user_id": str(1000 + i), "sessoes": 12, "total_segundos": 3600 * 40 + i}
            for i in range(25)
        ]
        membros = {
            1000 + i: SimpleNamespace(display_name=f"Nome_Muito*Comprido_do_Membro_{i:02d}")
            for i in range(25)
        }
        guild = SimpleNamespace(get_member=lambda uid: membros.get(uid))
        resumo = {"usuarios": 25, "sessoes": 300, "total_segundos": 999999, "abertas": 3}
        with patch.object(ponto_cog, "ponto_ranking_semana", return_value=ranking), \
             patch.object(ponto_cog, "ponto_resumo_semana", return_value=resumo):
            embed = ponto_cog._build_ranking_embed(guild, "1", "2026-11-09")

        campos = [f for f in embed.fields if f.name.startswith("Ranking")]
        self.assertEqual(len(campos), 3)
        for campo in embed.fields:
            self.assertLessEqual(len(campo.value), 1024)
        self.assertIn("\\*", campos[0].value)
