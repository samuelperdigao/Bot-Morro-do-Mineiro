import json
import unittest

from cogs.colete import MATERIAIS_POR_COLETE
from cogs.farm import (
    COLETE_PLACEHOLDERS,
    COLETE_PRODUTOS,
    DefinirMetasModal,
    EscolherTipoMetaView,
)
from services.db_service import db_meta_itens_ativos, db_meta_tipo_efetivo


class MetaColeteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = {
            "meta_tipo": "colete",
            "itens_json": json.dumps(
                {
                    "Ferro": 20,
                    "Plastico": 10,
                    "Tecido": 1,
                    "Aluminio": 20,
                    "Borracha": 10,
                }
            ),
        }

    def test_meta_colete_mantem_tipo_proprio(self):
        self.assertEqual(db_meta_tipo_efetivo(self.meta), "colete")

    def test_meta_colete_conta_como_meta_de_itens(self):
        self.assertEqual(
            db_meta_itens_ativos(self.meta),
            {
                "Ferro": 20,
                "Plastico": 10,
                "Tecido": 1,
                "Aluminio": 20,
                "Borracha": 10,
            },
        )

    async def test_seletor_oferece_colete_kit_e_dinheiro(self):
        view = EscolherTipoMetaView(None, "2026-06-15", "1")
        self.assertEqual(
            [item.label for item in view.children],
            ["📦 Kit Desmanche", "🦺 Colete", "💵 Dinheiro"],
        )

    async def test_modal_colete_usa_a_receita_da_fabricacao(self):
        modal = DefinirMetasModal(
            None,
            "2026-06-15",
            "1",
            produtos=COLETE_PRODUTOS,
            meta_tipo="colete",
            titulo="Meta Colete",
            placeholders=COLETE_PLACEHOLDERS,
        )
        esperados = [
            (nome.title(), f"{quantidade} por colete")
            for nome, quantidade in MATERIAIS_POR_COLETE.items()
        ]
        recebidos = [
            (item.label.split(" ", 1)[1], item.placeholder)
            for item in modal.children
        ]
        self.assertEqual(modal.title, "Meta Colete")
        self.assertEqual(recebidos, esperados)


if __name__ == "__main__":
    unittest.main()
