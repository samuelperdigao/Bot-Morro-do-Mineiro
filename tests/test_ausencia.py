import unittest
from datetime import datetime, timedelta

from cogs.ausencia import _dias_restantes, _embeds_ausencias, _fmt_data_brt


class AusenciaFusoTests(unittest.TestCase):
    def test_retorno_exibido_no_horario_de_brasilia(self):
        # 22h de Brasilia = 01h UTC do dia seguinte. Antes o retorno saia com
        # 1 dia a mais para quem registrava entre 21h e 23h59.
        inicio_utc = datetime(2026, 11, 10, 1, 0)  # 09/11 22:00 em Brasilia
        fim_utc = inicio_utc + timedelta(days=3)
        self.assertEqual(_fmt_data_brt(fim_utc), "12/11/2026")

    def test_aceita_datas_com_fuso(self):
        self.assertEqual(_fmt_data_brt("2026-11-12T01:00:00+00:00"), "11/11/2026")

    def test_dias_restantes_pelo_calendario_brt(self):
        agora = datetime(2026, 11, 10, 1, 0)  # 09/11 22:00 BRT
        self.assertEqual(_dias_restantes(agora + timedelta(days=3), agora), 3)
        self.assertEqual(_dias_restantes(agora - timedelta(days=1), agora), 0)


class AusenciaListagemTests(unittest.TestCase):
    def test_muitas_ausencias_respeitam_limites(self):
        agora = datetime(2026, 11, 10, 12, 0)
        ativos = [
            {
                "user_id": str(100000000000000000 + i),
                "nome": f"Membro *{i}*",
                "motivo": "Viagem a trabalho com retorno incerto " * 5,
                "fim": (agora + timedelta(days=1 + i % 7)).isoformat(),
            }
            for i in range(120)
        ]
        embeds = _embeds_ausencias(ativos, agora)
        self.assertLessEqual(len(embeds), 10)
        total = 0
        for embed in embeds:
            self.assertLessEqual(len(embed.description), 4096)
            total += len(embed.description) + len(embed.title) + len(embed.footer.text)
        # Limite do Discord: soma de todas as embeds da mensagem.
        self.assertLessEqual(total, 6000)
        self.assertIn("\\*", embeds[0].description)
        self.assertIn("e mais", embeds[-1].description)

    def test_poucas_ausencias_cabem_em_uma_embed(self):
        agora = datetime(2026, 11, 10, 12, 0)
        ativos = [{"user_id": "1", "nome": "Ana", "motivo": "", "fim": (agora + timedelta(days=2)).isoformat()}]
        embeds = _embeds_ausencias(ativos, agora)
        self.assertEqual(len(embeds), 1)
        self.assertNotIn("e mais", embeds[0].description)


if __name__ == "__main__":
    unittest.main()
