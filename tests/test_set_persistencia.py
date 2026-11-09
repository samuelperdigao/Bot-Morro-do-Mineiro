import os
import re
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs import set_views
from cogs.set_views import SetDecisaoButton, _dados_do_embed_legado, build_approval_view
from services import set_request_service as pedidos
from services.db_schema import SCHEMA_SQL


class SetPersistenciaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(os.path.join(self._tmp.name, "set.db"))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._patch = patch.object(pedidos, "get_conn", return_value=self.conn)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.conn.close()
        self._tmp.cleanup()

    def test_botoes_carregam_o_id_no_custom_id(self):
        view = build_approval_view(42)
        ids = sorted(child.custom_id for child in view.children)
        self.assertEqual(ids, ["set:ap:42", "set:rp:42"])
        for custom_id in ids:
            self.assertIsNotNone(re.fullmatch(SetDecisaoButton.__discord_ui_compiled_template__, custom_id))
        view.stop()

    def test_so_um_clique_reserva_a_solicitacao(self):
        sid = pedidos.criar_solicitacao("1", "10", "Fulano", "123")
        self.assertTrue(pedidos.reservar(sid, "99"))
        self.assertFalse(pedidos.reservar(sid, "98"))
        pedidos.liberar(sid)
        self.assertTrue(pedidos.reservar(sid, "98"))

    def test_pendente_bloqueia_novo_pedido_ate_decisao(self):
        sid = pedidos.criar_solicitacao("1", "10", "Fulano", "123")
        self.assertIsNotNone(pedidos.pendente_do_usuario("1", "10"))
        pedidos.concluir(sid, pedidos.REPROVADO, "99")
        self.assertIsNone(pedidos.pendente_do_usuario("1", "10"))

    async def test_reprovar_conclui_e_remove_botoes(self):
        sid = pedidos.criar_solicitacao("1", "10", "Fulano", "123")
        interaction = SimpleNamespace(
            guild_id=1,
            guild=SimpleNamespace(id=1),
            user=SimpleNamespace(id=99, mention="<@99>"),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        with patch.object(set_views, "_check_permission", return_value=True):
            await set_views.decidir_set(interaction, sid, aprovado=False)
            self.assertEqual(pedidos.get_solicitacao(sid)["status"], pedidos.REPROVADO)
            interaction.edit_original_response.assert_awaited_once_with(view=None)

            # Segundo clique (ex.: outro lider, ou depois de restart) e recusado.
            interaction.response.send_message.reset_mock()
            await set_views.decidir_set(interaction, sid, aprovado=True)
            msg = interaction.response.send_message.await_args.args[0]
            self.assertIn("reprovado", msg)

    def test_le_dados_de_pedido_antigo_pelo_embed(self):
        embed = discord.Embed(title="📋 Nova Solicitação de Set")
        embed.add_field(name="🎮 ID no Jogo", value="`12345`")
        embed.add_field(name="📝 Nome", value="João Silva")
        embed.add_field(name="📨 Solicitante (Discord)", value="<@111111111111111111>\n`111111111111111111`")
        dados = _dados_do_embed_legado(SimpleNamespace(embeds=[embed]))
        self.assertEqual(dados, {"id_jogo": "12345", "nome": "João Silva", "user_id": "111111111111111111"})
        self.assertIsNone(_dados_do_embed_legado(SimpleNamespace(embeds=[])))


if __name__ == "__main__":
    unittest.main()
