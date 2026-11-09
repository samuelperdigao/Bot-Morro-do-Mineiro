import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import tasks

from core import error_reporting
from core.error_reporting import _deve_avisar, instalar_handlers_ui, proteger_loop


class AvisoRateLimitTests(unittest.TestCase):
    def setUp(self):
        error_reporting._ultimos_avisos.clear()

    def test_mesmo_erro_so_avisa_uma_vez_na_janela(self):
        self.assertTrue(_deve_avisar("x", agora=1000))
        self.assertFalse(_deve_avisar("x", agora=1000 + 10))
        self.assertTrue(_deve_avisar("x", agora=1000 + error_reporting.JANELA_AVISO_SEGUNDOS + 1))
        self.assertTrue(_deve_avisar("y", agora=1000 + 10))


class ProtegerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_que_falha_e_reiniciada(self):
        execucoes = []

        @tasks.loop(seconds=0.01, count=None)
        async def minha_task():
            execucoes.append(1)
            if len(execucoes) == 1:
                raise ValueError("falha simulada")
            minha_task.stop()

        with patch.object(error_reporting.log, "error"):
            proteger_loop(minha_task, "teste", atraso_reinicio=0.05)
            minha_task.start()
            for _ in range(100):
                await asyncio.sleep(0.02)
                if len(execucoes) >= 2 and not minha_task.is_running():
                    break
        self.assertGreaterEqual(len(execucoes), 2)


class HandlersUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        base = discord.ui.view.BaseView
        self._originais = (base.on_error, discord.ui.Modal.on_error)
        instalar_handlers_ui(client=None)

    def tearDown(self):
        discord.ui.view.BaseView.on_error, discord.ui.Modal.on_error = self._originais

    def _interaction(self):
        response = SimpleNamespace(is_done=lambda: False, send_message=AsyncMock())
        return SimpleNamespace(
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
            command=None,
            data={"custom_id": "x"},
            user=SimpleNamespace(id=1),
            channel_id=None,
        )

    async def test_view_layoutview_e_modal_respondem_ao_usuario(self):
        class MinhaView(discord.ui.View):
            pass

        class MinhaLayout(discord.ui.LayoutView):
            pass

        class MeuModal(discord.ui.Modal, title="t"):
            pass

        with patch.object(error_reporting.log, "error"):
            for objeto, args in (
                (MinhaView(), (ValueError("x"), None)),
                (MinhaLayout(), (ValueError("x"), None)),
                (MeuModal(), (ValueError("x"),)),
            ):
                with self.subTest(tipo=type(objeto).__name__):
                    interaction = self._interaction()
                    await objeto.on_error(interaction, *args)
                    interaction.response.send_message.assert_awaited_once_with(
                        error_reporting.MENSAGEM_ERRO_USUARIO, ephemeral=True
                    )

    async def test_on_error_proprio_nao_e_substituido(self):
        chamado = AsyncMock()

        class ComHandler(discord.ui.View):
            async def on_error(self, interaction, error, item):
                await chamado()

        interaction = self._interaction()
        await ComHandler().on_error(interaction, ValueError("x"), None)
        chamado.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
