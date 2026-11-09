import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import services.db_service as db
from cogs import recolhimento as rec


class _BancoTemporario(unittest.TestCase):
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

    def _ciclo(self, tipo="dinheiro", semana="2026-06-15", channel="10", message="99"):
        ciclo_id = db.db_recolhimento_criar_ciclo(
            "1", "5", channel, tipo, semana, rec._semana_fim_from_inicio(semana)
        )
        if message:
            db.db_recolhimento_salvar_message_id(ciclo_id, message)
        return ciclo_id


class EmbedTests(_BancoTemporario):
    def test_muitas_entregas_nao_estouram_o_limite_do_field(self):
        ciclo_id = self._ciclo()
        for i in range(60):
            db.db_recolhimento_add_entrega_dinheiro(
                ciclo_id, "5", 1000 + i, str(100 + i), f"Membro numero {i}", str(900 + i)
            )
        embed = rec.build_embed_dinheiro(
            db.db_recolhimento_get_ciclo(ciclo_id), db.db_recolhimento_get_entregas(ciclo_id)
        )
        self.assertTrue(all(len(f.value) <= 1024 for f in embed.fields))
        self.assertLessEqual(len(embed), 6000)
        self.assertIn("oculta", embed.fields[0].name)
        total = next(f.value for f in embed.fields if f.name == "TOTAL")
        # O total considera todas as 60 entregas, inclusive as ocultas.
        self.assertEqual(total, rec._fmt_valor(sum(1000 + i for i in range(60))))

    def test_farm_mostra_ferro_e_entregas_antigas(self):
        ciclo_id = self._ciclo(tipo="farm")
        db.db_recolhimento_add_entrega_farm(ciclo_id, "5", 1, 2, 3, 4)
        db.db_recolhimento_add_entrega_itens(ciclo_id, "5", {"Borracha": 10, "Ferro": 7})
        embed = rec.build_embed_farm(
            db.db_recolhimento_get_ciclo(ciclo_id), db.db_recolhimento_get_entregas(ciclo_id)
        )
        total = next(f.value for f in embed.fields if f.name == "TOTAL")
        self.assertEqual(total, "Borracha: 11 | Aluminio: 2 | Cobre: 3 | Plastico: 4 | Ferro: 7")


class CicloTests(_BancoTemporario):
    def test_pagamento_e_idempotente(self):
        ciclo_id = self._ciclo()
        self.assertTrue(db.db_recolhimento_marcar_pago(ciclo_id, "5", "pix"))
        self.assertFalse(db.db_recolhimento_marcar_pago(ciclo_id, "6", "de novo"))
        self.assertEqual(db.db_recolhimento_get_ciclo(ciclo_id)["pago_por"], "5")

    def test_ciclo_encerrado_continua_pagavel(self):
        ciclo_id = self._ciclo()
        db.db_recolhimento_encerrar(ciclo_id)
        self.assertIsNone(db.db_recolhimento_ciclo_aberto_por_mensagem("1", "10", "dinheiro", "99"))
        ciclo = db.db_recolhimento_ciclo_por_mensagem("1", "10", "dinheiro", "99")
        self.assertEqual(ciclo["id"], ciclo_id)
        view = rec._view_para_ciclo(ciclo)
        self.assertTrue(view.registrar.disabled)
        self.assertFalse(view.pagar.disabled)
        db.db_recolhimento_marcar_pago(ciclo_id, "5", "ok")
        self.assertIsNone(rec._view_para_ciclo(db.db_recolhimento_get_ciclo(ciclo_id)))

    def test_fechamento_pega_semanas_perdidas_mas_nao_ciclos_de_ticket(self):
        antigo = self._ciclo(semana="2026-06-01")
        atual = self._ciclo(semana="2026-06-15", channel="11", message="98")
        ticket = self._ciclo(semana="2026-06-01", channel="12", message=None)
        vencidos = {c["id"] for c in db.db_recolhimento_ciclos_vencidos("2026-06-21", False)}
        self.assertEqual(vencidos, {antigo})
        vencidos = {c["id"] for c in db.db_recolhimento_ciclos_vencidos("2026-06-21", True)}
        self.assertEqual(vencidos, {antigo, atual})
        self.assertNotIn(ticket, vencidos)

    def test_ciclo_vazio_pode_ser_excluido_mas_com_entrega_nao(self):
        vazio = self._ciclo(message=None)
        db.db_recolhimento_excluir_ciclo_vazio(vazio)
        self.assertIsNone(db.db_recolhimento_get_ciclo(vazio))
        cheio = self._ciclo(channel="11", message=None)
        db.db_recolhimento_add_entrega_dinheiro(cheio, "5", 10)
        db.db_recolhimento_excluir_ciclo_vazio(cheio)
        self.assertIsNotNone(db.db_recolhimento_get_ciclo(cheio))


class ModalTests(_BancoTemporario, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _BancoTemporario.setUp(self)

    def _interaction(self):
        return SimpleNamespace(
            user=SimpleNamespace(id=5),
            guild=SimpleNamespace(id=1),
            client=SimpleNamespace(get_cog=lambda nome: None),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

    async def test_modal_recusa_ciclo_encerrado(self):
        ciclo_id = self._ciclo()
        db.db_recolhimento_encerrar(ciclo_id)
        modal = rec.RecolhimentoDinheiroModal(ciclo_id, "7", "Alvo")
        modal.valor_input._value = "1500"
        interaction = self._interaction()
        await modal.on_submit(interaction)
        self.assertIn("encerrado", interaction.response.send_message.await_args.args[0])
        self.assertEqual(db.db_recolhimento_get_entregas(ciclo_id), [])

    async def test_modal_le_valor_no_padrao_brasileiro(self):
        ciclo_id = self._ciclo()
        for raw, esperado in (("1500.50", 1500.5), ("R$ 1.500,00", 1500.0)):
            modal = rec.RecolhimentoDinheiroModal(ciclo_id, "7", "Alvo")
            modal.valor_input._value = raw
            await modal.on_submit(self._interaction())
        valores = [e["valor"] for e in db.db_recolhimento_get_entregas(ciclo_id)]
        self.assertEqual(valores, [1500.5, 1500.0])

    async def test_modal_recusa_inf(self):
        ciclo_id = self._ciclo()
        modal = rec.RecolhimentoDinheiroModal(ciclo_id, "7", "Alvo")
        modal.valor_input._value = "inf"
        interaction = self._interaction()
        await modal.on_submit(interaction)
        self.assertIn("inválido", interaction.response.send_message.await_args.args[0])
        self.assertEqual(db.db_recolhimento_get_entregas(ciclo_id), [])

    async def test_modal_farm_grava_ferro(self):
        ciclo_id = self._ciclo(tipo="farm")
        modal = rec.RecolhimentoFarmModal(ciclo_id, "7", "Alvo")
        for campo, valor in (
            (modal.folha_input, "3"), (modal.opio_input, ""), (modal.seringa_input, ""),
            (modal.agulha_input, ""), (modal.ferro_input, "5"),
        ):
            campo._value = valor
        await modal.on_submit(self._interaction())
        entrega = db.db_recolhimento_get_entregas(ciclo_id)[0]
        self.assertEqual(db.db_recolhimento_entrega_itens(entrega), {"Borracha": 3, "Ferro": 5})


class FechamentoTests(_BancoTemporario, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _BancoTemporario.setUp(self)

    async def test_alerta_so_para_pendencia_recente_com_entregas(self):
        recente = self._ciclo(semana="2026-06-08")
        db.db_recolhimento_add_entrega_dinheiro(recente, "5", 10)
        antigo = self._ciclo(semana="2026-01-05", channel="11", message="98")
        db.db_recolhimento_add_entrega_dinheiro(antigo, "5", 10)

        canal = SimpleNamespace(send=AsyncMock())
        guild = SimpleNamespace(get_channel=lambda _id: canal)
        cog = rec.RecolhimentoCog.__new__(rec.RecolhimentoCog)
        cog.bot = SimpleNamespace(get_guild=lambda _id: guild)
        cog._atualizar_embed_ciclo = AsyncMock()

        hoje = datetime.date(2026, 6, 16)
        for ciclo_id in (recente, antigo):
            await cog._encerrar_ciclo(db.db_recolhimento_get_ciclo(ciclo_id), hoje)

        self.assertEqual(canal.send.await_count, 1)
        self.assertTrue(db.db_recolhimento_get_ciclo(recente)["encerrado"])
        self.assertTrue(db.db_recolhimento_get_ciclo(antigo)["encerrado"])
        cog._atualizar_embed_ciclo.assert_any_await(guild, recente)


if __name__ == "__main__":
    unittest.main()
