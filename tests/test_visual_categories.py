import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.mod import VISUAL_CATEGORY_NAME, eh_categoria_visual, proteger_categoria_visual


class VisualCategoryPermissionTests(unittest.IsolatedAsyncioTestCase):
    def _category(self, name: str, overwrite: discord.PermissionOverwrite):
        default_role = SimpleNamespace(id=1)
        category = SimpleNamespace(
            name=name,
            guild=SimpleNamespace(default_role=default_role),
            overwrites_for=lambda role: overwrite,
            set_permissions=AsyncMock(),
        )
        return category, default_role

    async def test_visual_category_is_visible_and_not_manageable(self):
        overwrite = discord.PermissionOverwrite(send_messages=False)
        category, default_role = self._category(VISUAL_CATEGORY_NAME, overwrite)

        changed = await proteger_categoria_visual(category)

        self.assertTrue(changed)
        self.assertIs(overwrite.view_channel, True)
        self.assertIs(overwrite.manage_channels, False)
        self.assertIs(overwrite.send_messages, False)
        category.set_permissions.assert_awaited_once_with(
            default_role,
            overwrite=overwrite,
            reason="Protecao da categoria visual do servidor",
        )

    async def test_already_protected_category_does_not_call_discord(self):
        overwrite = discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=False,
        )
        category, _ = self._category(VISUAL_CATEGORY_NAME, overwrite)

        changed = await proteger_categoria_visual(category)

        self.assertFalse(changed)
        category.set_permissions.assert_not_awaited()

    async def test_regular_category_is_ignored(self):
        overwrite = discord.PermissionOverwrite()
        category, _ = self._category("FARM", overwrite)

        changed = await proteger_categoria_visual(category)

        self.assertFalse(changed)
        category.set_permissions.assert_not_awaited()

    def test_recognizes_visual_categories_with_different_lengths(self):
        self.assertTrue(eh_categoria_visual("▬▬▬"))
        self.assertTrue(eh_categoria_visual("▬▬▬▬▬▬▬▬▬▬▬▬"))
        self.assertFalse(eh_categoria_visual("▬▬ FARM ▬▬"))
        self.assertFalse(eh_categoria_visual("▬"))
