import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import services.db_service as db
from config.paineis import BOTOES_LIDERANCA
from cogs.farm import FarmView
from cogs.farm_painel import (
    FarmPainelView,
    LegacyFarmLaunchView,
    lock_farm_panel_channel,
)
from cogs.farm_tickets import (
    FarmTicketView,
    FarmTicketsCog,
    _expanded_admin_role_ids,
    _progress,
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

    def _create_log_cog(self):
        db.db_set_system_config("1", "farm", None, "900")
        channel = FakeLogChannel()
        guild = FakeLogGuild(channel)
        cog = FarmTicketsCog.__new__(FarmTicketsCog)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 1 else None)
        return cog, channel

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
            modal.inputs[0]._value = "12"
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
            modal.inputs[0]._value = "300"
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock()),
                channel=SimpleNamespace(send=AsyncMock()),
            )
            await modal.on_submit(interaction)

            empty_modal = cog._modal_recolhimento_ticket(ticket, "99")
            self.assertEqual(empty_modal.inputs[0].label, "Ferro | disponível: 0")

            db.db_ticket_launch(
                int(ticket["id"]), "10", {"Ferro": 300},
                "100", "301", "https://cdn.example/second.png", None,
            )
            replenished_modal = cog._modal_recolhimento_ticket(ticket, "99")
            self.assertEqual(
                replenished_modal.inputs[0].label,
                "Ferro | disponível: 300",
            )

        asyncio.run(collect_first_launch())

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
        self.assertIn("Abrir para Membro", fixed_labels)
        self.assertIn("🎫 Abrir Ticket Semanal", fixed_labels)
        self.assertIn("🗑️ Excluir Ticket", fixed_labels)
        self.assertIn("🎫 Abrir Ticket de Farm", personal_labels)
        self.assertNotIn("🚜 Lançar Farm", fixed_labels)
        self.assertNotIn("💵 Lançar Dinheiro", fixed_labels | personal_labels)

    def test_legacy_fixed_panel_ids_remain_registered_as_blockers(self):
        async def ids():
            return {item.custom_id for item in LegacyFarmLaunchView().children}

        custom_ids = asyncio.run(ids())
        self.assertEqual(
            custom_ids,
            {"farm_painel:lancar", "farm_painel:lancar_dinheiro"},
        )


if __name__ == "__main__":
    unittest.main()
