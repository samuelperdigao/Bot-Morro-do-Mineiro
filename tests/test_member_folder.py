import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import services.set_service as set_service

from services.set_service import (
    MemberFolderError,
    liberar_pasta,
    member_folder_access_roles,
    organizar_ordem_pastas,
    parse_member_folder,
    proximo_numero_pasta,
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


class MemberFolderOrderingTests(unittest.IsolatedAsyncioTestCase):
    def test_next_number_fills_first_gap(self):
        category = SimpleNamespace(
            channels=[
                SimpleNamespace(name="┃📁-1-joao-10"),
                SimpleNamespace(name="┃📁-3-maria-20"),
            ]
        )
        guild = SimpleNamespace(get_channel=lambda channel_id: category)

        with patch.dict(set_service._ultimo_numero, {}, clear=True):
            self.assertEqual(proximo_numero_pasta(guild, 40), 2)
            self.assertEqual(proximo_numero_pasta(guild, 40), 4)

    async def test_reorders_folders_by_numeric_slot(self):
        channels = [
            SimpleNamespace(id=10, name="┃📁-10-dez-10", position=1),
            SimpleNamespace(id=2, name="┃📁-2-dois-2", position=2),
            SimpleNamespace(id=99, name="avisos", position=3),
            SimpleNamespace(id=1, name="┃📁-1-um-1", position=4),
        ]
        category = SimpleNamespace(text_channels=channels)
        http = SimpleNamespace(bulk_channel_update=AsyncMock())
        guild = SimpleNamespace(
            id=123,
            _state=SimpleNamespace(http=http),
            get_channel=lambda channel_id: category,
        )

        changed = await organizar_ordem_pastas(guild, 40)

        self.assertEqual(changed, 2)
        http.bulk_channel_update.assert_awaited_once()
        payload = http.bulk_channel_update.await_args.args[1]
        self.assertEqual(
            payload,
            [
                {"id": 1, "position": 1},
                {"id": 2, "position": 2},
                {"id": 10, "position": 4},
            ],
        )


class MemberFolderReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_exit_cleans_messages_removes_access_and_marks_free(self):
        events = []
        member_target = FakeRole(10, "Member")
        manager_target = FakeRole(20, "Manager")
        channel = SimpleNamespace(
            id=50,
            name="┃📁-7-mineiro-6627",
            category_id=40,
            overwrites={member_target: "member", manager_target: "manager"},
        )

        async def purge(**kwargs):
            events.append("purge")
            return [1, 2]

        async def edit(**kwargs):
            events.append("edit")
            return None

        channel.purge = AsyncMock(side_effect=purge)
        channel.edit = AsyncMock(side_effect=edit)
        guild = SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == 50 else None)
        member = SimpleNamespace(id=10)

        with (
            patch("services.set_service.db_channel_map_get", return_value=50),
            patch("services.set_service.db_channel_map_delete") as delete_map,
            patch("services.set_service.organizar_ordem_pastas", new=AsyncMock()) as organize,
        ):
            released = await liberar_pasta(guild, member, "1")

        self.assertTrue(released)
        self.assertEqual(events, ["purge", "edit"])
        edit_kwargs = channel.edit.await_args.kwargs
        self.assertEqual(edit_kwargs["name"], "┃📁-7-livre")
        self.assertNotIn(member_target, edit_kwargs["overwrites"])
        self.assertIn(manager_target, edit_kwargs["overwrites"])
        delete_map.assert_called_once_with("1", "10")
        organize.assert_awaited_once()

    async def test_folder_is_not_marked_free_when_cleanup_fails(self):
        channel = SimpleNamespace(
            id=50,
            name="┃📁-7-mineiro-6627",
            category_id=40,
            overwrites={},
            edit=AsyncMock(),
        )
        guild = SimpleNamespace(get_channel=lambda channel_id: channel)

        with (
            patch("services.set_service.db_channel_map_get", return_value=50),
            patch("services.set_service.db_channel_map_delete") as delete_map,
            patch("services.set_service.limpar_mensagens_pasta", new=AsyncMock(return_value=None)),
        ):
            released = await liberar_pasta(guild, SimpleNamespace(id=10), "1")

        self.assertFalse(released)
        channel.edit.assert_not_awaited()
        delete_map.assert_not_called()

    async def test_finds_folder_by_member_overwrite_when_map_is_missing(self):
        member_target = FakeRole(10, "Member")
        channel = SimpleNamespace(
            id=50,
            name="┃📁-7-mineiro-6627",
            category_id=40,
            overwrites={member_target: "member"},
            purge=AsyncMock(return_value=[]),
            edit=AsyncMock(return_value=None),
        )
        category = SimpleNamespace(text_channels=[channel])
        guild = SimpleNamespace(
            get_channel=lambda channel_id: category if channel_id == 40 else None,
        )

        with (
            patch("services.set_service.db_channel_map_get", return_value=None),
            patch(
                "services.set_service.db_get_guild_config",
                return_value={"private_category_id": "40"},
            ),
            patch("services.set_service.db_channel_map_delete") as delete_map,
            patch("services.set_service.organizar_ordem_pastas", new=AsyncMock()),
        ):
            released = await liberar_pasta(guild, SimpleNamespace(id=10), "1")

        self.assertTrue(released)
        channel.purge.assert_awaited_once()
        channel.edit.assert_awaited_once()
        delete_map.assert_called_once_with("1", "10")

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
