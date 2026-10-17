import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.acao_painel import _build_painel_embed
from ui.views.acao import (
    ACAO_CONTAINER_CUSTOM_ID,
    ACAO_CONTAINER_TEST_CUSTOM_ID,
    AcaoContainerPanelView,
)


class AcaoContainerPanelTests(unittest.IsolatedAsyncioTestCase):
    def test_view_uses_components_v2_and_preserves_initial_panel_text(self):
        view = AcaoContainerPanelView()

        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertIsInstance(view.children[0], discord.ui.Container)

        embed = _build_painel_embed()
        text_displays = [
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        ]
        self.assertEqual(text_displays[0].content, f"# {embed.title}")
        self.assertEqual(text_displays[1].content, embed.description)
        self.assertEqual(text_displays[2].content, embed.footer.text)

        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].custom_id, ACAO_CONTAINER_CUSTOM_ID)
        self.assertEqual(buttons[0].label, "⚡ Iniciar Ação")
        self.assertNotIn("acao:entrar", {button.custom_id for button in buttons})
        self.assertNotIn("acao:encerrar", {button.custom_id for button in buttons})

    async def test_button_delegates_to_existing_action_panel_callback(self):
        view = AcaoContainerPanelView()
        legacy_callback = AsyncMock()
        view._legacy_button.callback = legacy_callback
        interaction = SimpleNamespace()
        button = next(item for item in view.walk_children() if isinstance(item, discord.ui.Button))

        await button.callback(interaction)

        legacy_callback.assert_awaited_once_with(interaction)

    def test_test_namespace_remains_available_for_existing_test_messages(self):
        view = AcaoContainerPanelView(custom_id=ACAO_CONTAINER_TEST_CUSTOM_ID)
        button = next(item for item in view.walk_children() if isinstance(item, discord.ui.Button))

        self.assertEqual(button.custom_id, ACAO_CONTAINER_TEST_CUSTOM_ID)


if __name__ == "__main__":
    unittest.main()
