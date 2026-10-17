import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.farm_painel import _build_painel_embed, _is_farm_panel_message
from ui.views.farm import (
    FARM_CONTAINER_CUSTOM_IDS,
    FARM_CONTAINER_TEST_CUSTOM_IDS,
    FarmContainerPanelView,
)


class FarmContainerPanelTests(unittest.IsolatedAsyncioTestCase):
    def test_view_uses_components_v2_without_public_launch_actions(self):
        view = FarmContainerPanelView()

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
        self.assertEqual(
            {button.custom_id for button in buttons},
            set(FARM_CONTAINER_CUSTOM_IDS.values()),
        )
        self.assertNotIn("farm_container:lancar", {button.custom_id for button in buttons})
        self.assertNotIn("farm_container:lancar_dinheiro", {button.custom_id for button in buttons})
        self.assertTrue(all("Lançar Farm" not in (button.label or "") for button in buttons))

    async def test_buttons_delegate_to_existing_farm_panel_callbacks(self):
        view = FarmContainerPanelView()
        interaction = SimpleNamespace()

        for legacy_custom_id, container_custom_id in FARM_CONTAINER_CUSTOM_IDS.items():
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

    def test_test_namespace_remains_available_for_existing_test_messages(self):
        view = FarmContainerPanelView(custom_ids=FARM_CONTAINER_TEST_CUSTOM_IDS)
        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]

        self.assertEqual(
            {button.custom_id for button in buttons},
            set(FARM_CONTAINER_TEST_CUSTOM_IDS.values()),
        )

    def test_repost_recognizes_nested_container_button_ids(self):
        nested_button = SimpleNamespace(custom_id="farm_container:abrir_ticket")
        action_row = SimpleNamespace(children=[nested_button])
        container = SimpleNamespace(children=[action_row])
        message = SimpleNamespace(
            author=SimpleNamespace(id=123),
            embeds=[],
            components=[container],
        )

        self.assertTrue(_is_farm_panel_message(message, SimpleNamespace(id=123)))


if __name__ == "__main__":
    unittest.main()
