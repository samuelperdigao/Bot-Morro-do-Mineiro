import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.bau import (
    _is_bau_admin,
    _parse_category_quantity,
    _build_operation_log_embeds,
    BauPainelView,
    CategoryPageView,
    CategoryQuantityModal,
    CategorySession,
    CategorySelect,
    ClearConfirmView,
    CATEGORY_PAGE_SIZE,
    UNDO_PAGE_SIZE,
    UndoView,
)
from cogs.bau_core import (
    CATEGORIAS,
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

    async def test_category_log_creates_classic_embed_per_product(self):
        result = OperationResult(
            "operation-id",
            "entrada",
            "categoria",
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

        self.assertEqual(len(embeds), 2)
        self.assertEqual(embeds[0].title, "\U0001f7e2 Entrada \u2014 Colete")
        self.assertEqual(embeds[1].title, "\U0001f7e2 Entrada \u2014 5mm")

    async def test_main_panel_has_all_persistent_actions(self):
        view = BauPainelView()

        custom_ids = {item.custom_id for item in view.children}
        self.assertEqual(
            custom_ids,
            {
                "bau:categoria_select",
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
                "bau:desfazer": ("Desfazer", 1),
                "bau:limpar": ("Zerar", 1),
            },
        )
        view.stop()

    async def test_category_select_contains_only_real_categories(self):
        select = CategorySelect()

        self.assertEqual(
            [option.value for option in select.options],
            list(CATEGORIAS),
        )

    async def test_category_pages_cover_supported_category_sizes(self):
        self.assertEqual(CATEGORY_PAGE_SIZE, 5)
        for product_count, expected_pages in (
            (1, 1),
            (4, 1),
            (5, 1),
            (6, 2),
            (11, 3),
            (16, 4),
        ):
            session = CategorySession(
                "Teste",
                "entrada",
                123,
                tuple(f"Produto {index}" for index in range(product_count)),
            )
            self.assertEqual(session.page_count, expected_pages)
            for page in range(expected_pages):
                session.page = page
                modal = CategoryQuantityModal(session)
                self.assertLessEqual(len(modal.children), 5)
                modal.stop()

    async def test_all_category_products_are_reachable_through_pages(self):
        for category, products in CATEGORIAS.items():
            session = CategorySession(
                category,
                "entrada",
                123,
                tuple(products),
            )
            visible_products = []
            for page in range(session.page_count):
                modal = CategoryQuantityModal(session, page)
                visible_products.extend(product for product, _ in modal.inputs)
                modal.stop()

            self.assertEqual(visible_products, products, category)

    async def test_category_navigation_uses_the_page_shown_by_the_view(self):
        session = CategorySession(
            "Teste",
            "entrada",
            123,
            tuple(f"Produto {index}" for index in range(11)),
        )
        session.page = 2
        view = CategoryPageView(session, page=0)
        buttons = {
            child.label: child
            for child in view.children
            if isinstance(child, discord.ui.Button)
        }

        self.assertTrue(buttons["Anterior"].disabled)
        next_button = next(
            child for child in view.children
            if isinstance(child, discord.ui.Button)
            and child.label.startswith("Proxima pagina")
        )
        self.assertEqual(next_button.label, "Proxima pagina (2/3)")

        interaction = SimpleNamespace(
            response=SimpleNamespace(send_modal=AsyncMock())
        )
        await next_button.callback(interaction)
        opened_modal = interaction.response.send_modal.await_args.args[0]
        self.assertEqual(opened_modal.page, 1)
        opened_modal.stop()
        view.stop()

    async def test_opening_next_modal_does_not_advance_session_before_submit(self):
        session = CategorySession(
            "Teste",
            "entrada",
            123,
            tuple(f"Produto {index}" for index in range(6)),
        )

        modal = CategoryQuantityModal(session, 1)

        self.assertEqual(session.page, 0)
        self.assertEqual(modal.page, 1)
        self.assertEqual(len(modal.children), 1)
        modal.stop()

    async def test_zero_and_empty_values_remove_session_quantity(self):
        self.assertEqual(_parse_category_quantity(""), 0)
        self.assertEqual(_parse_category_quantity("0"), 0)
        self.assertEqual(_parse_category_quantity("1.000"), 1000)
        self.assertEqual(_parse_category_quantity("1,000"), 1000)
        self.assertEqual(_parse_category_quantity("1 000"), 1000)
        with self.assertRaises(ValueError):
            _parse_category_quantity("-10")

        session = CategorySession("Teste", "entrada", 123, ("5mm",))
        session.quantities["5mm"] = 10
        if _parse_category_quantity("0") == 0:
            session.quantities.pop("5mm", None)
        self.assertEqual(session.items(), [])

    async def test_category_page_sends_directly_without_review(self):
        session = CategorySession("Teste", "entrada", 123, ("5mm",))
        view = CategoryPageView(session)
        labels = {
            child.label
            for child in view.children
            if isinstance(child, discord.ui.Button)
        }

        self.assertIn("Enviar", labels)
        self.assertNotIn("Revisar", labels)
        self.assertNotIn("Confirmar", labels)
        view.stop()

    async def test_clear_confirmation_requires_administrator(self):
        self.assertTrue(_is_bau_admin(SimpleNamespace(
            user=SimpleNamespace(
                guild_permissions=SimpleNamespace(administrator=True)
            )
        )))
        self.assertFalse(_is_bau_admin(SimpleNamespace(
            user=SimpleNamespace(
                guild_permissions=SimpleNamespace(administrator=False)
            )
        )))

        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(
                id=123,
                guild_permissions=SimpleNamespace(administrator=False),
            ),
            response=response,
        )
        view = ClearConfirmView(123)

        self.assertFalse(await view.interaction_check(interaction))
        response.send_message.assert_awaited_once_with(
            "\u274c Apenas administradores podem zerar o bau.",
            ephemeral=True,
        )
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
