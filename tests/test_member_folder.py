import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from services.set_service import (
    MemberFolderError,
    member_folder_access_roles,
    parse_member_folder,
    resolve_member_folder,
    sync_member_folder_manager_overwrites,
)


class FakeTextChannel:
    def __init__(self, channel_id, name, category_id, member_id=None):
        self.id = channel_id
        self.name = name
        self.category_id = category_id
        target = type("Target", (), {"id": member_id})()
        self.overwrites = {target: SimpleNamespace(view_channel=True)} if member_id else {}


class FakeCategory:
    def __init__(self, channels):
        self.text_channels = channels


class FakeRole:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id


class FakeGuild:
    def __init__(self, roles, category):
        self.roles = roles
        self.category = category

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    def get_channel(self, channel_id):
        return self.category if channel_id == 40 else None


class FakePermissionChannel:
    def __init__(self, name, overwrites):
        self.name = name
        self.overwrites = dict(overwrites)
        self.set_permissions = AsyncMock(side_effect=self._set_permissions)

    async def _set_permissions(self, target, *, overwrite=None, reason=None):
        if overwrite is None:
            self.overwrites.pop(target, None)
            return
        self.overwrites[target] = overwrite

    def overwrites_for(self, role):
        return self.overwrites.get(role, discord.PermissionOverwrite())


class MemberFolderParsingTests(unittest.TestCase):
    def test_parses_production_folder_name(self):
        identity = parse_member_folder("┃📁-1-pedro-henrique-11704", 99)
        self.assertEqual(identity.channel_id, 99)
        self.assertEqual(identity.slot, 1)
        self.assertEqual(identity.nickname, "Pedro Henrique")
        self.assertEqual(identity.game_id, "11704")

    def test_parses_admin_folder_with_slot_zero(self):
        identity = parse_member_folder("┃📁-0-mineiro-6627", 99)

        self.assertEqual(identity.slot, 0)
        self.assertEqual(identity.nickname, "Mineiro")
        self.assertEqual(identity.game_id, "6627")

    def test_rejects_free_or_incomplete_shape(self):
        with self.assertRaises(MemberFolderError):
            parse_member_folder("┃📁-22-livre", 99)
        with self.assertRaises(MemberFolderError):
            parse_member_folder("┃📁-0-mineiro", 99)


class MemberFolderPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_filtra_apenas_gerentes_nao_permitidos(self):
        geral = FakeRole(1, "| Gerente Geral")
        farm = FakeRole(2, "| Gerente de Farm")
        producao = FakeRole(3, "| Gerente de Producao")
        acao = FakeRole(4, "| Gerente de Acao")
        lider = FakeRole(5, "| Lider")
        guild = FakeGuild([geral, farm, producao, acao, lider], None)

        roles = member_folder_access_roles(guild, [1, 2, 3, 4, 5])

        self.assertEqual([role.id for role in roles], [1, 2, 5])

    async def test_sincroniza_pastas_mantendo_so_gerentes_permitidos(self):
        geral = FakeRole(1, "| Gerente Geral")
        farm = FakeRole(2, "| Gerente de Farm")
        producao = FakeRole(3, "| Gerente de Producao")
        acao = FakeRole(4, "| Gerente de Acao")
        lider = FakeRole(5, "| Lider")
        member = FakeRole(99, "Membro")
        channel = FakePermissionChannel(
            "pasta",
            {
                farm: discord.PermissionOverwrite(view_channel=True),
                producao: discord.PermissionOverwrite(view_channel=True),
                acao: discord.PermissionOverwrite(view_channel=True),
                lider: discord.PermissionOverwrite(view_channel=True),
                member: discord.PermissionOverwrite(view_channel=True),
            },
        )
        guild = FakeGuild(
            [geral, farm, producao, acao, lider],
            FakeCategory([channel]),
        )

        result = await sync_member_folder_manager_overwrites(
            guild,
            40,
            [1, 2, 3, 4, 5],
        )

        self.assertIn(geral, channel.overwrites)
        self.assertIn(farm, channel.overwrites)
        self.assertIn(lider, channel.overwrites)
        self.assertIn(member, channel.overwrites)
        self.assertNotIn(producao, channel.overwrites)
        self.assertNotIn(acao, channel.overwrites)
        self.assertTrue(channel.overwrites[geral].view_channel)
        self.assertTrue(channel.overwrites[geral].send_messages)
        self.assertTrue(channel.overwrites[geral].read_message_history)
        self.assertEqual(result.checked_channels, 1)
        self.assertEqual(result.updated_channels, 1)
        self.assertEqual(result.removed_overwrites, 2)
        self.assertEqual(result.ensured_overwrites, 2)


class MemberFolderResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_channel_map_first(self):
        member = SimpleNamespace(id=10)
        channel = FakeTextChannel(50, "┃📁-7-mineiro-6627", 40, 10)
        guild = SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == 50 else None)
        with (
            patch("services.set_service.db_channel_map_get", return_value=50),
            patch("services.set_service.discord.TextChannel", FakeTextChannel),
        ):
            identity = await resolve_member_folder(guild, "1", member, 40)
        self.assertEqual((identity.slot, identity.nickname, identity.game_id), (7, "Mineiro", "6627"))

    async def test_falls_back_to_unique_explicit_permission(self):
        member = SimpleNamespace(id=10)
        channel = FakeTextChannel(51, "┃📁-12-maria-silva-4455", 40, 10)
        category = FakeCategory([channel])
        guild = SimpleNamespace(get_channel=lambda channel_id: category if channel_id == 40 else None)
        with (
            patch("services.set_service.db_channel_map_get", return_value=None),
            patch("services.set_service.discord.CategoryChannel", FakeCategory),
        ):
            identity = await resolve_member_folder(guild, "1", member, 40)
        self.assertEqual((identity.slot, identity.nickname, identity.game_id), (12, "Maria Silva", "4455"))

    async def test_rejects_ambiguous_folders(self):
        member = SimpleNamespace(id=10)
        channels = [
            FakeTextChannel(51, "┃📁-1-maria-4455", 40, 10),
            FakeTextChannel(52, "┃📁-2-maria-4455", 40, 10),
        ]
        category = FakeCategory(channels)
        guild = SimpleNamespace(get_channel=lambda channel_id: category if channel_id == 40 else None)
        with (
            patch("services.set_service.db_channel_map_get", return_value=None),
            patch("services.set_service.discord.CategoryChannel", FakeCategory),
        ):
            with self.assertRaises(MemberFolderError):
                await resolve_member_folder(guild, "1", member, 40)

    async def test_admin_uses_unique_slot_zero_folder_without_explicit_overwrite(self):
        member = SimpleNamespace(
            id=10,
            guild_permissions=SimpleNamespace(administrator=True),
        )
        channel = FakeTextChannel(50, "┃📁-0-mineiro-6627", 40)
        category = FakeCategory([channel])
        guild = SimpleNamespace(
            get_channel=lambda channel_id: category if channel_id == 40 else None
        )
        with (
            patch("services.set_service.db_channel_map_get", return_value=None),
            patch("services.set_service.discord.CategoryChannel", FakeCategory),
        ):
            identity = await resolve_member_folder(guild, "1", member, 40)

        self.assertEqual(
            (identity.channel_id, identity.slot, identity.nickname, identity.game_id),
            (50, 0, "Mineiro", "6627"),
        )

    async def test_regular_member_cannot_claim_admin_slot_zero_folder(self):
        member = SimpleNamespace(
            id=10,
            guild_permissions=SimpleNamespace(administrator=False),
        )
        channel = FakeTextChannel(50, "┃📁-0-mineiro-6627", 40)
        category = FakeCategory([channel])
        guild = SimpleNamespace(
            get_channel=lambda channel_id: category if channel_id == 40 else None
        )
        with (
            patch("services.set_service.db_channel_map_get", return_value=None),
            patch("services.set_service.discord.CategoryChannel", FakeCategory),
        ):
            with self.assertRaises(MemberFolderError):
                await resolve_member_folder(guild, "1", member, 40)


if __name__ == "__main__":
    unittest.main()
