import unittest

import discord

from cogs.encomenda import EncomendaPainelView, PedidoView, build_embed

PEDIDO_CUSTOM_IDS = {
    "encomenda_pedido:producao",
    "encomenda_pedido:pronta",
    "encomenda_pedido:entregue",
    "encomenda_pedido:cancelar",
}


def _row(**overrides):
    row = {
        "id": 1,
        "numero": 3,
        "familia": "Família Silva",
        "quantidade": 50,
        "valor_centavos": 150000,
        "data": "08/06/2026",
        "observacao": None,
        "status": "pendente",
        "solicitante_id": "10",
        "responsavel_id": None,
        "atualizado_em": "2026-06-08T10:00:00-03:00",
    }
    row.update(overrides)
    return row


class EncomendaViewsTests(unittest.IsolatedAsyncioTestCase):
    async def test_painel_preserva_custom_id(self):
        view = EncomendaPainelView()
        self.assertTrue(view.is_persistent())
        self.assertEqual([item.custom_id for item in view.children], ["encomenda_painel:registrar"])

    async def test_pedido_view_persistente_com_custom_ids_fixos(self):
        view = PedidoView()
        self.assertTrue(view.is_persistent())
        self.assertEqual({item.custom_id for item in view.children}, PEDIDO_CUSTOM_IDS)
        self.assertFalse(any(item.disabled for item in view.children))

    async def test_botoes_desabilitados_conforme_status(self):
        esperado = {
            "pendente": set(),
            "em_producao": {"encomenda_pedido:producao"},
            "pronta": {"encomenda_pedido:producao", "encomenda_pedido:pronta"},
            "entregue": PEDIDO_CUSTOM_IDS,
            "cancelada": PEDIDO_CUSTOM_IDS,
        }
        for status, desabilitados in esperado.items():
            with self.subTest(status=status):
                view = PedidoView(status)
                self.assertEqual(
                    {item.custom_id for item in view.children if item.disabled},
                    desabilitados,
                )
                self.assertEqual({item.custom_id for item in view.children}, PEDIDO_CUSTOM_IDS)


class EncomendaEmbedTests(unittest.TestCase):
    def test_embed_pendente(self):
        embed = build_embed(_row(), None)
        campos = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "📦 Encomenda #003")
        self.assertEqual(embed.color, discord.Color.from_rgb(230, 126, 34))
        self.assertEqual(campos["💰 Valor"], "`R$ 1.500,00`")
        self.assertEqual(campos["🛠️ Responsável"], "—")
        self.assertNotIn("📝 Observação", campos)
        self.assertEqual(embed.footer.text, "Morro do Mineiro — Encomendas")
        self.assertIsNotNone(embed.timestamp)

    def test_embed_cancelada_mostra_quem_cancelou(self):
        embed = build_embed(
            _row(status="cancelada", responsavel_id="20", observacao="Sem pressa"),
            None,
            finalizado_por_id="30",
        )
        campos = {field.name: field.value for field in embed.fields}

        self.assertEqual(campos["❌ Cancelada por"], "<@30>")
        self.assertEqual(campos["🛠️ Responsável"], "<@20>")
        self.assertEqual(campos["📝 Observação"], "Sem pressa")


if __name__ == "__main__":
    unittest.main()
