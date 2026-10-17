import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.disparo import build_broadcast_embed
from ui.views.disparo import BROADCAST_CONTAINER_CUSTOM_IDS, BroadcastContainerView


class BroadcastContainerViewTests(unittest.IsolatedAsyncioTestCase):
    def test_view_uses_components_v2_and_preserves_panel_content(self):
        view = BroadcastContainerView()
        embed = build_broadcast_embed()

        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertIsInstance(view.children[0], discord.ui.Container)
        self.assertEqual(len(view.children[0].children), 10)

        text_displays = [
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        ]
        self.assertEqual(text_displays[0].content, f"# {embed.title}")
        self.assertEqual(text_displays[1].content, embed.description)
        for display, field in zip(text_displays[2:-1], embed.fields):
            self.assertEqual(display.content, f"**{field.name}**\n{field.value}")
        self.assertEqual(text_displays[-1].content, embed.footer.text)

        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
        self.assertEqual(
            {button.custom_id for button in buttons},
            set(BROADCAST_CONTAINER_CUSTOM_IDS.values()),
        )

    async def test_buttons_delegate_to_legacy_callbacks(self):
        view = BroadcastContainerView()
        interaction = SimpleNamespace()

        for legacy_custom_id, container_custom_id in BROADCAST_CONTAINER_CUSTOM_IDS.items():
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


if __name__ == "__main__":
    unittest.main()
