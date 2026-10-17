import unittest
from types import SimpleNamespace

import discord

from cogs.set_views import SetModal
from config.paineis import PAINEL_SET_CONFIG
from ui.views.set import SET_CONTAINER_TEST_CUSTOM_ID, SetContainerPanelView


class SetContainerPanelTests(unittest.IsolatedAsyncioTestCase):
    def test_view_uses_components_v2_and_is_persistent(self):
        view = SetContainerPanelView()

        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertIsInstance(view.children[0], discord.ui.Container)

        text_displays = [
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        ]
        self.assertEqual(text_displays[0].content, f"# {PAINEL_SET_CONFIG['titulo']}")
        self.assertEqual(text_displays[1].content, PAINEL_SET_CONFIG["descricao"])

        component_types = [type(item) for item in view.children[0].children]
        self.assertEqual(
            component_types,
            [
                discord.ui.TextDisplay,
                discord.ui.Separator,
                discord.ui.TextDisplay,
                discord.ui.Separator,
                discord.ui.ActionRow,
                discord.ui.TextDisplay,
            ],
        )

        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].custom_id, SET_CONTAINER_TEST_CUSTOM_ID)
        self.assertEqual(buttons[0].label, "📝 Pedir Set")

    async def test_button_reuses_set_modal_flow(self):
        view = SetContainerPanelView()
        button = next(item for item in view.walk_children() if isinstance(item, discord.ui.Button))

        class FakeResponse:
            def __init__(self):
                self.modal = None

            async def send_modal(self, modal):
                self.modal = modal

        response = FakeResponse()
        interaction = SimpleNamespace(response=response)

        await button.callback(interaction)

        self.assertIsInstance(response.modal, SetModal)


if __name__ == "__main__":
    unittest.main()
