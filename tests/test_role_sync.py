import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from core.role_sync import find_role_by_names, sync_role_permissions


class FakeRole:
    def __init__(self, role_id, name, position, permissions=0):
        self.id = role_id
        self.name = name
        self.position = position
        self.permissions = discord.Permissions(permissions)
        self.edit = AsyncMock()

    def __hash__(self):
        return hash(self.id)


class FakeChannel:
    def __init__(self, name, overwrites):
        self.name = name
        self.overwrites = overwrites
        self.set_permissions = AsyncMock()


class RoleSyncTests(unittest.IsolatedAsyncioTestCase):
    def test_encontra_cargo_ignorando_pipe_e_maiusculas(self):
        role = FakeRole(1, "🦺 | FLANELINHA", 1)
        guild = SimpleNamespace(roles=[role])

        found = find_role_by_names(guild, ("Flanelinha",))

        self.assertIs(found, role)

    async def test_copia_permissoes_overwrites_e_posicao(self):
        source = FakeRole(1, "| Membro", 5, permissions=discord.Permissions.send_messages.flag)
        target = FakeRole(2, "Flanelinha", 2)
        source_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
        )
        copied_channel = FakeChannel("membros", {source: source_overwrite})
        clean_channel = FakeChannel(
            "privado",
            {target: discord.PermissionOverwrite(view_channel=False)},
        )
        unchanged_channel = FakeChannel("geral", {})
        guild = SimpleNamespace(
            channels=[copied_channel, clean_channel, unchanged_channel],
            edit_role_positions=AsyncMock(),
        )

        result = await sync_role_permissions(
            guild,
            source,
            target,
            reason="test",
            disable_invites=True,
        )

        source.edit.assert_awaited_once()
        source_permissions = source.edit.await_args.kwargs["permissions"]
        self.assertFalse(source_permissions.create_instant_invite)
        target.edit.assert_awaited_once()
        edited_permissions = target.edit.await_args.kwargs["permissions"]
        self.assertFalse(edited_permissions.create_instant_invite)
        expected_permissions = discord.Permissions(source.permissions.value)
        expected_permissions.create_instant_invite = False
        self.assertEqual(edited_permissions.value, expected_permissions.value)

        copied_calls = copied_channel.set_permissions.await_args_list
        self.assertEqual(len(copied_calls), 2)
        self.assertIs(copied_calls[0].args[0], source)
        self.assertFalse(
            copied_calls[0].kwargs["overwrite"].create_instant_invite
        )
        self.assertIs(copied_calls[1].args[0], target)
        self.assertFalse(
            copied_calls[1].kwargs["overwrite"].create_instant_invite
        )

        clean_calls = clean_channel.set_permissions.await_args_list
        self.assertEqual(len(clean_calls), 2)
        self.assertIs(clean_calls[0].args[0], source)
        self.assertFalse(clean_calls[0].kwargs["overwrite"].create_instant_invite)
        self.assertIs(clean_calls[1].args[0], target)
        self.assertFalse(clean_calls[1].kwargs["overwrite"].create_instant_invite)

        unchanged_channel.set_permissions.assert_has_awaits(
            [
                unittest.mock.call(
                    source,
                    overwrite=unittest.mock.ANY,
                    reason="test",
                ),
                unittest.mock.call(
                    target,
                    overwrite=unittest.mock.ANY,
                    reason="test",
                ),
            ]
        )
        clean_channel.set_permissions.assert_any_await(
            target,
            overwrite=unittest.mock.ANY,
            reason="test",
        )
        guild.edit_role_positions.assert_awaited_once_with(
            positions={target: 4},
            reason="test",
        )
        self.assertEqual(result.copied_overwrites, 3)
        self.assertEqual(result.removed_overwrites, 0)
        self.assertEqual(result.unchanged_channels, 0)
        self.assertTrue(result.moved)

    async def test_move_correto_quando_flanelinha_esta_acima(self):
        source = FakeRole(1, "Membro", 5)
        target = FakeRole(2, "Flanelinha", 8)
        guild = SimpleNamespace(channels=[], edit_role_positions=AsyncMock())

        await sync_role_permissions(guild, source, target, reason="test")

        guild.edit_role_positions.assert_awaited_once_with(
            positions={target: 5},
            reason="test",
        )


if __name__ == "__main__":
    unittest.main()
