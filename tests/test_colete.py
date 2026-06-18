import logging
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.bau_core import BauRepository
from cogs.colete import (
    ColeteCog,
    ColetePanelView,
    ColeteQuantityView,
    calcular_fabricacao,
    sincronizar_fabricacao_no_bau,
)
from services.db_schema import ensure_schema


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

    def test_calcula_limite_de_cem_coletes(self):
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

    def test_rejeita_quantidade_fora_do_limite(self):
        for quantidade in (0, 101):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(ValueError):
                    calcular_fabricacao(quantidade)

    async def test_painel_distribui_quantidades_por_quatro_faixas(self):
        seletores = ColetePanelView().children

        self.assertEqual(len(seletores), 1)
        self.assertEqual(
            [opcao.value for opcao in seletores[0].options],
            [
                "1:25",
                "26:50",
                "51:75",
                "76:100",
            ],
        )

    async def test_seletores_de_faixa_cobrem_uma_a_cem(self):
        quantidades = []
        for inicio in (1, 26, 51, 76):
            view = ColeteQuantityView(inicio, inicio + 24)
            self.assertEqual(len(view.children), 1)
            self.assertLessEqual(len(view.children[0].options), 25)
            quantidades.extend(
                int(opcao.value) for opcao in view.children[0].options
            )

        self.assertEqual(quantidades, list(range(1, 101)))

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

    async def test_falha_ao_postar_preserva_painel_anterior(self):
        old_message = SimpleNamespace(delete=AsyncMock())
        old_channel = SimpleNamespace(fetch_message=AsyncMock(return_value=old_message))
        channel = SimpleNamespace(
            id=20,
            mention="#coletes",
            send=AsyncMock(side_effect=RuntimeError("falha ao enviar")),
        )
        guild = SimpleNamespace(
            get_channel=MagicMock(return_value=old_channel),
            fetch_channel=AsyncMock(),
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            guild_id=30,
            guild=guild,
            channel=channel,
        )
        cog = ColeteCog(MagicMock())

        with patch(
            "cogs.colete.db_get_painel_colete",
            return_value=("10", "11"),
        ):
            with self.assertRaises(RuntimeError):
                await ColeteCog.colete.callback(cog, interaction)

        old_message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
