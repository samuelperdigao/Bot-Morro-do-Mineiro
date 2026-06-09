import unittest
from types import SimpleNamespace

import discord

from cogs.bau import (
    _build_operation_log_embeds,
    BauPainelView,
    MovementConfirmView,
    PREVIEW_PAGE_SIZE,
    ProductActionView,
    UNDO_PAGE_SIZE,
    UndoView,
)
from cogs.bau_core import (
    MovementLine,
    OperationResult,
    TOTAL_PRODUTOS,
    UndoOperation,
)


class BauViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_individual_log_uses_classic_layout(self):
        result = OperationResult(
            "operation-id",
            "entrada",
            "individual",
            "123",
            "Gerente",
            "09/06/2026 12:19:35",
            (
                MovementLine(
                    "Kit de Desmanche",
                    "\U0001f9f0 Kit de Desmanche",
                    64,
                    0,
                    64,
                ),
            ),
        )
        user = SimpleNamespace(display_name="6 6 2 7 | Mineiro", id=123)

        embeds = _build_operation_log_embeds(result, user)

        self.assertEqual(len(embeds), 1)
        embed = embeds[0]
        self.assertEqual(embed.title, "\U0001f7e2 Entrada \u2014 Kit de Desmanche")
        self.assertEqual(
            [field.name for field in embed.fields],
            [
                "\U0001f464 Usu\u00e1rio",
                "\U0001f4e6 Quantidade",
                "\U0001f5c3\ufe0f Estoque ap\u00f3s",
                "\U0001f550 Hor\u00e1rio",
            ],
        )
        self.assertEqual(embed.fields[1].value, "+64")
        self.assertEqual(embed.fields[2].value, "64 unidades")
        self.assertEqual(embed.fields[3].value, "09/06/2026 12:19:35")

    async def test_batch_log_remains_grouped(self):
        result = OperationResult(
            "operation-id",
            "entrada",
            "lote",
            "123",
            "Gerente",
            "09/06/2026 12:19:35",
            (
                MovementLine("Colete", "Itens Gerais", 2, 0, 2),
                MovementLine("5mm", "Municoes", 100, 0, 100),
            ),
        )
        user = SimpleNamespace(display_name="Gerente", id=123)

        embeds = _build_operation_log_embeds(result, user)

        self.assertEqual(embeds[0].title, "Entrada no Bau")
        self.assertIn("Operacao:", embeds[0].description)

    async def test_main_panel_has_all_persistent_actions(self):
        view = BauPainelView()

        custom_ids = {item.custom_id for item in view.children}
        self.assertEqual(
            custom_ids,
            {
                "bau:categoria_select",
                "bau:lote_entrada",
                "bau:desfazer",
                "bau:limpar",
            },
        )
        buttons = {
            item.custom_id: (item.label, item.row)
            for item in view.children
            if item.custom_id != "bau:categoria_select"
        }
        self.assertEqual(
            buttons,
            {
                "bau:lote_entrada": ("Adicionar", 1),
                "bau:desfazer": ("Desfazer", 1),
                "bau:limpar": ("Zerar", 1),
            },
        )
        view.stop()

    async def test_product_actions_use_only_entry_and_exit_buttons(self):
        view = ProductActionView("Colete", 123)

        self.assertEqual(
            [(item.label, item.style) for item in view.children],
            [
                ("Entrada", discord.ButtonStyle.success),
                ("Sa\u00edda", discord.ButtonStyle.danger),
            ],
        )
        view.stop()

    async def test_complete_catalog_preview_is_paginated(self):
        items = [(f"Produto {index}", 1) for index in range(TOTAL_PRODUTOS)]
        view = MovementConfirmView("entrada", items, "lote", 1)

        self.assertEqual(PREVIEW_PAGE_SIZE, 15)
        self.assertEqual(view.total_pages, 6)
        self.assertTrue(view.previous.disabled)
        self.assertFalse(view.next.disabled)
        view.stop()

    async def test_complete_catalog_undo_is_paginated_in_discord_limit(self):
        operation = UndoOperation(
            "operation",
            "entrada",
            "lote",
            "09/06/2026 12:00:00",
            tuple(
                (f"Produto {index}", 1)
                for index in range(TOTAL_PRODUTOS)
            ),
        )
        view = UndoView(operation, 1)
        select = next(
            child for child in view.children
            if child.__class__.__name__ == "UndoProductSelect"
        )

        self.assertEqual(UNDO_PAGE_SIZE, 25)
        self.assertEqual(view.total_pages, 4)
        self.assertEqual(len(select.options), 25)
        view.stop()


if __name__ == "__main__":
    unittest.main()
