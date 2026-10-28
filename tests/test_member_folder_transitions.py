import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cogs.membros import MembrosCog


class FakeRole:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name


class FakeGuild:
    def __init__(self, guild_id=10, roles=None, members=None, category=None):
        self.id = guild_id
        self.roles = roles or []
        self._members = members or {}
        self.category = category

    def get_member(self, member_id):
        return self._members.get(member_id)

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    def get_channel(self, channel_id):
        return self.category if channel_id == 40 else None

    async def fetch_channel(self, channel_id):
        return self.category if channel_id == 40 else None


class FakeMember:
    def __init__(self, member_id, guild, roles, nick):
        self.id = member_id
        self.guild = guild
        self.roles = roles
        self.nick = nick
        self.display_name = nick or "Membro"

    def __str__(self):
        return f"member-{self.id}"


class MemberFolderTransitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.member_role = FakeRole(2, "| Membro")
        self.manager_role = FakeRole(3, "| Gerente de Farm")
        self.vice_role = FakeRole(1474869320684146846, "| 02")
        self.guild = FakeGuild(roles=[self.member_role, self.manager_role, self.vice_role])
        self.bot = SimpleNamespace(guilds=[self.guild])
        self.cog = MembrosCog(self.bot)

    async def test_promotion_releases_only_the_member_folder(self):
        before = FakeMember(20, self.guild, [self.member_role], "[MBR] Jo | 123")
        after = FakeMember(
            20,
            self.guild,
            [self.member_role, self.manager_role],
            "[GRT] Jo | 123",
        )
        release = AsyncMock(return_value=True)

        with (
            patch("cogs.membros.liberar_pasta", release),
            patch("cogs.membros.db_pending_member_folder_delete") as pending_delete,
        ):
            await self.cog.on_member_update(before, after)

        release.assert_awaited_once_with(
            self.guild,
            after,
            "10",
            reason="Pasta individual liberada ao promover cargo de lideranca",
        )
        pending_delete.assert_called_once_with("10", "20")

    async def test_promotion_to_vice_also_releases_member_folder(self):
        before = FakeMember(20, self.guild, [self.member_role], "[MBR] Jo | 123")
        after = FakeMember(
            20,
            self.guild,
            [self.member_role, self.vice_role],
            "[VICE] Jo | 123",
        )
        release = AsyncMock(return_value=True)

        with (
            patch("cogs.membros.liberar_pasta", release),
            patch("cogs.membros.db_pending_member_folder_delete"),
        ):
            await self.cog.on_member_update(before, after)

        release.assert_awaited_once_with(
            self.guild,
            after,
            "10",
            reason="Pasta individual liberada ao promover cargo de lideranca",
        )

    async def test_demotion_assigns_folder_and_records_channel_map(self):
        before = FakeMember(
            20,
            self.guild,
            [self.member_role, self.manager_role],
            "[GRT] Jo | 123",
        )
        after = FakeMember(20, self.guild, [self.member_role], "[MBR] Jo | 123")
        folder = SimpleNamespace(id=50, name="┃📁-7-jo-123")
        create = AsyncMock(return_value=folder)

        with (
            patch("cogs.membros.db_pending_member_folder_set") as pending_set,
            patch("cogs.membros.db_pending_member_folder_exists", return_value=True),
            patch("cogs.membros.db_channel_map_get", return_value=None),
            patch(
                "cogs.membros.db_get_guild_config",
                return_value={"member_role_id": "2", "private_category_id": "40"},
            ),
            patch("cogs.membros.db_get_approver_role_ids", return_value=[5]),
            patch("cogs.membros.criar_pasta", create),
            patch("cogs.membros.db_channel_map_set") as map_set,
            patch("cogs.membros.db_pending_member_folder_delete") as pending_delete,
        ):
            await self.cog.on_member_update(before, after)

        pending_set.assert_called_once_with("10", "20")
        create.assert_awaited_once_with(
            self.guild,
            after,
            after,
            40,
            [5],
            id_jogo="123",
            membro_nome="Jo",
            reason="Pasta de membro atribuida apos rebaixamento de gerente",
        )
        map_set.assert_called_once_with("10", "20", 50)
        pending_delete.assert_called_once_with("10", "20")

    async def test_demotion_from_vice_assigns_member_folder(self):
        before = FakeMember(20, self.guild, [self.member_role, self.vice_role], "[VICE] Jo | 123")
        after = FakeMember(20, self.guild, [self.member_role], "[MBR] Jo | 123")
        folder = SimpleNamespace(id=51, name="┃📁-8-jo-123")

        with (
            patch("cogs.membros.db_pending_member_folder_set"),
            patch("cogs.membros.db_pending_member_folder_exists", return_value=True),
            patch("cogs.membros.db_channel_map_get", return_value=None),
            patch(
                "cogs.membros.db_get_guild_config",
                return_value={"member_role_id": "2", "private_category_id": "40"},
            ),
            patch("cogs.membros.db_get_approver_role_ids", return_value=[]),
            patch("cogs.membros.criar_pasta", new=AsyncMock(return_value=folder)),
            patch("cogs.membros.db_channel_map_set") as map_set,
            patch("cogs.membros.db_pending_member_folder_delete"),
        ):
            await self.cog.on_member_update(before, after)

        map_set.assert_called_once_with("10", "20", 51)

    async def test_missing_game_id_stays_pending_then_retries_on_nickname_change(self):
        before = FakeMember(
            20,
            self.guild,
            [self.member_role, self.manager_role],
            "[GRT] Jo",
        )
        demoted = FakeMember(20, self.guild, [self.member_role], "[MBR] Jo")
        created = SimpleNamespace(id=50, name="┃📁-7-jo-123")
        create = AsyncMock(return_value=created)
        pending_delete = Mock()
        map_set = Mock()

        with (
            patch("cogs.membros.db_pending_member_folder_set") as pending_set,
            patch("cogs.membros.db_pending_member_folder_exists", return_value=True),
            patch("cogs.membros.db_channel_map_get", return_value=None),
            patch(
                "cogs.membros.db_get_guild_config",
                return_value={"member_role_id": "2", "private_category_id": "40"},
            ),
            patch("cogs.membros.db_get_approver_role_ids", return_value=[]),
            patch("cogs.membros.criar_pasta", create),
            patch("cogs.membros.db_channel_map_set", map_set),
            patch("cogs.membros.db_pending_member_folder_delete", pending_delete),
        ):
            await self.cog.on_member_update(before, demoted)
            create.assert_not_awaited()
            map_set.assert_not_called()

            corrected = FakeMember(
                20,
                self.guild,
                [self.member_role],
                "[MBR] Jo | 123",
            )
            await self.cog.on_member_update(demoted, corrected)

        self.assertEqual(pending_set.call_count, 1)
        create.assert_awaited_once()
        map_set.assert_called_once_with("10", "20", 50)
        pending_delete.assert_called_once_with("10", "20")

    async def test_startup_releases_existing_manager_mapping(self):
        manager = FakeMember(
            20,
            self.guild,
            [self.manager_role],
            "[GRT] Jo | 123",
        )
        ordinary_member = FakeMember(
            21,
            self.guild,
            [self.member_role],
            "[MBR] Ana | 456",
        )
        pending_member = FakeMember(
            22,
            self.guild,
            [self.member_role],
            "[MBR] Bia | 789",
        )
        self.guild._members = {20: manager, 21: ordinary_member, 22: pending_member}
        release = AsyncMock(return_value=True)
        folder = SimpleNamespace(id=52, name="┃📁-8-bia-789")
        create = AsyncMock(return_value=folder)

        with (
            patch("cogs.membros.asyncio.sleep", new=AsyncMock()),
            patch(
                "cogs.membros.db_channel_map_all",
                return_value=[("20", 50), ("21", 51)],
            ),
            patch("cogs.membros.db_pending_member_folders_all", return_value=["22"]),
            patch("cogs.membros.db_channel_map_get", return_value=None),
            patch(
                "cogs.membros.db_get_guild_config",
                return_value={"member_role_id": "2", "private_category_id": "40"},
            ),
            patch("cogs.membros.db_get_approver_role_ids", return_value=[]),
            patch("cogs.membros.criar_pasta", create),
            patch("cogs.membros.db_channel_map_set") as map_set,
            patch("cogs.membros.liberar_pasta", release),
            patch("cogs.membros.db_pending_member_folder_delete"),
        ):
            await self.cog._reconciliar_pastas()

        release.assert_awaited_once_with(
            self.guild,
            manager,
            "10",
            reason="Pasta individual liberada na reconciliacao de cargo de lideranca",
        )
        create.assert_awaited_once()
        map_set.assert_called_once_with("10", "22", 52)

    async def test_startup_releases_manager_folder_found_by_individual_overwrite(self):
        manager = FakeMember(
            20,
            self.guild,
            [self.member_role, self.manager_role],
            "[GRT] Jo | 123",
        )
        direct_target = FakeMember(20, self.guild, [], "")
        channel = SimpleNamespace(
            id=60,
            name="┃📁-9-jo-123",
            overwrites={direct_target: SimpleNamespace(view_channel=True)},
        )
        category = SimpleNamespace(text_channels=[channel])
        self.guild.category = category
        self.guild._members = {20: manager}
        release = AsyncMock(return_value=True)

        with (
            patch("cogs.membros.asyncio.sleep", new=AsyncMock()),
            patch("cogs.membros.db_channel_map_all", return_value=[]),
            patch("cogs.membros.db_pending_member_folders_all", return_value=[]),
            patch(
                "cogs.membros.db_get_guild_config",
                return_value={"private_category_id": "40"},
            ),
            patch("cogs.membros.liberar_pasta", release),
        ):
            await self.cog._reconciliar_pastas()

        release.assert_awaited_once_with(
            self.guild,
            manager,
            "10",
            user_id="20",
            channel_id=60,
            reason="Pasta individual liberada na reconciliacao de cargo de lideranca",
        )


if __name__ == "__main__":
    unittest.main()
