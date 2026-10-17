import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from config.paineis import PAINEL_OPERACOES_CONFIG
from ui.views.operacoes import (
    PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS,
    PAINEL_OPERACOES_CONTAINER_TEST_CUSTOM_IDS,
    PainelOperacoesContainerView,
)


class PainelOperacoesContainerTests(unittest.IsolatedAsyncioTestCase):
    def test_view_uses_components_v2_and_preserves_panel_text(self):
        view = PainelOperacoesContainerView()

        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertIsInstance(view.children[0], discord.ui.Container)

        text_displays = [
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        ]
        self.assertEqual(text_displays[0].content, f"# {PAINEL_OPERACOES_CONFIG['titulo']}")
        self.assertEqual(text_displays[1].content, PAINEL_OPERACOES_CONFIG["descricao"])
        self.assertEqual(text_displays[2].content, "Use os botões abaixo para navegar")

        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
        self.assertEqual(
            {button.custom_id for button in buttons},
            set(PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS.values()),
        )

    async def test_buttons_delegate_to_legacy_panel_callbacks(self):
        view = PainelOperacoesContainerView()
        interaction = SimpleNamespace()

        for legacy_custom_id, container_custom_id in PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS.items():
            with self.subTest(legacy_custom_id=legacy_custom_id):
                legacy_callback = AsyncMock()
                view._legacy_buttons[legacy_custom_id].callback = legacy_callback
                button = next(
                    item
                    for item in view.walk_children()
                    if getattr(item, "custom_id", None) == container_custom_id
                )

                await button.callback(interaction)

                legacy_callback.assert_awaited_once_with(interaction)

    def test_test_namespace_remains_available(self):
        view = PainelOperacoesContainerView(
            custom_ids=PAINEL_OPERACOES_CONTAINER_TEST_CUSTOM_IDS,
        )
        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]

        self.assertEqual(
            {button.custom_id for button in buttons},
            set(PAINEL_OPERACOES_CONTAINER_TEST_CUSTOM_IDS.values()),
        )


if __name__ == "__main__":
    unittest.main()
