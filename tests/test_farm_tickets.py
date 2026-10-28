import asyncio
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import services.db_service as db
from config.paineis import BOTOES_LIDERANCA
from cogs.farm import FarmView
from cogs.farm_painel import (
    FarmPainelView,
    FarmTicketMemberSelectView,
    FarmTicketRoleSelectView,
    LegacyFarmLaunchView,
    fetch_ticket_target_members,
    fetch_ticket_target_roles,
    lock_farm_panel_channel,
)
from cogs.farm_tickets import (
    FarmTicketView,
    FarmTicketsCog,
    build_ticket_view,
    _approval_is_automatic,
    _approval_origin,
    _expanded_admin_role_ids,
    _payload_approval_origin,
    _progress,
    _ticket_sort_key,
    TICKET_ANIMATED_EMOJI_ID,
    TICKET_LOGO_FILENAME,
    TICKET_LOGO_PATH,
    _farm_ticket_channel_base,
    _staff_ticket_identity,
    _resolve_ticket_folder_identity,
    approved_ticket_channel_name,
)
from services.db_service import (
    APROVACAO_ORIGEM_EXPIRACAO,
    APROVACAO_ORIGEM_META,
)
from cogs.recolhimento import (
    RecolhimentoCog,
    RecolhimentoMetaModal,
)


class FakeLogThread:
    def __init__(self, id=200):
        self.id = id
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        attachments = []
        for file in kwargs.get("files") or []:
            attachments.append(
                SimpleNamespace(
                    url=f"https://cdn.example/thread/{getattr(file, 'filename', 'proof.png')}"
                )
            )
        return SimpleNamespace(id=300 + len(self.sent), attachments=attachments)


class FakeLogMessage:
    def __init__(self, id=100):
        self.id = id
        self.thread = None
        self.attachments = []
        self.edit = AsyncMock()

    async def create_thread(self, *, name):
        self.thread = FakeLogThread()
        self.thread.name = name
        return self.thread


class FakeLogChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        message = FakeLogMessage(100 + len(self.sent))
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[int(message_id)]


class FakeLogGuild:
    id = 1

    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel if int(channel_id) == 900 else None

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    def get_thread(self, thread_id):
        message = next(iter(self.channel.messages.values()), None)
        if message and message.thread and message.thread.id == int(thread_id):
            return message.thread
        return None


class FakeAttachment:
    url = "https://cdn.example/original.png"

    async def to_file(self, use_cached=True):
        return SimpleNamespace(filename="proof.png")


class FarmPanelPermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_denies_writes_and_keeps_bot_allowed(self):
        default_role = object()
        allowed_role = object()
        allowed_member = object()
        bot_member = object()
        overwrites = {
            allowed_role: discord.PermissionOverwrite(send_messages=True),
            allowed_member: discord.PermissionOverwrite(
                send_messages=True,
                send_messages_in_threads=True,
            ),
        }
        channel = SimpleNamespace(
            overwrites=overwrites,
            overwrites_for=lambda target: overwrites.get(
                target, discord.PermissionOverwrite()
            ),
            set_permissions=AsyncMock(),
        )
        guild = SimpleNamespace(default_role=default_role, me=bot_member)

        changed = await lock_farm_panel_channel(channel, guild)

        self.assertEqual(changed, 4)
        applied = {
            call.args[0]: call.kwargs["overwrite"]
            for call in channel.set_permissions.await_args_list
        }
        for target in (default_role, allowed_role, allowed_member):
            self.assertFalse(applied[target].send_messages)
            self.assertFalse(applied[target].send_messages_in_threads)
        self.assertTrue(applied[bot_member].send_messages)


class FarmTicketDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "farm.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def _create_ticket(self):
        ticket, created = db.db_ticket_reserve("1", "2026-06-15", "10", "Membro")
        self.assertTrue(created)
        db.db_ticket_activate(int(ticket["id"]), "100", "200")
        return db.db_ticket_get(int(ticket["id"]))

    def _ticket_panel(self, *, approved=False):
        ticket = db.db_ticket_get(1)
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )
        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
            approved=approved,
        )

        return view, self._view_text(view)

    @staticmethod
    def _view_text(view):
        parts = []

        def collect_text(component):
            if isinstance(component, discord.ui.TextDisplay):
                parts.append(component.content)
            for child in getattr(component, "children", ()):
                collect_text(child)

        for item in view.children:
            collect_text(item)
        return "\n".join(parts)

    def test_ticket_panel_container_shows_zero_partial_and_complete_progress(self):
        db.db_set_meta("1", "2026-06-15", {"Ferro": 100}, "99")
        ticket = self._create_ticket()

        view, text = self._ticket_panel()
        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertIn("CENTRAL DE FARM", text)
        self.assertIn(
            "# <:ChatGPTImage27deagode202620_11_1:1542674742916419644> CENTRAL DE FARM",
            text,
        )
        self.assertIn("OPERAÇÃO ATIVA", text)
        self.assertIn(">>> ## 01  /  PROGRESSO DA SEMANA", text)
        self.assertIn(">>> ## 02  /  ENTREGAS DA SEMANA", text)
        self.assertIn(">>> ## 03  /  ACOMPANHAMENTO", text)
        self.assertIn(">>> ## 04  /  HISTÓRICO RECENTE", text)
        self.assertIn("**0% CONCLUÍDO**", text)
        self.assertIn(f"`{'▱' * 42}`", text)
        self.assertIn("restante `100`", text)

        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        view, text = self._ticket_panel()
        self.assertIn("**50% CONCLUÍDO**", text)
        self.assertIn("`50` / `100`", text)
        self.assertIn("LANÇAMENTO 01", text)

        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 50},
            "101", "301", "https://cdn.example/proof2.png", None,
        )
        view, text = self._ticket_panel()
        self.assertIn("**100% CONCLUÍDO**", text)
        self.assertIn(f"`{'▰' * 42}`", text)
        self.assertIn("✅ **Ferro**", text)
        self.assertIn("✓ META ATINGIDA", text)

        db.db_aprovar("1", "2026-06-15", "10", "99")
        view, text = self._ticket_panel(approved=True)
        self.assertIn("✓ META APROVADA", text)
        self.assertIn("Aprovada por <@99>", text)
        db.db_ticket_add_action(
            int(ticket["id"]),
            "aprovacao",
            "0",
            payload={
                "aprovacao_automatica": True,
                "origem": APROVACAO_ORIGEM_META,
            },
        )
        view, text = self._ticket_panel(approved=True)
        self.assertIn("Aprovada automaticamente ao atingir", text)

        ticket = dict(db.db_ticket_get(int(ticket["id"])))
        ticket["status"] = "revisao"
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )
        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
        )
        self.assertIn("⚠️ EM REVISÃO", self._view_text(view))

        ticket["status"] = "finalizado"
        view = build_ticket_view(
            ticket, member, db.db_get_meta("1", "2026-06-15")
        )
        self.assertIn("🔒 FINALIZADO", self._view_text(view))

    def test_ticket_panel_container_preserves_action_ids_and_disabled_states(self):
        ticket = self._create_ticket()
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )
        meta = db.db_get_meta("1", "2026-06-15")
        active = build_ticket_view(ticket, member, meta)
        container_items = active.children[0].children
        self.assertIsInstance(active.children[0], discord.ui.Container)
        header = container_items[0]
        self.assertIsInstance(header, discord.ui.Section)
        self.assertIsInstance(header.accessory, discord.ui.Thumbnail)
        self.assertEqual(header.accessory.media.url, "https://cdn.example/avatar.png")
        self.assertEqual(header.accessory.description, "Foto de perfil de Membro")
        self.assertTrue(TICKET_LOGO_PATH.is_file())
        galleries = [child for child in container_items if isinstance(child, discord.ui.MediaGallery)]
        self.assertEqual(len(galleries), 1)
        self.assertEqual(
            galleries[0].items[0].media.url,
            f"attachment://{TICKET_LOGO_FILENAME}",
        )
        action_rows = [child for child in container_items if isinstance(child, discord.ui.ActionRow)]
        self.assertEqual(len(action_rows), 2)
        self.assertEqual([len(row.children) for row in action_rows], [4, 3])
        self.assertEqual(container_items[-2:], action_rows)
        self.assertIn("AÇÕES DO TICKET", container_items[-3].content)
        separators = [child for child in container_items if isinstance(child, discord.ui.Separator)]
        self.assertEqual(
            [child.spacing for child in separators],
            [discord.SeparatorSpacing.large] * 4 + [discord.SeparatorSpacing.small] * 2,
        )
        quoted_displays = [
            child.content
            for child in container_items
            if isinstance(child, discord.ui.TextDisplay)
        ]
        self.assertEqual(len(quoted_displays), 5)
        self.assertTrue(all(content.startswith(">>> ") for content in quoted_displays[:4]))
        self.assertTrue(quoted_displays[4].startswith("### AÇÕES DO TICKET"))
        items = [child for row in container_items if isinstance(row, discord.ui.ActionRow) for child in row.children]
        expected = {item.custom_id for item in FarmTicketView().children}
        self.assertEqual({item.custom_id for item in items}, expected)

        finalized = dict(ticket)
        finalized["status"] = "finalizado"
        db.db_aprovar("1", "2026-06-15", "10", "99")
        view = build_ticket_view(finalized, member, meta, finalized=True, approved=True)
        self.assertTrue(view.to_components())
        items = [child for row in view.children[0].children if isinstance(row, discord.ui.ActionRow) for child in row.children]
        self.assertTrue(all(item.disabled for item in items if item.custom_id != "farm_ticket:proofs"))
        self.assertFalse(next(item for item in items if item.custom_id == "farm_ticket:proofs").disabled)

    def test_ticket_panel_uses_server_animated_emoji_in_section_titles(self):
        ticket = self._create_ticket()
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )

        class AnimatedEmoji:
            id = TICKET_ANIMATED_EMOJI_ID
            name = "mdm_animado"
            animated = True

            def __str__(self):
                return f"<a:{self.name}:{self.id}>"

        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
            guild=SimpleNamespace(emojis=[AnimatedEmoji()]),
        )

        text = self._view_text(view)
        self.assertEqual(
            text.count(f"<a:mdm_animado:{TICKET_ANIMATED_EMOJI_ID}>"),
            2,
        )
        self.assertIn(">>> ## 01  /  PROGRESSO DA SEMANA", text)

    def test_ticket_panel_uses_requested_emoji_in_central_title_even_when_static(self):
        self.assertEqual(TICKET_ANIMATED_EMOJI_ID, 1542674742916419644)
        ticket = self._create_ticket()
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )

        class CentralEmoji:
            id = TICKET_ANIMATED_EMOJI_ID
            name = "central_farm"
            animated = False

            def __str__(self):
                return f"<:{self.name}:{self.id}>"

        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
            guild=SimpleNamespace(emojis=[CentralEmoji()]),
        )

        self.assertIn(
            f"# <:central_farm:{TICKET_ANIMATED_EMOJI_ID}> CENTRAL DE FARM",
            self._view_text(view),
        )

    def test_ticket_panel_formats_member_folder_and_game_id_without_duplicates(self):
        ticket = dict(self._create_ticket())
        ticket["folder_slot"] = 0
        ticket["folder_nickname"] = "Mineiro"
        ticket["game_id"] = "6627"
        member = SimpleNamespace(
            id=10,
            display_name="[LÍDER] Mineiro | 6627",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )

        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
        )
        text = self._view_text(view)

        self.assertIn("**Membro**  ·  Mineiro", text)
        self.assertIn("`PASTA 00`  ·  **ID do jogo** `6627`", text)
        self.assertNotIn("<@10>", text)
        self.assertNotIn("ID `10`", text)
        self.assertNotIn("[LÍDER] Mineiro | 6627", text)

    def test_ticket_panel_uses_an_available_animated_emoji_when_preferred_one_is_static(self):
        ticket = self._create_ticket()
        member = SimpleNamespace(
            id=10,
            display_name="Membro",
            mention="<@10>",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        )

        class StaticEmoji:
            id = TICKET_ANIMATED_EMOJI_ID
            animated = False

        class AvailableAnimatedEmoji:
            id = 1541575597438795876
            name = "download4"
            animated = True

            def __str__(self):
                return f"<a:{self.name}:{self.id}>"

        view = build_ticket_view(
            ticket,
            member,
            db.db_get_meta("1", "2026-06-15"),
            guild=SimpleNamespace(emojis=[StaticEmoji(), AvailableAnimatedEmoji()]),
        )

        self.assertEqual(
            self._view_text(view).count("<a:download4:1541575597438795876>"),
            1,
        )

    def test_refresh_ticket_keeps_existing_files_and_adds_original_logo(self):
        ticket = {
            "id": 1,
            "guild_id": "1",
            "channel_id": "200",
            "panel_message_id": "300",
            "user_id": "10",
            "week_id": "2026-06-15",
            "status": "aberto",
        }
        proof_attachment = SimpleNamespace(filename="proof.png")
        message = SimpleNamespace(
            attachments=[proof_attachment],
            edit=AsyncMock(),
        )
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        member = SimpleNamespace(id=10)
        guild = SimpleNamespace(
            get_channel=lambda channel_id: channel,
            get_member=lambda member_id: member,
            fetch_member=AsyncMock(),
        )
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: guild)

        with unittest.mock.patch(
            "cogs.farm_tickets.db_ticket_get", return_value=ticket
        ), unittest.mock.patch(
            "cogs.farm_tickets.db_get_progresso", return_value=None
        ), unittest.mock.patch(
            "cogs.farm_tickets.db_get_meta", return_value={}
        ), unittest.mock.patch(
            "cogs.farm_tickets.build_ticket_view", return_value=object()
        ):
            asyncio.run(cog.refresh_ticket(1))

        message.edit.assert_awaited_once()
        attachments = message.edit.await_args.kwargs["attachments"]
        self.assertIs(attachments[0], proof_attachment)
        self.assertEqual(attachments[1].filename, TICKET_LOGO_FILENAME)
        self.assertEqual(attachments[1].fp.name, str(TICKET_LOGO_PATH))
        attachments[1].close()

        existing_logo = SimpleNamespace(filename=TICKET_LOGO_FILENAME)
        message.attachments = [proof_attachment, existing_logo]
        with unittest.mock.patch(
            "cogs.farm_tickets.db_ticket_get", return_value=ticket
        ), unittest.mock.patch(
            "cogs.farm_tickets.db_get_progresso", return_value=None
        ), unittest.mock.patch(
            "cogs.farm_tickets.db_get_meta", return_value={}
        ), unittest.mock.patch(
            "cogs.farm_tickets.build_ticket_view", return_value=object()
        ):
            asyncio.run(cog.refresh_ticket(1))

        second_attachments = message.edit.await_args.kwargs["attachments"]
        self.assertEqual(second_attachments, [proof_attachment, existing_logo])

    def _create_log_cog(self):
        db.db_set_system_config("1", "farm", None, "900")
        channel = FakeLogChannel()
        guild = FakeLogGuild(channel)
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 1 else None)
        return cog, channel

    def test_approved_channel_name_is_idempotent_and_respects_discord_limit(self):
        self.assertEqual(approved_ticket_channel_name("farm-01-mineiro-123"), "✅-farm-01-mineiro-123")
        self.assertEqual(approved_ticket_channel_name("✅-farm-01-mineiro-123"), "✅-farm-01-mineiro-123")
        self.assertEqual(len(approved_ticket_channel_name("x" * 100)), 100)

    def test_ticket_sort_key_uses_numeric_folder_slot(self):
        self.assertLess(
            _ticket_sort_key({"id": 1, "folder_slot": 2}),
            _ticket_sort_key({"id": 2, "folder_slot": 10}),
        )
        self.assertLess(
            _ticket_sort_key({"id": 3, "folder_slot": 10}),
            _ticket_sort_key({"id": 4, "folder_slot": 10}),
        )
        self.assertGreater(
            _ticket_sort_key({"id": 5, "folder_slot": None}),
            _ticket_sort_key({"id": 6, "folder_slot": 10}),
        )

    def test_approved_ticket_channel_is_renamed_without_duplicate_marker(self):
        ticket, _ = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Membro", folder_slot=1
        )
        db.db_ticket_activate(int(ticket["id"]), "100", "200")
        db.db_aprovar("1", "2026-06-15", "10", "99")

        class FakeTicketChannel:
            def __init__(self):
                self.name = "farm-01-mineiro-123"
                self.edit = AsyncMock()

        channel = FakeTicketChannel()
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        with unittest.mock.patch("cogs.farm_tickets.discord.TextChannel", FakeTicketChannel):
            changed = asyncio.run(
                cog.sync_approved_channel_name(db.db_ticket_get(int(ticket["id"])), channel)
            )

        self.assertTrue(changed)
        channel.edit.assert_awaited_once_with(
            name="✅-farm-01-mineiro-123",
            reason="Ticket de farm aprovado",
        )

    def test_unapproved_ticket_channel_is_not_renamed(self):
        ticket, _ = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Membro", folder_slot=1
        )
        db.db_ticket_activate(int(ticket["id"]), "100", "200")

        class FakeTicketChannel:
            name = "farm-01-mineiro-123"

            def __init__(self):
                self.edit = AsyncMock()

        channel = FakeTicketChannel()
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        with unittest.mock.patch("cogs.farm_tickets.discord.TextChannel", FakeTicketChannel):
            changed = asyncio.run(
                cog.sync_approved_channel_name(db.db_ticket_get(int(ticket["id"])), channel)
            )

        self.assertFalse(changed)
        channel.edit.assert_not_awaited()

    def test_ticket_category_is_reordered_by_numeric_folder_slot(self):
        tickets = []
        channels = []
        for ticket_id, slot in ((1, 10), (2, 2), (3, 1)):
            ticket, _ = db.db_ticket_reserve(
                "1", "2026-06-15", str(ticket_id), f"Membro {ticket_id}", folder_slot=slot
            )
            db.db_ticket_activate(int(ticket["id"]), str(100 + ticket_id), "200")
            tickets.append(ticket)

        class FakeTicketChannel:
            def __init__(self, channel_id, name):
                self.id = channel_id
                self.name = name
                self.category_id = 700
                self.moves = []

            async def move(self, **kwargs):
                self.moves.append(kwargs)

        channels = [
            FakeTicketChannel(101, "farm-10"),
            FakeTicketChannel(102, "farm-02"),
            FakeTicketChannel(103, "farm-01"),
        ]

        class FakeCategory:
            id = 700

            def __init__(self, channels):
                self.guild = SimpleNamespace(id=1)
                self.text_channels = channels

        category = FakeCategory(channels)
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        with unittest.mock.patch("cogs.farm_tickets.discord.TextChannel", FakeTicketChannel), \
             unittest.mock.patch("cogs.farm_tickets.discord.CategoryChannel", FakeCategory):
            asyncio.run(cog.reorder_ticket_category(category))

        self.assertTrue(channels[2].moves[0]["beginning"])
        self.assertIs(channels[1].moves[0]["after"], channels[2])
        self.assertIs(channels[0].moves[0]["after"], channels[1])

    def test_ticket_category_keeps_farm_panel_at_top(self):
        db.db_set_system_config("1", "farm", "999", None)
        for ticket_id, slot in ((1, 10), (2, 2), (3, 1)):
            ticket, _ = db.db_ticket_reserve(
                "1", "2026-06-15", str(ticket_id), f"Membro {ticket_id}", folder_slot=slot
            )
            db.db_ticket_activate(int(ticket["id"]), str(100 + ticket_id), "200")

        class FakeChannel:
            def __init__(self, channel_id, name):
                self.id = channel_id
                self.name = name
                self.moves = []

            async def move(self, **kwargs):
                self.moves.append(kwargs)

        panel = FakeChannel(999, "farm-painel")
        ticket_10 = FakeChannel(101, "farm-10")
        ticket_02 = FakeChannel(102, "farm-02")
        ticket_01 = FakeChannel(103, "farm-01")

        class FakeCategory:
            id = 700

            def __init__(self, channels):
                self.guild = SimpleNamespace(id=1)
                self.text_channels = channels

        category = FakeCategory([ticket_10, panel, ticket_02, ticket_01])
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        with unittest.mock.patch("cogs.farm_tickets.discord.CategoryChannel", FakeCategory):
            asyncio.run(cog.reorder_ticket_category(category))

        self.assertTrue(panel.moves[0]["beginning"])
        self.assertIs(ticket_01.moves[0]["after"], panel)
        self.assertIs(ticket_02.moves[0]["after"], ticket_01)
        self.assertIs(ticket_10.moves[0]["after"], ticket_02)

    def test_reconciliation_marks_existing_finalized_approved_ticket(self):
        ticket, _ = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Membro", folder_slot=1
        )
        db.db_ticket_activate(int(ticket["id"]), "100", "200")
        db.db_ticket_finalize(int(ticket["id"]), "99", "Finalizado")
        db.db_aprovar("1", "2026-06-15", "10", "99")

        class FakeTicketChannel:
            id = 100
            name = "farm-01-mineiro-123"
            category_id = 700

            def __init__(self):
                self.edit = AsyncMock()

        class FakeCategory:
            id = 700
            text_channels = []

            def __init__(self):
                self.guild = SimpleNamespace(id=1)

        channel = FakeTicketChannel()
        category = FakeCategory()
        category.text_channels = [channel]

        class FakeGuild:
            id = 1

            def get_channel(self, channel_id):
                return {100: channel, 700: category}.get(int(channel_id))

            async def fetch_channel(self, channel_id):
                return self.get_channel(channel_id)

        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: FakeGuild())
        with unittest.mock.patch("cogs.farm_tickets.discord.TextChannel", FakeTicketChannel), \
             unittest.mock.patch("cogs.farm_tickets.discord.CategoryChannel", FakeCategory):
            asyncio.run(cog.reconcile_existing_ticket_channels())

        channel.edit.assert_awaited_once_with(
            name="✅-farm-01-mineiro-123",
            reason="Ticket de farm aprovado",
        )

    def test_ticket_is_unique_per_member_and_week(self):
        first, created = db.db_ticket_reserve("1", "2026-06-15", "10", "Membro")
        second, created_again = db.db_ticket_reserve("1", "2026-06-15", "10", "Outro nome")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])

    def test_member_can_open_another_ticket_after_finalization(self):
        first = self._create_ticket()
        self.assertTrue(db.db_ticket_finalize(int(first["id"]), "99", "Concluído"))

        second, created = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Membro"
        )

        self.assertTrue(created)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "criando")

        active, created_again = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Membro"
        )
        self.assertFalse(created_again)
        self.assertEqual(second["id"], active["id"])

    def test_ticket_keeps_folder_identity_snapshot(self):
        ticket, created = db.db_ticket_reserve(
            "1", "2026-06-15", "10", "Mineiro",
            folder_channel_id="500", folder_slot=1,
            game_id="6627", folder_nickname="Mineiro",
        )
        self.assertTrue(created)
        self.assertEqual(ticket["folder_channel_id"], "500")
        self.assertEqual(ticket["folder_slot"], 1)
        self.assertEqual(ticket["game_id"], "6627")
        self.assertEqual(ticket["folder_nickname"], "Mineiro")

    def test_ticket_launch_adds_to_general_progress_without_claiming_legacy_event(self):
        db.db_lancar("1", "2026-06-15", "10", {"Borracha": 100})
        ticket = self._create_ticket()
        event_id, _ = db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", "parcial",
        )

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(db.db_prog_itens(progress)["Borracha"], 150)
        launches = db.db_ticket_launches(int(ticket["id"]))
        self.assertEqual([row["id"] for row in launches], [event_id])
        self.assertEqual(db.db_evento_itens(launches[0]), {"Borracha": 50})
        self.assertEqual(len(db.db_eventos_usuario("1", "2026-06-15", "10")), 2)

    def test_legacy_and_ticket_launches_share_weekly_goal_progress(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 150}, "99")
        db.db_lancar("1", "2026-06-15", "10", {"Borracha": 100})
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(db.db_prog_itens(progress), {"Borracha": 150})
        self.assertEqual(len(db.db_ticket_launches(int(ticket["id"]))), 1)
        _, delivered, percentage, completed, _ = _progress(
            ticket, db.db_get_meta("1", "2026-06-15")
        )
        self.assertEqual(delivered, {"Borracha": 150})
        self.assertEqual(percentage, 100)
        self.assertTrue(completed)

    def test_failed_reservation_cleanup_does_not_remove_ticket_with_launches(self):
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 1},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        db.db_ticket_release_failed(int(ticket["id"]))
        self.assertIsNotNone(db.db_ticket_get(int(ticket["id"])))

    def test_expired_open_ticket_is_selected_for_deadline_closure(self):
        ticket = self._create_ticket()
        expired = db.db_ticket_expired("2026-06-22")
        self.assertEqual([row["id"] for row in expired], [ticket["id"]])
        self.assertEqual(db.db_ticket_expired("2026-06-15"), [])

    def test_manual_delete_preserves_launches_and_progress(self):
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 5},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        db.db_ticket_mark_manual_deleted(int(ticket["id"]), "99", "Exclusão administrativa")

        deleted = db.db_ticket_get(int(ticket["id"]))
        self.assertEqual(deleted["status"], "finalizado")
        self.assertIsNone(deleted["channel_id"])
        self.assertIsNotNone(deleted["excluido_em"])
        self.assertEqual(len(db.db_ticket_launches(int(ticket["id"]))), 1)
        self.assertEqual(db.db_prog_itens(db.db_get_progresso("1", "2026-06-15", "10"))["Ferro"], 5)

    def test_pending_log_blocks_manual_deletion(self):
        ticket = self._create_ticket()
        action_id = db.db_ticket_add_action(int(ticket["id"]), "abertura", "10")
        self.assertTrue(db.db_ticket_has_pending_logs(int(ticket["id"])))
        db.db_ticket_set_log_result(action_id, message_id="500")
        self.assertFalse(db.db_ticket_has_pending_logs(int(ticket["id"])))

    def test_ticket_action_log_creates_summary_and_thread(self):
        ticket = self._create_ticket()
        action_id = db.db_ticket_add_action(int(ticket["id"]), "abertura", "10")
        cog, channel = self._create_log_cog()
        actor = SimpleNamespace(id=10, mention="<@10>")

        logged = asyncio.run(
            cog.send_action_log(ticket, action_id, "Ticket aberto", actor, "Semana 15/06/2026")
        )

        self.assertTrue(logged)
        self.assertEqual(len(channel.sent), 1)
        summary = next(iter(channel.messages.values()))
        self.assertIsNotNone(summary.thread)
        self.assertEqual(len(summary.thread.sent), 1)
        updated = db.db_ticket_get(int(ticket["id"]))
        self.assertEqual(updated["log_message_id"], str(summary.id))
        self.assertEqual(updated["log_thread_id"], str(summary.thread.id))
        self.assertFalse(db.db_ticket_has_pending_logs(int(ticket["id"])))

    def test_ticket_log_member_uses_nickname_when_user_id_is_invalid(self):
        ticket = dict(self._create_ticket())
        ticket["user_id"] = "%5020808747556874"
        ticket["folder_nickname"] = "Caxias Bondi | 32929"
        ticket["member_name"] = "5020808747556874"
        cog = FarmTicketsCog.__new__(FarmTicketsCog)

        embed = cog.build_ticket_action_embed(
            ticket,
            "Canal de ticket excluido",
            SimpleNamespace(id=1, mention="@Admin"),
            "Retencao encerrada",
        )

        self.assertEqual(embed.fields[0].name, "Membro")
        self.assertEqual(embed.fields[0].value, "Caxias Bondi | 32929")

    def test_ticket_launch_log_copies_proof_to_thread(self):
        ticket = self._create_ticket()
        event_id, action_id = db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/original.png", "parcial",
        )
        cog, channel = self._create_log_cog()
        actor = SimpleNamespace(id=10, mention="<@10>")
        proof_message = SimpleNamespace(content="parcial")

        asyncio.run(
            cog.log_launch(
                ticket,
                actor,
                event_id,
                action_id,
                {"Borracha": 50},
                proof_message,
                FakeAttachment(),
            )
        )

        summary = next(iter(channel.messages.values()))
        self.assertEqual(len(channel.sent), 1)
        self.assertEqual(len(summary.thread.sent), 1)
        launch = db.db_ticket_launches(int(ticket["id"]))[0]
        self.assertEqual(launch["log_proof_url"], "https://cdn.example/thread/proof.png")
        self.assertFalse(db.db_ticket_has_pending_logs(int(ticket["id"])))

    def test_ticket_launch_log_identifies_actor(self):
        ticket = self._create_ticket()
        event_id, action_id = db.db_ticket_launch(
            int(ticket["id"]), "99", {"Borracha": 50},
            "100", "300", "https://cdn.example/original.png", "parcial",
        )
        cog, channel = self._create_log_cog()
        actor = SimpleNamespace(id=99, mention="<@99>")
        proof_message = SimpleNamespace(content="parcial")

        asyncio.run(
            cog.log_launch(
                ticket,
                actor,
                event_id,
                action_id,
                {"Borracha": 50},
                proof_message,
                FakeAttachment(),
            )
        )

        summary = next(iter(channel.messages.values()))
        embed = summary.thread.sent[0]["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Lancado por"], "<@99>")

    def test_config_is_separate_from_existing_farm_configuration(self):
        db.db_ticket_config_set("1", [11, 12], [21, 22])
        config = db.db_ticket_config_get("1")
        self.assertEqual(config["category_ids"], ["11", "12"])
        self.assertEqual(config["admin_role_ids"], ["21", "22"])
        self.assertIsNone(db.db_get_guild_config("1"))

    def test_gerente_produtos_inherits_ticket_admin_from_gerente_producao(self):
        producao = SimpleNamespace(id=21, name="| Gerente de Produção")
        produtos = SimpleNamespace(id=22, name="| Gerente de Produtos")
        guild = SimpleNamespace(roles=[producao, produtos])

        self.assertEqual(_expanded_admin_role_ids(guild, ["21"]), [21, 22])

    def test_exact_farm_ticket_operator_roles_are_allowed(self):
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        admin = SimpleNamespace(
            id=1,
            roles=[],
            guild_permissions=SimpleNamespace(administrator=True),
        )
        gerente_farm = SimpleNamespace(
            id=2,
            roles=[SimpleNamespace(id=20, name="| Gerente de Farm")],
            guild_permissions=SimpleNamespace(administrator=False),
        )
        gerente_geral = SimpleNamespace(
            id=3,
            roles=[SimpleNamespace(id=30, name="Gerente Geral")],
            guild_permissions=SimpleNamespace(administrator=False),
        )
        gerente_produtos = SimpleNamespace(
            id=4,
            roles=[SimpleNamespace(id=40, name="Gerente de Produtos")],
            guild_permissions=SimpleNamespace(administrator=False),
        )
        manage_guild_only = SimpleNamespace(
            id=5,
            roles=[],
            guild_permissions=SimpleNamespace(
                administrator=False,
                manage_guild=True,
            ),
        )

        self.assertTrue(cog.is_ticket_operator(admin))
        self.assertTrue(cog.is_ticket_operator(gerente_farm))
        self.assertTrue(cog.is_ticket_operator(gerente_geral))
        self.assertFalse(cog.is_ticket_operator(gerente_produtos))
        self.assertFalse(cog.is_ticket_operator(manage_guild_only))

    def test_manager_launch_credits_ticket_owner_and_records_actor(self):
        ticket = self._create_ticket()
        event_id, action_id = db.db_ticket_launch(
            int(ticket["id"]), "99", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", "gerente lancou",
        )

        progress_owner = db.db_get_progresso("1", "2026-06-15", "10")
        progress_actor = db.db_get_progresso("1", "2026-06-15", "99")
        action = db.db_ticket_latest_action(int(ticket["id"]), "lancamento")

        self.assertEqual(db.db_prog_itens(progress_owner), {"Borracha": 50})
        self.assertIsNone(progress_actor)
        self.assertEqual(action["actor_id"], "99")
        self.assertEqual(action["event_id"], event_id)
        self.assertEqual(action["id"], action_id)

    def test_completed_ticket_can_be_approved_without_listing_other_members(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        ticket = db.db_ticket_get(int(ticket["id"]))
        meta = db.db_get_meta("1", "2026-06-15")
        self.assertTrue(_progress(ticket, meta)[3])

        db.db_aprovar("1", "2026-06-15", "10", "20")
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovada_por"], "20")

    def test_admin_can_approve_partial_ticket_by_manual_decision(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 97},
            "100", "300", "https://cdn.example/proof.png", None,
        )

        async def invoke():
            view = FarmTicketView()
            button = next(
                item for item in view.children
                if item.custom_id == "farm_ticket:approve"
            )
            self.assertFalse(button.disabled)
            response = SimpleNamespace(send_message=AsyncMock())
            ticket_cog = SimpleNamespace(
                is_admin=lambda member, guild_id: True,
                send_action_log=AsyncMock(return_value=True),
                refresh_ticket=AsyncMock(),
            )
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=100,
                guild=SimpleNamespace(),
                user=SimpleNamespace(id=99),
                client=SimpleNamespace(
                    get_cog=lambda name: (
                        ticket_cog if name == "FarmTicketsCog" else None
                    )
                ),
                response=response,
            )
            await button.callback(interaction)
            return response, ticket_cog

        response, ticket_cog = asyncio.run(invoke())

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovacao_antecipada"], 1)
        self.assertEqual(progress["aprovacao_nivel"], "meta_batida")
        ranking = db.db_ranking_semana("1", "2026-06-15", ["10"])
        self.assertEqual(ranking[0]["classificacao"], "meta_batida")
        action = db.db_ticket_latest_action(int(ticket["id"]), "aprovacao")
        payload = json.loads(action["payload_json"])
        self.assertFalse(payload["meta_atingida_no_ticket"])
        self.assertEqual(payload["percentual_no_momento"], 97.0)
        ticket_cog.refresh_ticket.assert_awaited_once_with(int(ticket["id"]))
        response.send_message.assert_awaited_once()

    def _create_auto_approval_cog(self):
        cog, channel = self._create_log_cog()
        get_guild = cog.bot.get_guild
        cog.bot = SimpleNamespace(
            get_guild=get_guild,
            get_cog=lambda name: None,
            user=SimpleNamespace(id=7, mention="<@7>"),
        )
        return cog, channel

    def test_reaching_the_goal_approves_the_ticket_automatically(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog, _ = self._create_auto_approval_cog()

        approved = asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))

        self.assertTrue(approved)
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovada_por"], "7")
        self.assertEqual(progress["aprovacao_antecipada"], 0)
        self.assertIsNone(progress["aprovacao_nivel"])
        action = db.db_ticket_latest_action(int(ticket["id"]), "aprovacao")
        payload = json.loads(action["payload_json"])
        self.assertTrue(payload["aprovacao_automatica"])
        self.assertFalse(payload["aprovacao_manual"])
        self.assertEqual(payload["percentual_no_momento"], 100.0)
        self.assertTrue(_approval_is_automatic(db.db_ticket_get(int(ticket["id"]))))

        self.assertFalse(
            asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))
        )
        actions = db.get_conn().execute(
            "SELECT COUNT(*) AS total FROM farm_ticket_actions WHERE ticket_id=? AND action='aprovacao'",
            (int(ticket["id"]),),
        ).fetchone()
        self.assertEqual(actions["total"], 1)

    def test_partial_ticket_is_not_approved_automatically(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 99},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog, _ = self._create_auto_approval_cog()

        approved = asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))

        self.assertFalse(approved)
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 0)
        self.assertIsNone(db.db_ticket_latest_action(int(ticket["id"]), "aprovacao"))

    def test_ticket_in_review_is_not_approved_automatically(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        event_id, _ = db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        db.db_ticket_set_review(int(ticket["id"]), event_id, "99", "Comprovante duvidoso")
        cog, _ = self._create_auto_approval_cog()

        self.assertFalse(
            asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))
        )
        self.assertEqual(db.db_get_progresso("1", "2026-06-15", "10")["aprovada"], 0)

        db.db_ticket_resolve_review(int(ticket["id"]), event_id, "99")

        self.assertTrue(
            asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))
        )
        self.assertEqual(db.db_get_progresso("1", "2026-06-15", "10")["aprovada"], 1)

    def test_manual_approval_still_wins_over_automatic_flag(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 20},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        db.db_aprovar("1", "2026-06-15", "10", "42", antecipada=True, nivel="parcial")
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 30},
            "100", "301", "https://cdn.example/proof.png", None,
        )
        cog, _ = self._create_auto_approval_cog()

        self.assertFalse(
            asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))
        )
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada_por"], "42")
        self.assertEqual(progress["aprovacao_nivel"], "parcial")

    def test_goal_approval_records_the_meta_origin(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 50}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog, _ = self._create_auto_approval_cog()

        asyncio.run(cog.auto_approve_if_completed(int(ticket["id"])))

        atualizado = db.db_ticket_get(int(ticket["id"]))
        self.assertEqual(_approval_origin(atualizado), APROVACAO_ORIGEM_META)

    def test_expired_ticket_approval_uses_the_same_automatic_key(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 40},
            "100", "300", "https://cdn.example/proof.png", None,
        )

        db.db_ticket_finalize_with_auto_approval(
            int(ticket["id"]), "99",
            "Ticket expirado - aprovação automática",
            action="prazo_encerrado",
        )

        action = db.db_ticket_latest_action(int(ticket["id"]), "aprovacao")
        payload = json.loads(action["payload_json"])
        self.assertTrue(payload["aprovacao_automatica"])
        self.assertEqual(payload["origem"], APROVACAO_ORIGEM_EXPIRACAO)
        atualizado = db.db_ticket_get(int(ticket["id"]))
        self.assertTrue(_approval_is_automatic(atualizado))
        self.assertEqual(_approval_origin(atualizado), APROVACAO_ORIGEM_EXPIRACAO)

    def test_legacy_automatic_key_is_read_as_expiration(self):
        self.assertEqual(
            _payload_approval_origin({"automatica": True}, "aprovacao"),
            APROVACAO_ORIGEM_EXPIRACAO,
        )
        self.assertEqual(
            _payload_approval_origin({"aprovacao_automatica": True}, "aprovacao"),
            APROVACAO_ORIGEM_EXPIRACAO,
        )
        self.assertEqual(
            _payload_approval_origin(
                {"aprovacao_automatica": True, "origem": APROVACAO_ORIGEM_META},
                "aprovacao",
            ),
            APROVACAO_ORIGEM_META,
        )
        self.assertIsNone(_payload_approval_origin({"automatica": True}, "finalizacao"))
        self.assertIsNone(_payload_approval_origin({"aprovacao_manual": True}, "aprovacao"))

    def test_manual_approval_has_no_automatic_origin(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()
        db.db_ticket_add_action(
            int(ticket["id"]), "aprovacao", "42",
            payload={"aprovacao_manual": True, "percentual_no_momento": 40.0},
        )

        atualizado = db.db_ticket_get(int(ticket["id"]))
        self.assertIsNone(_approval_origin(atualizado))
        self.assertFalse(_approval_is_automatic(atualizado))

    def test_manual_approval_also_works_with_zero_progress(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")

        db.db_aprovar(
            "1",
            "2026-06-15",
            "10",
            "99",
            antecipada=True,
            nivel="meta_batida",
        )

        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertIsNotNone(progress)
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovacao_nivel"], "meta_batida")

    def test_finalizing_ticket_auto_approves_partial_delivery_once(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Borracha": 40},
            "100", "300", "https://cdn.example/proof.png", None,
        )

        result = db.db_ticket_finalize_with_auto_approval(
            int(ticket["id"]),
            "99",
            "Ticket expirado - aprovação automática",
            action="prazo_encerrado",
        )

        self.assertTrue(result["processed"])
        finalized = db.db_ticket_get(int(ticket["id"]))
        self.assertEqual(finalized["status"], "finalizado")
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovacao_antecipada"], 1)
        self.assertEqual(progress["aprovacao_nivel"], "parcial")
        logs = db.db_ticket_finalization_logs(int(ticket["id"]))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["item"], "Borracha")
        self.assertEqual(logs[0]["quantidade_meta"], 100)
        self.assertEqual(logs[0]["quantidade_entregue"], 40)
        self.assertEqual(logs[0]["status_final"], "APROVADA_PARCIAL")
        self.assertIsNotNone(db.db_ticket_latest_action(int(ticket["id"]), "aprovacao"))

        second = db.db_ticket_finalize_with_auto_approval(
            int(ticket["id"]),
            "99",
            "Ticket expirado - aprovação automática",
            action="prazo_encerrado",
        )

        self.assertFalse(second["processed"])
        self.assertEqual(len(db.db_ticket_finalization_logs(int(ticket["id"]))), 1)
        actions = db.get_conn().execute(
            "SELECT COUNT(*) AS total FROM farm_ticket_actions WHERE ticket_id=? AND action='aprovacao'",
            (int(ticket["id"]),),
        ).fetchone()
        self.assertEqual(actions["total"], 1)

    def test_finalizing_ticket_with_no_delivery_logs_sem_entrega(self):
        db.db_set_meta("1", "2026-06-15", {"Borracha": 100}, "99")
        ticket = self._create_ticket()

        result = db.db_ticket_finalize_with_auto_approval(
            int(ticket["id"]),
            "99",
            "Ticket expirado - aprovação automática",
            action="prazo_encerrado",
        )

        self.assertTrue(result["processed"])
        progress = db.db_get_progresso("1", "2026-06-15", "10")
        self.assertEqual(progress["aprovada"], 1)
        self.assertEqual(progress["aprovacao_nivel"], "zero")
        logs = db.db_ticket_finalization_logs(int(ticket["id"]))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["quantidade_entregue"], 0)
        self.assertEqual(logs[0]["status_final"], "SEM_ENTREGA")

    def test_operations_panel_no_longer_contains_general_approval(self):
        custom_ids = {button["custom_id"] for button in BOTOES_LIDERANCA}
        self.assertNotIn("painel:aprovar_farm", custom_ids)

    def test_ticket_panel_contains_collection_button(self):
        async def custom_ids():
            return {item.custom_id for item in FarmTicketView().children}

        self.assertIn("farm_ticket:collection", asyncio.run(custom_ids()))

    def test_finalized_ticket_disables_collection_button(self):
        async def disabled():
            view = FarmTicketView(finalized=True)
            collection = next(
                item for item in view.children
                if item.custom_id == "farm_ticket:collection"
            )
            return collection.disabled

        self.assertTrue(asyncio.run(disabled()))

    def test_collection_button_rejects_non_admin_member(self):
        ticket = self._create_ticket()

        async def invoke():
            view = FarmTicketView()
            button = next(
                item for item in view.children
                if item.custom_id == "farm_ticket:collection"
            )
            response = SimpleNamespace(send_message=AsyncMock())
            ticket_cog = SimpleNamespace(is_admin=lambda member, guild_id: False)
            interaction = SimpleNamespace(
                guild_id=int(ticket["guild_id"]),
                channel_id=int(ticket["channel_id"]),
                user=SimpleNamespace(id=10),
                client=SimpleNamespace(
                    get_cog=lambda name: ticket_cog if name == "FarmTicketsCog" else None
                ),
                response=response,
            )
            await button.callback(interaction)
            return response

        response = asyncio.run(invoke())
        response.send_message.assert_awaited_once_with(
            "Sem permissão administrativa.", ephemeral=True
        )

    def test_ticket_collection_uses_weekly_colete_meta_and_reuses_cycle(self):
        original = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15",
            {"Ferro": 100, "Plastico": 80, "Tecido": 60},
            "99", meta_tipo="colete",
        )
        db.get_conn().execute(
            """UPDATE farm_tickets
               SET folder_channel_id='500', folder_nickname='Mineiro', folder_slot=7
               WHERE id=?""",
            (original["id"],),
        )
        db.get_conn().commit()
        ticket = db.db_ticket_get(int(original["id"]))
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def modals():
            return (
                cog._modal_recolhimento_ticket(ticket, "99"),
                cog._modal_recolhimento_ticket(ticket, "98"),
            )

        first, second = asyncio.run(modals())

        self.assertIsInstance(first, RecolhimentoMetaModal)
        self.assertEqual(first.meta_tipo, "colete")
        self.assertEqual(first.item_names, ["Ferro", "Plastico", "Tecido"])
        self.assertEqual(first.ciclo_id, second.ciclo_id)
        self.assertEqual(first.alvo_user_id, ticket["user_id"])
        self.assertEqual(first.alvo_nome, "Mineiro")
        self.assertEqual(first.alvo_pasta_id, "500")
        self.assertEqual(first.alvo_slot, 7)

    def test_collection_posts_receipt_in_ticket_with_member_admin_and_slot(self):
        original = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15", {"Ferro": 100}, "99", meta_tipo="colete"
        )
        db.get_conn().execute(
            """UPDATE farm_tickets
               SET folder_channel_id='500', folder_nickname='Mineiro', folder_slot=7
               WHERE id=?""",
            (original["id"],),
        )
        db.get_conn().commit()
        ticket = db.db_ticket_get(int(original["id"]))
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 12},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def submit():
            modal = cog._modal_recolhimento_ticket(ticket, "99")
            modal.inputs[0]._value = modal.inputs[0].default
            response = SimpleNamespace(send_message=AsyncMock())
            channel = SimpleNamespace(send=AsyncMock())
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=99),
                response=response,
                channel=channel,
            )
            await modal.on_submit(interaction)
            return response, channel

        response, channel = asyncio.run(submit())

        response.send_message.assert_awaited_once()
        channel.send.assert_awaited_once()
        embed = channel.send.await_args.kwargs["embed"]
        self.assertIn(f"<@{ticket['user_id']}>", embed.description)
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["📋 Quantidades recolhidas"], "• **Ferro:** 12")
        self.assertEqual(fields["👮 Recolhido por"], "<@99>")
        self.assertEqual(fields["📁 Slot da pasta"], "`07`")
        self.assertEqual(
            embed.footer.text,
            "O saldo disponível foi atualizado automaticamente.",
        )

    def test_collection_balance_tracks_launches_and_previous_collections(self):
        ticket = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15", {"Ferro": 600}, "99", meta_tipo="colete"
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 300},
            "100", "300", "https://cdn.example/first.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def collect_first_launch():
            modal = cog._modal_recolhimento_ticket(ticket, "99")
            self.assertEqual(modal.inputs[0].label, "Ferro | disponível: 300")
            self.assertEqual(modal.inputs[0].default, "300")
            modal.inputs[0]._value = modal.inputs[0].default
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock()),
                channel=SimpleNamespace(send=AsyncMock()),
            )
            await modal.on_submit(interaction)

            empty_modal = cog._modal_recolhimento_ticket(ticket, "99")
            self.assertEqual(empty_modal.inputs[0].label, "Ferro | disponível: 0")
            self.assertEqual(empty_modal.inputs[0].default, "0")

            db.db_ticket_launch(
                int(ticket["id"]), "10", {"Ferro": 300},
                "100", "301", "https://cdn.example/second.png", None,
            )
            replenished_modal = cog._modal_recolhimento_ticket(ticket, "99")
            self.assertEqual(
                replenished_modal.inputs[0].label,
                "Ferro | disponível: 300",
            )
            self.assertEqual(replenished_modal.inputs[0].default, "300")

        asyncio.run(collect_first_launch())

    def test_collection_modal_aggregates_all_launches_and_prefills_every_item(self):
        ticket = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15",
            {"Ferro": 600, "Plastico": 100},
            "99",
            meta_tipo="colete",
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 300, "Plastico": 20},
            "100", "300", "https://cdn.example/first.png", None,
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 125, "Plastico": 30},
            "100", "301", "https://cdn.example/second.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def open_modal():
            return cog._modal_recolhimento_ticket(
                db.db_ticket_get(int(ticket["id"])), "99"
            )

        modal = asyncio.run(open_modal())

        self.assertEqual(modal.item_names, ["Ferro", "Plastico"])
        self.assertEqual([field.default for field in modal.inputs], ["425", "50"])

    def test_collection_submit_without_editing_defaults_recollects_all_available(self):
        ticket = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15", {"Ferro": 100, "Plastico": 80}, "99", meta_tipo="colete"
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 60, "Plastico": 25},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def submit():
            modal = cog._modal_recolhimento_ticket(db.db_ticket_get(int(ticket["id"])), "99")
            for field in modal.inputs:
                field._value = field.default
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock()),
                channel=SimpleNamespace(send=AsyncMock()),
            )
            await modal.on_submit(interaction)
            return modal, interaction

        modal, interaction = asyncio.run(submit())

        entregas = db.db_recolhimento_get_entregas(modal.ciclo_id)
        self.assertEqual(len(entregas), 1)
        self.assertEqual(
            db.db_recolhimento_entrega_itens(entregas[0]),
            {"Ferro": 60, "Plastico": 25},
        )
        interaction.response.send_message.assert_awaited_once()
        interaction.channel.send.assert_awaited_once()

    def test_collection_rejects_value_above_available_balance(self):
        ticket = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15", {"Ferro": 100}, "99", meta_tipo="colete"
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 50},
            "100", "300", "https://cdn.example/proof.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def overcollect():
            modal = cog._modal_recolhimento_ticket(ticket, "99")
            modal.inputs[0]._value = "51"
            response = SimpleNamespace(send_message=AsyncMock())
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=99),
                response=response,
                channel=SimpleNamespace(send=AsyncMock()),
            )
            await modal.on_submit(interaction)
            return modal, response, interaction

        modal, response, interaction = asyncio.run(overcollect())

        self.assertEqual(db.db_recolhimento_get_entregas(modal.ciclo_id), [])
        response.send_message.assert_awaited_once()
        self.assertIn("disponível 50", response.send_message.await_args.args[0])
        interaction.channel.send.assert_not_awaited()

    def test_legacy_overcollection_does_not_consume_future_launches(self):
        ticket = self._create_ticket()
        db.db_set_meta(
            "1", "2026-06-15",
            {"Ferro": 300, "Tecido": 30},
            "99",
            meta_tipo="colete",
        )
        ciclo_id = db.db_recolhimento_criar_ciclo(
            "1", "99", ticket["channel_id"], "colete",
            ticket["week_id"], "2026-06-21",
        )
        db.db_recolhimento_add_entrega_itens(
            ciclo_id,
            "99",
            {"Ferro": 600, "Tecido": 60},
            ticket["user_id"],
            ticket["member_name"],
        )
        db.db_ticket_launch(
            int(ticket["id"]), "10", {"Ferro": 11, "Tecido": 11},
            "100", "300", "https://cdn.example/new.png", None,
        )
        cog = RecolhimentoCog.__new__(RecolhimentoCog)

        async def labels():
            modal = cog._modal_recolhimento_ticket(ticket, "99")
            return [field.label for field in modal.inputs]

        self.assertEqual(
            asyncio.run(labels()),
            ["Ferro | disponível: 11", "Tecido | disponível: 11"],
        )

    def test_collection_items_support_dynamic_names(self):
        ticket = self._create_ticket()
        ciclo_id = db.db_recolhimento_criar_ciclo(
            "1", "99", ticket["channel_id"], "colete",
            ticket["week_id"], "2026-06-21",
        )
        db.db_recolhimento_add_entrega_itens(
            ciclo_id, "99", {"Ferro": 12, "Tecido": 8},
            ticket["user_id"], ticket["member_name"], "500",
        )

        entrega = db.db_recolhimento_get_entregas(ciclo_id)[0]
        self.assertEqual(
            db.db_recolhimento_entrega_itens(entrega),
            {"Ferro": 12, "Tecido": 8},
        )

    def test_current_farm_panels_only_offer_ticket_launch(self):
        async def labels():
            fixed = {item.label for item in FarmPainelView().children}
            personal = {
                item.label for item in FarmView(None, "1", "2026-06-15", "10").children
            }
            return fixed, personal

        fixed_labels, personal_labels = asyncio.run(labels())
        self.assertEqual(
            fixed_labels,
            {
                "🎫 Abrir Ticket Semanal",
                "👥 Abrir para Membro",
                "👥 Abrir Ticket por Cargo",
                "🗑️ Excluir Ticket",
            },
        )
        self.assertIn("🎫 Abrir Ticket de Farm", personal_labels)
        self.assertNotIn("🚜 Lançar Farm", fixed_labels)
        self.assertNotIn("💵 Lançar Dinheiro", fixed_labels | personal_labels)

    def test_ticket_member_pages_include_every_human_by_server_nickname(self):
        class FakeGuild:
            def __init__(self, members):
                self._members = members

            async def fetch_members(self, *, limit=None):
                self.requested_limit = limit
                for member in self._members:
                    yield member

        members = [
            SimpleNamespace(
                id=index,
                display_name=f"Apelido {index:02d}",
                name=f"usuario{index}",
                bot=False,
            )
            for index in range(1, 61)
        ]
        members.append(
            SimpleNamespace(id=999, display_name="Bot", name="bot", bot=True)
        )
        guild = FakeGuild(list(reversed(members)))

        async def collect_options():
            targets = await fetch_ticket_target_members(guild)
            values = []
            labels = []
            for page in range(3):
                view = FarmTicketMemberSelectView(None, targets, page)
                select = view.children[0]
                values.extend(option.value for option in select.options)
                labels.extend(option.label for option in select.options)
            return targets, values, labels

        targets, values, labels = asyncio.run(collect_options())
        self.assertIsNone(guild.requested_limit)
        self.assertEqual(len(targets), 60)
        self.assertEqual(set(values), {str(index) for index in range(1, 61)})
        self.assertEqual(labels[0], "Apelido 01")
        self.assertEqual(labels[-1], "Apelido 60")

    def test_role_ticket_menu_lists_only_roles_with_human_members(self):
        human = SimpleNamespace(id=1, display_name="Membro", bot=False)
        bot_member = SimpleNamespace(id=2, display_name="Bot", bot=True)

        everyone = SimpleNamespace(id=0, name="@everyone", managed=False, position=0, members=[human])
        membro = SimpleNamespace(id=10, name="Membro", managed=False, position=3, members=[human])
        vazio = SimpleNamespace(id=11, name="Cargo Vazio", managed=False, position=2, members=[])
        so_bot = SimpleNamespace(id=12, name="Integração", managed=True, position=5, members=[bot_member])
        topo = SimpleNamespace(id=13, name="Gerência", managed=False, position=9, members=[human, bot_member])
        guild = SimpleNamespace(
            default_role=everyone,
            roles=[everyone, membro, vazio, so_bot, topo],
        )

        roles = fetch_ticket_target_roles(guild)
        self.assertEqual([role.name for role in roles], ["Gerência", "Membro"])

        async def option_values():
            view = FarmTicketRoleSelectView(None, roles)
            return {opt.value for opt in view.children[0].options}

        self.assertEqual(asyncio.run(option_values()), {"13", "10"})

    def test_bulk_role_open_tallies_results_and_stops_when_categories_full(self):
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=1))
        cog.is_ticket_operator = lambda member: True

        outcomes = iter([
            SimpleNamespace(status="created", detail=None),
            SimpleNamespace(status="already_exists", detail=None),
            SimpleNamespace(status="folder_error", detail="pasta ausente"),
            SimpleNamespace(status="category_full", detail=None),
            SimpleNamespace(status="created", detail=None),
        ])
        cog._provision_ticket_for_owner = AsyncMock(side_effect=lambda *a, **k: next(outcomes))

        members = [
            SimpleNamespace(id=i, display_name=f"M{i}", bot=False) for i in range(1, 6)
        ]
        role = SimpleNamespace(id=10, name="Membro", mention="@Membro", members=members)
        guild = SimpleNamespace(id=123)
        executor = unittest.mock.MagicMock(spec=discord.Member)
        executor.id = 99
        executor.mention = "@op"

        followups = []
        interaction = SimpleNamespace(
            guild=guild,
            user=executor,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock(side_effect=lambda *a, **k: followups.append(a[0]))),
        )

        with unittest.mock.patch("cogs.farm_tickets.db_ticket_config_get", return_value={"x": 1}), \
             unittest.mock.patch("cogs.farm_tickets.db_get_meta", return_value={}), \
             unittest.mock.patch("cogs.farm_tickets._active_targets", return_value=("itens", {"Ferro": 1})), \
             unittest.mock.patch("cogs.farm_tickets.db_get_guild_config", return_value={"private_category_id": "1"}), \
             unittest.mock.patch("cogs.farm_tickets.send_log", new=AsyncMock()):
            asyncio.run(cog.bulk_open_tickets_for_role(interaction, role))

        resumo = followups[-1]
        self.assertIn("✅ 1 ticket(s) criado(s)", resumo)
        self.assertIn("♻️ 1", resumo)
        self.assertIn("⚠️ 1", resumo)
        self.assertIn("Processo interrompido", resumo)
        self.assertIn("2 membro(s) não processado(s)", resumo)
        self.assertEqual(cog._provision_ticket_for_owner.await_count, 4)

    def test_legacy_fixed_panel_ids_remain_registered_as_blockers(self):
        async def ids():
            return {item.custom_id for item in LegacyFarmLaunchView().children}

        custom_ids = asyncio.run(ids())
        self.assertEqual(
            custom_ids,
            {"farm_painel:lancar", "farm_painel:lancar_dinheiro"},
        )


class ManagerFarmTicketIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_ticket_uses_tag_and_name_without_slot_or_game_id(self):
        manager = SimpleNamespace(
            id=101,
            name="Joao Silva",
            roles=[SimpleNamespace(name="| Gerente de Farm")],
            nick="[GRT] João Silva | 1234",
            display_name="[GRT] João Silva | 1234",
        )

        identity = _staff_ticket_identity(manager)

        self.assertIsNone(identity.channel_id)
        self.assertIsNone(identity.slot)
        self.assertIsNone(identity.game_id)
        self.assertEqual(identity.nickname, "[GRT] João Silva")
        self.assertEqual(_farm_ticket_channel_base(identity), "farm-grt-joao-silva")

    async def test_vice_ticket_uses_vice_tag_and_name_without_slot_or_game_id(self):
        vice = SimpleNamespace(
            id=102,
            name="Joao Silva",
            roles=[SimpleNamespace(id=1474869320684146846, name="| 02")],
            nick="[VICE] João Silva | 1234",
            display_name="[VICE] João Silva | 1234",
        )

        identity = _staff_ticket_identity(vice)

        self.assertIsNone(identity.channel_id)
        self.assertIsNone(identity.slot)
        self.assertIsNone(identity.game_id)
        self.assertEqual(identity.role_label, "Vice")
        self.assertEqual(identity.nickname, "[VICE] João Silva")
        self.assertEqual(_farm_ticket_channel_base(identity), "farm-vice-joao-silva")

    async def test_manager_ticket_identity_does_not_require_member_folder(self):
        manager = SimpleNamespace(
            id=101,
            name="Joao Silva",
            roles=[SimpleNamespace(name="| Gerente Geral")],
            nick="[GRT] João Silva | 1234",
            display_name="[GRT] João Silva | 1234",
        )

        with unittest.mock.patch(
            "cogs.farm_tickets.resolve_member_folder",
            new=AsyncMock(side_effect=AssertionError("manager folder lookup should be skipped")),
        ) as resolve_folder:
            identity = await _resolve_ticket_folder_identity(
                SimpleNamespace(), "guild-1", manager, 40
            )

        resolve_folder.assert_not_awaited()
        self.assertEqual(identity.nickname, "[GRT] João Silva")

    async def test_vice_ticket_identity_does_not_require_member_folder(self):
        vice = SimpleNamespace(
            id=102,
            name="Joao Silva",
            roles=[SimpleNamespace(id=1474869320684146846, name="| 02")],
            nick="[VICE] João Silva | 1234",
            display_name="[VICE] João Silva | 1234",
        )

        with unittest.mock.patch(
            "cogs.farm_tickets.resolve_member_folder",
            new=AsyncMock(side_effect=AssertionError("vice folder lookup should be skipped")),
        ) as resolve_folder:
            identity = await _resolve_ticket_folder_identity(
                SimpleNamespace(), "guild-1", vice, 40
            )

        resolve_folder.assert_not_awaited()
        self.assertEqual(identity.nickname, "[VICE] João Silva")
        self.assertEqual(identity.role_label, "Vice")

    def test_regular_ticket_keeps_the_member_slot_and_game_id_in_name(self):
        folder = SimpleNamespace(slot=7, nickname="Joao Silva", game_id="1234")

        self.assertEqual(_farm_ticket_channel_base(folder), "farm-07-joao-silva-1234")


if __name__ == "__main__":
    unittest.main()
