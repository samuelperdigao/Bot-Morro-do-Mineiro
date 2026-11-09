import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs import acao as acao_cog
from cogs.acao import ACOES, _build_regras_embed, normalizar_horario
from services import acao_service
from services.db_schema import SCHEMA_SQL


def _tamanho(embed) -> int:
    total = len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "")
    return total + sum(len(f.name) + len(f.value) for f in embed.fields)


class AcaoServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(os.path.join(self._tmp.name, "acao.db"), isolation_level="")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._patch = patch.object(acao_service, "get_conn", return_value=self.conn)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.conn.close()
        self._tmp.cleanup()

    def test_duas_acoes_simultaneas_tem_inscritos_separados(self):
        a = acao_service.criar_acao("1", "c", "fleeca", "9", "10/11/2026", "21:00", "fuga", message_id="m1")
        b = acao_service.criar_acao("1", "c", "joalheria", "9", "10/11/2026", "22:00", "tiro", message_id="m2")
        self.assertEqual(acao_service.inscrever(a, "10", "10", 8), "ok")
        self.assertEqual(acao_service.inscrever(b, "20", "20", 7), "ok")
        self.assertEqual(acao_service.inscritos(a), ["10"])
        self.assertEqual(acao_service.inscritos(b), ["20"])
        self.assertEqual(acao_service.get_por_mensagem("m2")["id"], b)

    def test_limite_de_vagas_e_duplicidade(self):
        a = acao_service.criar_acao("1", "c", "loja_tatuagens", "9", None, None, None)
        self.assertEqual(acao_service.inscrever(a, "1", "1", 2), "ok")
        self.assertEqual(acao_service.inscrever(a, "1", "1", 2), "ja_inscrito")
        self.assertEqual(acao_service.inscrever(a, "2", "2", 2), "ok")
        self.assertEqual(acao_service.inscrever(a, "3", "3", 2), "lotada")

    def test_acao_encerrada_nao_aceita_alteracoes(self):
        a = acao_service.criar_acao("1", "c", "fleeca", "9", None, None, None)
        acao_service.inscrever(a, "1", "1", None)
        self.assertTrue(acao_service.encerrar(a, "9"))
        self.assertFalse(acao_service.encerrar(a, "9"))
        self.assertEqual(acao_service.inscrever(a, "2", "2", None), "encerrada")
        self.assertEqual(acao_service.remover(a, "1"), "encerrada")
        self.assertEqual(acao_service.inscritos(a), ["1"])


class AcaoEmbedTests(unittest.TestCase):
    def test_muitos_inscritos_respeitam_limites(self):
        ids = [str(100000000000000000 + i) for i in range(300)]
        for key in ACOES:
            with self.subTest(acao=key):
                embed = _build_regras_embed(key, ids, "21:00", "fuga", "10/11/2026")
                self.assertLessEqual(len(embed.fields), 25)
                for field in embed.fields:
                    self.assertLessEqual(len(field.value), 1024)
                self.assertLessEqual(_tamanho(embed), 6000)

    def test_horario(self):
        self.assertEqual(normalizar_horario("21:00"), "21:00")
        self.assertEqual(normalizar_horario("9h30"), "09:30")
        for invalido in ("25:00", "21", "amanhã", "21:7"):
            with self.subTest(invalido=invalido):
                with self.assertRaises(ValueError):
                    normalizar_horario(invalido)


class AcaoViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_painel_sem_registro_avisa_em_vez_de_quebrar(self):
        view = acao_cog.AcaoParticipantesView()
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=123),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        with patch.object(acao_service, "get_por_mensagem", return_value=None):
            self.assertIsNone(await view._acao(interaction))
        self.assertIn("antes da atualização", interaction.response.send_message.await_args.args[0])
        view.stop()


if __name__ == "__main__":
    unittest.main()
