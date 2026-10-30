import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# core.config exige estas variáveis no import; os testes não dependem do .env.
os.environ.setdefault("DISCORD_TOKEN", "token-de-teste")
os.environ.setdefault("APPLICATION_ID", "1")

import discord
from discord.ext import commands

import services.db_service as db
from cogs.set_views import (
    ApprovalView,
    _avisar_apelido_bloqueado,
    _view_from_row,
    parse_set_embed,
    register_persistent_views,
)
from features.set.service import set_request_service

GUILD_ID = 111
CHANNEL_ID = 222
MESSAGE_ID = 333
USER_ID = 444


class FakeLogChannel:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    async def send(self, content=None, **kwargs):
        if self.error:
            raise self.error
        self.sent.append((content, kwargs))


class FakeMessage:
    def __init__(self, embeds=None, message_id=MESSAGE_ID):
        self.id = message_id
        self.embeds = embeds or []
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def legacy_embed():
    embed = discord.Embed(title="📋 Nova Solicitação de Set")
    embed.add_field(name="🎮 ID no Jogo", value="`12345`")
    embed.add_field(name="📝 Nome", value="Fulano de Tal")
    embed.add_field(name="📨 Solicitante (Discord)", value=f"<@{USER_ID}>\n`{USER_ID}`")
    return embed


def fake_interaction(message, guild=None):
    return SimpleNamespace(
        guild=guild or SimpleNamespace(id=GUILD_ID, roles=[], get_role=lambda _id: None),
        guild_id=GUILD_ID,
        channel_id=CHANNEL_ID,
        user=SimpleNamespace(id=999, mention="<@999>"),
        message=message,
        followup=FakeFollowup(),
    )


class ApelidoBloqueadoTests(unittest.IsolatedAsyncioTestCase):
    async def test_avisa_no_canal_de_log_sem_marcar_o_membro(self):
        channel = FakeLogChannel()
        member = SimpleNamespace(id=10, mention="<@10>")

        await _avisar_apelido_bloqueado(channel, member)

        content, kwargs = channel.sent[0]
        self.assertIn("Sem permissão para alterar apelido de <@10>", content)
        self.assertFalse(kwargs["allowed_mentions"].users)

    async def test_falha_ao_avisar_nao_interrompe_a_aprovacao(self):
        channel = FakeLogChannel(error=discord.DiscordException("falhou"))

        await _avisar_apelido_bloqueado(channel, SimpleNamespace(id=10, mention="<@10>"))

        self.assertEqual(channel.sent, [])


class ParseSetEmbedTests(unittest.TestCase):
    def test_le_os_campos_do_embed_de_solicitacao(self):
        self.assertEqual(
            parse_set_embed(legacy_embed()),
            {
                "requester_user_id": str(USER_ID),
                "target_name": "Fulano de Tal",
                "id_jogo": "12345",
            },
        )

    def test_recusa_embed_incompleto_ou_com_ids_invalidos(self):
        sem_nome = legacy_embed().remove_field(1)
        id_invalido = legacy_embed().set_field_at(0, name="🎮 ID no Jogo", value="`abc`")
        solicitante_sem_id = legacy_embed().set_field_at(
            2, name="📨 Solicitante (Discord)", value=f"<@{USER_ID}>"
        )

        for embed in (discord.Embed(title="Outro"), sem_nome, id_invalido, solicitante_sem_id):
            with self.subTest(fields=[field.value for field in embed.fields]):
                self.assertIsNone(parse_set_embed(embed))


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "set.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def criar_pedido(self, message_id=MESSAGE_ID):
        request_id = set_request_service.create(
            str(GUILD_ID), str(USER_ID), "Fulano", "12345", str(CHANNEL_ID)
        )
        set_request_service.attach_message(request_id, str(message_id))
        return request_id

    def pedidos(self):
        return db.get_conn().execute("SELECT * FROM set_requests").fetchall()


class RestartTests(DatabaseTestCase):
    async def test_pedido_continua_decidivel_em_nova_instancia_apos_restart(self):
        request_id = self.criar_pedido()
        set_request_service.claim(request_id, "999", "approved")

        # O restart reabre o que estava em processamento e recria as views.
        bot = commands.Bot(
            command_prefix="!", intents=discord.Intents.none(), application_id=1
        )
        register_persistent_views(bot)
        await bot.close()

        self.assertEqual(len(bot.persistent_views), 5)
        recuperado = set_request_service.recoverable()[0]
        view = _view_from_row(recuperado)
        self.assertEqual(view.request_id, request_id)
        self.assertEqual(view.target_user_id, USER_ID)
        self.assertTrue(set_request_service.claim(view.request_id, "999", "approved"))

    async def test_somente_a_primeira_de_duas_reivindicacoes_passa(self):
        request_id = self.criar_pedido()

        self.assertTrue(set_request_service.claim(request_id, "1", "approved"))
        self.assertFalse(set_request_service.claim(request_id, "2", "rejected"))


class FallbackTests(DatabaseTestCase):
    def fallback(self):
        return ApprovalView(0, "", None)

    async def test_resgata_pedido_legado_pelo_embed_e_reprova(self):
        message = FakeMessage([legacy_embed()])
        interaction = fake_interaction(message)
        fallback = self.fallback()
        fallback._processando = True

        await fallback._processar(interaction, aprovado=False)

        rows = self.pedidos()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertEqual(rows[0]["approval_message_id"], str(MESSAGE_ID))
        self.assertEqual(rows[0]["requester_user_id"], str(USER_ID))
        self.assertEqual(message.edits, [{"view": None}])
        self.assertEqual(fallback.target_user_id, 0)
        self.assertIsNone(fallback.request_id)
        self.assertFalse(fallback._processando)

    async def test_mensagem_com_linha_ja_decidida_nao_reprocessa(self):
        request_id = self.criar_pedido()
        set_request_service.claim(request_id, "1", "approved")
        set_request_service.complete(request_id, "approved")
        message = FakeMessage([legacy_embed()])
        interaction = fake_interaction(message)

        await self.fallback()._processar(interaction, aprovado=True)

        self.assertEqual(len(self.pedidos()), 1)
        self.assertEqual(self.pedidos()[0]["status"], "approved")
        self.assertEqual(message.edits, [])
        self.assertIn("já foi processada", interaction.followup.sent[0])

    async def test_mensagem_com_linha_pendente_segue_a_linha_existente(self):
        request_id = self.criar_pedido()
        message = FakeMessage([legacy_embed()])

        await self.fallback()._processar(fake_interaction(message), aprovado=False)

        rows = self.pedidos()
        self.assertEqual([row["request_id"] for row in rows], [request_id])
        self.assertEqual(rows[0]["status"], "rejected")

    async def test_embed_sem_dados_pede_novo_set(self):
        for embeds in ([], [discord.Embed(title="Outro")]):
            with self.subTest(embeds=len(embeds)):
                interaction = fake_interaction(FakeMessage(embeds))
                fallback = self.fallback()
                fallback._processando = True

                await fallback._processar(interaction, aprovado=True)

                self.assertEqual(self.pedidos(), [])
                self.assertIn("refazer o Set", interaction.followup.sent[0])
                self.assertFalse(fallback._processando)

    async def test_falha_ao_criar_responde_sem_travar_o_fallback(self):
        interaction = fake_interaction(FakeMessage([legacy_embed()]))
        fallback = self.fallback()
        fallback._processando = True

        with patch.object(set_request_service, "create", side_effect=RuntimeError("banco")):
            await fallback._processar(interaction, aprovado=True)

        self.assertIn("Não foi possível recuperar", interaction.followup.sent[0])
        self.assertFalse(fallback._processando)


class FalhaAposReivindicacaoTests(DatabaseTestCase):
    async def fetch_not_found(self, _user_id):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "ausente")

    async def test_membro_nao_encontrado_mantem_botoes_e_pedido_pendente(self):
        request_id = self.criar_pedido()
        view = _view_from_row(set_request_service.get(request_id))
        message = FakeMessage()
        guild = SimpleNamespace(
            id=GUILD_ID, get_member=lambda _id: None, fetch_member=self.fetch_not_found
        )
        interaction = fake_interaction(message, guild)

        await view._processar(interaction, aprovado=True)

        row = set_request_service.get(request_id)
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["decided_by"])
        self.assertEqual(message.edits, [])
        self.assertIn("não encontrado", interaction.followup.sent[0])
        self.assertFalse(view._processando)

    async def test_excecao_depois_de_remover_botoes_recoloca_e_libera_o_pedido(self):
        request_id = self.criar_pedido()
        view = _view_from_row(set_request_service.get(request_id))
        message = FakeMessage()
        member = SimpleNamespace(id=USER_ID, roles=[])
        guild = SimpleNamespace(
            id=GUILD_ID, roles=[], get_role=lambda _id: None, get_member=lambda _id: member
        )

        with patch("cogs.set_views.db_channel_map_get", side_effect=RuntimeError("banco")):
            with self.assertRaises(RuntimeError):
                await view._processar(fake_interaction(message, guild), aprovado=True)

        self.assertEqual(set_request_service.get(request_id)["status"], "pending")
        self.assertEqual(message.edits, [{"view": None}, {"view": view}])
        self.assertFalse(view._processando)

    async def test_pedido_liberado_nao_prende_o_membro_apos_nova_decisao(self):
        request_id = self.criar_pedido()
        view = _view_from_row(set_request_service.get(request_id))
        message = FakeMessage()
        guild = SimpleNamespace(
            id=GUILD_ID, get_member=lambda _id: None, fetch_member=self.fetch_not_found
        )

        await view._processar(fake_interaction(message, guild), aprovado=True)
        await view._processar(fake_interaction(message), aprovado=False)

        self.assertEqual(set_request_service.get(request_id)["status"], "rejected")
        self.assertIsNone(
            set_request_service.pending_for_user(str(GUILD_ID), str(USER_ID))
        )


if __name__ == "__main__":
    unittest.main()
