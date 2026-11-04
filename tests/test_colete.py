import asyncio
import logging
import sqlite3
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import colete
from cogs.bau_core import BauRepository
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
    sincronizar_fabricacao_no_bau,
)
from core.components_v2 import LIMITE_COMPONENTES, contar_componentes
from services import db_service
from services.db_schema import ensure_schema


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


class ColeteCalculationTests(unittest.IsolatedAsyncioTestCase):
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

    def test_sincronizacao_com_bau_e_idempotente(self):
        with TemporaryDirectory() as tmp:
            repository = BauRepository(Path(tmp) / "bau.db")
            repository.initialize()
            fabricacao = {
                "id": 7,
                "user_id": "123",
                "user_name": "Fabricante",
                "quantidade": 12,
                "bau_operation_id": "fabricacao-colete-teste",
            }

            with patch(
                "cogs.colete.db_marcar_fabricacao_colete_sincronizada"
            ) as marcar:
                primeira = sincronizar_fabricacao_no_bau(
                    fabricacao,
                    repository,
                )
                repetida = sincronizar_fabricacao_no_bau(
                    fabricacao,
                    repository,
                )

            self.assertEqual(repository.get_quantity("Colete"), 12)
            self.assertEqual(primeira.origem, "fabricacao_colete")
            self.assertEqual(primeira.lines[0].estoque_antes, 0)
            self.assertEqual(primeira.lines[0].estoque_depois, 12)
            self.assertIsNone(repetida)
            self.assertEqual(marcar.call_count, 2)

    def test_fabricacao_nao_pode_ser_desfeita_pelo_bau(self):
        with TemporaryDirectory() as tmp:
            repository = BauRepository(Path(tmp) / "bau.db")
            repository.initialize()
            fabricacao = {
                "id": 8,
                "user_id": "123",
                "user_name": "Fabricante",
                "quantidade": 5,
                "bau_operation_id": "fabricacao-colete-sem-undo",
            }
            with patch(
                "cogs.colete.db_marcar_fabricacao_colete_sincronizada"
            ):
                sincronizar_fabricacao_no_bau(fabricacao, repository)

            self.assertIsNone(repository.get_last_undoable_operation("123"))
            with self.assertRaises(ValueError):
                repository.undo_items(
                    "fabricacao-colete-sem-undo",
                    "123",
                    {"Colete"},
                )
            self.assertEqual(repository.get_quantity("Colete"), 5)

    def test_migracao_nao_importa_fabricacoes_antigas(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "farmbot.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE fabricacoes_colete (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    quantidade INTEGER NOT NULL,
                    ferro INTEGER NOT NULL,
                    plastico INTEGER NOT NULL,
                    tecido INTEGER NOT NULL,
                    aluminio INTEGER NOT NULL,
                    borracha INTEGER NOT NULL,
                    custo INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                )"""
            )
            conn.execute(
                """INSERT INTO fabricacoes_colete
                   (guild_id, user_id, user_name, quantidade, ferro, plastico,
                    tecido, aluminio, borracha, custo, timestamp)
                   VALUES ('1', '2', 'Antigo', 10, 200, 100, 10, 200, 100,
                           10000, '2026-01-01')"""
            )
            ensure_schema(conn, db_path, logging.getLogger("test"))

            row = conn.execute(
                """SELECT bau_operation_id, bau_sincronizado
                   FROM fabricacoes_colete WHERE id=1"""
            ).fetchone()
            conn.close()

            self.assertIsNone(row[0])
            self.assertEqual(row[1], 0)

    def _interacao_publicar(self, old_message):
        old_channel = SimpleNamespace(fetch_message=AsyncMock(return_value=old_message))
        guild = SimpleNamespace(
            get_channel=MagicMock(return_value=old_channel),
            fetch_channel=AsyncMock(),
        )
        return SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            guild_id=30,
            guild=guild,
            channel=SimpleNamespace(id=20, mention="#coletes"),
        )

    async def test_falha_ao_postar_preserva_painel_anterior(self):
        old_message = SimpleNamespace(delete=AsyncMock())
        interaction = self._interacao_publicar(old_message)
        cog = ColeteCog(MagicMock())

        with patch(
            "cogs.colete.db_get_painel_colete", return_value=("10", "11")
        ), patch(
            "cogs.colete.db_resumo_coletes", return_value=None
        ), patch.object(
            colete.v2, "enviar_canal",
            new=AsyncMock(side_effect=RuntimeError("falha ao enviar")),
        ):
            with self.assertRaises(RuntimeError):
                await ColeteCog.colete.callback(cog, interaction)

        old_message.delete.assert_not_awaited()

    async def test_falha_ao_salvar_remove_painel_novo_e_preserva_anterior(self):
        old_message = SimpleNamespace(delete=AsyncMock())
        interaction = self._interacao_publicar(old_message)
        bot = MagicMock()
        bot.http.delete_message = AsyncMock()
        cog = ColeteCog(bot)

        with patch(
            "cogs.colete.db_get_painel_colete", return_value=("10", "11")
        ), patch(
            "cogs.colete.db_resumo_coletes", return_value=None
        ), patch(
            "cogs.colete.db_set_guild_config",
            side_effect=sqlite3.OperationalError("banco travado"),
        ), patch.object(
            colete.v2, "enviar_canal", new=AsyncMock(return_value={"id": "99"})
        ):
            with self.assertRaises(sqlite3.OperationalError):
                await ColeteCog.colete.callback(cog, interaction)

        bot.http.delete_message.assert_awaited_once_with(20, 99)
        old_message.delete.assert_not_awaited()

    async def test_publicacao_remove_painel_anterior_depois_de_salvar(self):
        old_message = SimpleNamespace(delete=AsyncMock())
        interaction = self._interacao_publicar(old_message)
        cog = ColeteCog(MagicMock())

        with patch(
            "cogs.colete.db_get_painel_colete", return_value=("10", "11")
        ), patch(
            "cogs.colete.db_resumo_coletes", return_value=None
        ), patch(
            "cogs.colete.db_set_guild_config"
        ) as salvar, patch.object(
            colete.v2, "enviar_canal", new=AsyncMock(return_value={"id": "99"})
        ):
            await ColeteCog.colete.callback(cog, interaction)

        salvar.assert_called_once()
        old_message.delete.assert_awaited_once()


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
        self._validar(montar_sucesso(42, 1, 1000, 123, bau_sincronizado=False))

    def test_sucesso_informa_estado_do_bau(self):
        ok = " ".join(_textos(montar_sucesso(42, 5, 5000, 123)))
        pendente = " ".join(
            _textos(montar_sucesso(42, 5, 5000, 123, bau_sincronizado=False))
        )
        self.assertIn("adicionada ao Baú", ok)
        self.assertIn("pendente", pendente)
        self.assertEqual(
            montar_sucesso(42, 5, 5000, 123, bau_sincronizado=False)[0]["accent_color"],
            colete.COR_DOURADO,
        )

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
        self.assertNotIn("Estoque do Baú", texto)

    def test_log_mostra_estoque_do_bau(self):
        operacao = SimpleNamespace(
            lines=[SimpleNamespace(estoque_antes=1200, estoque_depois=1205, quantidade=5)]
        )
        estados = {
            "`1.200` → `1.205` (+5)": colete._texto_estoque_bau(True, operacao),
            "Sincronizado anteriormente": colete._texto_estoque_bau(True, None),
            "Pendente": colete._texto_estoque_bau(False, None),
        }
        for esperado, estoque in estados.items():
            with self.subTest(esperado=esperado):
                componentes = montar_log(
                    fabricacao_id=42,
                    membro_id=111,
                    avatar_url="https://cdn.example/a.png",
                    quantidade=5,
                    materiais=calcular_fabricacao(5),
                    canal_id=222,
                    nome_arquivo="print.png",
                    quando_unix=1_800_000_000,
                    estoque_bau=estoque,
                )
                self._validar(componentes)
                texto = " ".join(_textos(componentes))
                self.assertIn("Estoque do Baú", texto)
                self.assertIn(esperado, texto)


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
        for acao in ("select", "faixa"):
            with self.subTest(acao=acao):
                self.interaction.response.send_message = AsyncMock()
                await self.cog._rotear(self.interaction, ["colete", acao])
                self.assertIn(
                    "/colete",
                    self.interaction.response.send_message.call_args.args[0],
                )

    async def test_finalizar_credita_bau_e_informa_no_log_e_na_resposta(self):
        anexo = MagicMock()
        anexo.filename = "print.png"
        anexo.content_type = "image/png"
        anexo.to_file = AsyncMock(return_value=SimpleNamespace(filename="print.png"))
        mensagem = SimpleNamespace(attachments=[anexo], delete=AsyncMock())
        self.interaction.user.display_name = "Fabricante"
        self.interaction.user.display_avatar.url = "https://cdn.example/a.png"
        self.interaction.channel_id = 3
        fabricacao = {
            "id": 77,
            "guild_id": "1",
            "user_id": "2",
            "user_name": "Fabricante",
            "quantidade": 5,
            "bau_operation_id": "fabricacao-colete-x",
        }
        self.cog.sincronizar_fabricacao = AsyncMock(return_value=(False, None))
        self.cog._postar_log = AsyncMock(return_value=123)
        self.cog._atualizar_painel = AsyncMock()

        with patch(
            "cogs.colete.db_registrar_fabricacao_colete", return_value=fabricacao
        ), patch.object(colete.v2, "editar_original", new=AsyncMock()) as editar:
            await self.cog._finalizar(self.interaction, 5, mensagem)

        self.cog.sincronizar_fabricacao.assert_awaited_once_with(fabricacao)
        texto_log = " ".join(_textos(self.cog._postar_log.call_args.args[1]))
        self.assertIn("Fabricação #77", texto_log)
        self.assertIn("Pendente de sincronização", texto_log)
        texto_resposta = " ".join(_textos(editar.call_args.args[1]))
        self.assertIn("Fabricação #77 registrada", texto_resposta)
        self.assertIn("pendente", texto_resposta)

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
                timestamp TEXT, bau_operation_id TEXT,
                bau_sincronizado INTEGER NOT NULL DEFAULT 0,
                bau_sincronizado_em TEXT)"""
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

    def test_registrar_retorna_id_e_fica_pendente_para_o_bau(self):
        primeiro = db_service.db_registrar_fabricacao_colete(
            "g1", "u", "n", 1, 20, 10, 1, 20, 10, 1000
        )
        segundo = db_service.db_registrar_fabricacao_colete(
            "g1", "u", "n", 2, 40, 20, 2, 40, 20, 2000
        )
        self.assertEqual(segundo["id"], primeiro["id"] + 1)
        self.assertNotEqual(primeiro["bau_operation_id"], segundo["bau_operation_id"])
        pendentes = db_service.db_get_fabricacoes_colete_pendentes()
        self.assertEqual([p["id"] for p in pendentes], [primeiro["id"], segundo["id"]])

        db_service.db_marcar_fabricacao_colete_sincronizada(primeiro["id"])
        pendentes = db_service.db_get_fabricacoes_colete_pendentes()
        self.assertEqual([p["id"] for p in pendentes], [segundo["id"]])


if __name__ == "__main__":
    unittest.main()
