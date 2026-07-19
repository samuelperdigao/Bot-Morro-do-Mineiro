import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.bau_gerentes import (
    BauGerentesPainelView,
    can_manage_bau_gerentes,
)
from cogs.disparo import BroadcastView, can_manage_broadcast


def member_with_permissions(*, manage_guild: bool):
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(manage_guild=manage_guild),
    )


def interaction_for(member):
    return SimpleNamespace(
        user=member,
        response=SimpleNamespace(send_message=AsyncMock()),
    )


class SecurityPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_broadcast_permission_helper(self):
        self.assertTrue(can_manage_broadcast(member_with_permissions(manage_guild=True)))
        self.assertFalse(can_manage_broadcast(member_with_permissions(manage_guild=False)))

    def test_bau_gerentes_permission_helper(self):
        self.assertTrue(can_manage_bau_gerentes(member_with_permissions(manage_guild=True)))
        self.assertFalse(can_manage_bau_gerentes(member_with_permissions(manage_guild=False)))

    async def test_broadcast_panel_rejects_regular_member(self):
        interaction = interaction_for(member_with_permissions(manage_guild=False))

        allowed = await BroadcastView().interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_bau_gerentes_panel_rejects_regular_member(self):
        interaction = interaction_for(member_with_permissions(manage_guild=False))

        allowed = await BauGerentesPainelView().interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_authorized_members_can_use_both_panels(self):
        interaction = interaction_for(member_with_permissions(manage_guild=True))

        self.assertTrue(await BroadcastView().interaction_check(interaction))
        self.assertTrue(await BauGerentesPainelView().interaction_check(interaction))
        interaction.response.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
