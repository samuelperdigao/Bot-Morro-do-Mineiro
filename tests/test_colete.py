import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import colete
from cogs.colete import (
    ColeteCog,
    calcular_fabricacao,
    interpretar_quantidade,
    montar_aguardando,
    montar_cancelado,
    montar_log,
    montar_painel,
    montar_passo_quantidade,
    montar_sucesso,
)
from core.components_v2 import LIMITE_COMPONENTES, contar_componentes
from services import db_service


def _todos(componentes):
    for comp in componentes:
        yield comp
        yield from _todos(comp.get("components", []))
        if "accessory" in comp:
            yield comp["accessory"]


def _botoes(componentes):
    return [c for c in _todos(componentes) if c["type"] == 2]


def _textos(componentes):
    return [c["content"] for c in _todos(componentes) if c["type"] == 10]


class ColeteCalculationTests(unittest.TestCase):
    def test_calcula_um_colete(self):
        self.assertEqual(
            calcular_fabricacao(1),
            {
                "ferro": 20,
                "plastico": 10,
                "tecido": 1,
                "aluminio": 20,
                "borracha": 10,
                "custo": 1000,
            },
        )

    def test_calcula_cem_coletes(self):
        self.assertEqual(
            calcular_fabricacao(100),
            {
                "ferro": 2000,
                "plastico": 1000,
                "tecido": 100,
                "aluminio": 2000,
                "borracha": 1000,
                "custo": 100000,
            },
        )

    def test_nao_ha_limite_superior(self):
        self.assertEqual(calcular_fabricacao(5000)["custo"], 5_000_000)

    def test_rejeita_quantidade_invalida(self):
        for quantidade in (0, -3):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(ValueError):
                    calcular_fabricacao(quantidade)


class InterpretarQuantidadeTests(unittest.TestCase):
    def test_aceita_numeros_e_separadores(self):
        self.assertEqual(interpretar_quantidade("25"), 25)
        self.assertEqual(interpretar_quantidade(" 1.000 "), 1000)
        self.assertEqual(interpretar_quantidade("1 000"), 1000)

    def test_rejeita_invalidos(self):
        for texto in ("", "0", "abc", "-5", "2,5x", "00"):
            with self.subTest(texto=texto):
                self.assertIsNone(interpretar_quantidade(texto))


class PayloadV2Tests(unittest.TestCase):
    def _validar(self, componentes):
        self.assertLessEqual(contar_componentes(componentes), LIMITE_COMPONENTES)
        ids = [b["custom_id"] for b in _botoes(componentes)]
        self.assertEqual(len(ids), len(set(ids)))
        for botao in _botoes(componentes):
            self.assertLessEqual(len(botao["custom_id"]), 100)
            self.assertLessEqual(len(botao["label"]), 80)
            self.assertTrue(botao["custom_id"].startswith("colete:"))
        for comp in _todos(componentes):
            if comp["type"] == 1:
                self.assertLessEqual(len(comp["components"]), 5)
        self.assertLessEqual(sum(len(t) for t in _textos(componentes)), 4000)

    def test_painel_sem_e_com_resumo(self):
        resumo = {"hoje_qtd": 34, "hoje_custo": 34000, "semana_qtd": 1212, "semana_custo": 1212000}
        sem = montar_painel()
        com = montar_painel(resumo)
        self._validar(sem)
        self._validar(com)
        ids = [b["custom_id"] for b in _botoes(com)]
        self.assertEqual(
            ids,
            ["colete:q:1", "colete:q:5", "colete:q:10", "colete:q:50", "colete:outra"],
        )
        texto = " ".join(_textos(com))
        self.assertIn("Hoje: **34**", texto)
        self.assertIn("Semana: **1.212**", texto)
        self.assertIn("$1.212.000", texto)
        self.assertNotIn("Hoje:", " ".join(_textos(sem)))

    def test_painel_nao_cita_limite(self):
        self.assertNotIn("limite", " ".join(_textos(montar_painel())).lower())

    def test_passo_quantidade(self):
        for quantidade in (1, 12, 1_000_000):
            with self.subTest(quantidade=quantidade):
                componentes = montar_passo_quantidade(quantidade)
                self._validar(componentes)
                ids = [b["custom_id"] for b in _botoes(componentes)]
                self.assertIn(f"colete:ok:{quantidade}", ids)
                self.assertIn(f"colete:step:{quantidade}:-10", ids)
                self.assertIn(f"colete:edit:{quantidade}", ids)

    def test_passo_mostra_materiais_e_custo(self):
        texto = " ".join(_textos(montar_passo_quantidade(5)))
        self.assertIn("Ferro `100`", texto)
        self.assertIn("Alumínio `100`", texto)
        self.assertIn("Tecido `5`", texto)
        self.assertIn("$5.000", texto)

    def test_demais_estados(self):
        self._validar(montar_aguardando(5, 1_800_000_000))
        self._validar(montar_cancelado())
        self._validar(montar_sucesso(42, 5, 5000, 123))
        self._validar(montar_sucesso(42, 1, 1000, None))

    def test_log_tem_secao_galeria_e_id(self):
        componentes = montar_log(
            fabricacao_id=42,
            membro_id=111,
            avatar_url="https://cdn.example/a.png",
            quantidade=5,
            materiais=calcular_fabricacao(5),
            canal_id=222,
            nome_arquivo="print.png",
            quando_unix=1_800_000_000,
        )
        self._validar(componentes)
        tipos = {c["type"] for c in _todos(componentes)}
        self.assertTrue({9, 11, 12, 17} <= tipos)
        galeria = next(c for c in _todos(componentes) if c["type"] == 12)
        self.assertEqual(galeria["items"][0]["media"]["url"], "attachment://print.png")
        texto = " ".join(_textos(componentes))
        self.assertIn("Fabricação #42", texto)
        self.assertIn("<@111>", texto)


class RoteamentoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = ColeteCog(MagicMock())
        self.interaction = MagicMock()
        self.interaction.guild_id = 1
        self.interaction.user.id = 2

    async def test_atalho_abre_passo_efemero(self):
        with patch.object(colete.v2, "responder", new=AsyncMock()) as responder:
            await self.cog._rotear(self.interaction, ["colete", "q", "10"])
        args, kwargs = responder.call_args
        self.assertIn("colete:ok:10", [b["custom_id"] for b in _botoes(args[1])])
        self.assertFalse(kwargs.get("atualizar", False))

    async def test_stepper_soma_e_nunca_fica_abaixo_de_um(self):
        casos = [("12", "-10", 2), ("5", "10", 15), ("3", "-10", 1), ("1", "-1", 1)]
        for atual, delta, esperado in casos:
            with self.subTest(atual=atual, delta=delta):
                with patch.object(colete.v2, "responder", new=AsyncMock()) as responder:
                    await self.cog._rotear(self.interaction, ["colete", "step", atual, delta])
                args, kwargs = responder.call_args
                self.assertTrue(kwargs["atualizar"])
                ids = [b["custom_id"] for b in _botoes(args[1])]
                self.assertIn(f"colete:ok:{esperado}", ids)

    async def test_outra_quantidade_abre_modal(self):
        self.interaction.response.send_modal = AsyncMock()
        await self.cog._rotear(self.interaction, ["colete", "outra"])
        self.interaction.response.send_modal.assert_awaited_once()

    async def test_painel_antigo_com_select_avisa_para_repostar(self):
        self.interaction.response.send_message = AsyncMock()
        await self.cog._rotear(self.interaction, ["colete", "select"])
        self.assertIn("/colete", self.interaction.response.send_message.call_args.args[0])

    async def test_abort_sinaliza_cancelamento_da_espera(self):
        import asyncio

        evento = asyncio.Event()
        self.cog._pendentes[(1, 2)] = evento
        with patch.object(colete.v2, "responder", new=AsyncMock()):
            await self.cog._rotear(self.interaction, ["colete", "abort"])
        self.assertTrue(evento.is_set())

    async def test_segunda_fabricacao_pendente_e_recusada(self):
        import asyncio

        self.cog._pendentes[(1, 2)] = asyncio.Event()
        self.interaction.response.send_message = AsyncMock()
        await self.cog._confirmar(self.interaction, 5)
        self.interaction.response.send_message.assert_awaited_once()


class ResumoColetesTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE fabricacoes_colete (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, user_id TEXT,
                user_name TEXT, quantidade INTEGER, ferro INTEGER, plastico INTEGER,
                tecido INTEGER, aluminio INTEGER, borracha INTEGER, custo INTEGER,
                timestamp TEXT)"""
        )
        self._antigo = db_service._db_conn
        db_service._db_conn = self.conn

    def tearDown(self):
        db_service._db_conn = self._antigo
        self.conn.close()

    def _inserir(self, guild, quantidade, quando):
        self.conn.execute(
            "INSERT INTO fabricacoes_colete (guild_id, user_id, user_name, quantidade,"
            " ferro, plastico, tecido, aluminio, borracha, custo, timestamp)"
            " VALUES (?, 'u', 'n', ?, 0, 0, 0, 0, 0, ?, ?)",
            (guild, quantidade, quantidade * 1000, quando.isoformat()),
        )
        self.conn.commit()

    def test_totais_de_hoje_e_da_semana_por_servidor(self):
        agora = db_service.now_tz()
        segunda = agora - timedelta(days=agora.weekday())
        self._inserir("g1", 10, agora)
        self._inserir("g1", 5, agora)
        self._inserir("g1", 7, segunda)
        self._inserir("g1", 99, segunda - timedelta(days=1))
        self._inserir("g2", 50, agora)

        resumo = db_service.db_resumo_coletes("g1")
        if agora.date() == segunda.date():
            self.assertEqual(resumo["hoje_qtd"], 22)
        else:
            self.assertEqual(resumo["hoje_qtd"], 15)
        self.assertEqual(resumo["semana_qtd"], 22)
        self.assertEqual(resumo["semana_custo"], 22000)

    def test_sem_registros_retorna_zeros(self):
        self.assertEqual(
            db_service.db_resumo_coletes("g1"),
            {"hoje_qtd": 0, "hoje_custo": 0, "semana_qtd": 0, "semana_custo": 0},
        )

    def test_registrar_retorna_id(self):
        primeiro = db_service.db_registrar_fabricacao_colete(
            "g1", "u", "n", 1, 20, 10, 1, 20, 10, 1000
        )
        segundo = db_service.db_registrar_fabricacao_colete(
            "g1", "u", "n", 2, 40, 20, 2, 40, 20, 2000
        )
        self.assertEqual(segundo, primeiro + 1)


if __name__ == "__main__":
    unittest.main()
