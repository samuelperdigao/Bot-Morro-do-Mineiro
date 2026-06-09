import unittest

from cogs.bau import (
    BauPainelView,
    MovementConfirmView,
    PREVIEW_PAGE_SIZE,
    UNDO_PAGE_SIZE,
    UndoView,
)
from cogs.bau_core import UndoOperation


class BauViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_panel_has_all_persistent_actions(self):
        view = BauPainelView()

        custom_ids = {item.custom_id for item in view.children}
        self.assertEqual(
            custom_ids,
            {
                "bau:categoria_select",
                "bau:lote_entrada",
                "bau:lote_saida",
                "bau:desfazer",
                "bau:limpar",
            },
        )
        view.stop()

    async def test_complete_catalog_preview_is_paginated(self):
        items = [(f"Produto {index}", 1) for index in range(78)]
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
            tuple((f"Produto {index}", 1) for index in range(78)),
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
