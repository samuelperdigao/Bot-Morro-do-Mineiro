import os
import unittest
from types import SimpleNamespace

# core.config exige estas variáveis no import; os testes não dependem do .env.
os.environ.setdefault("DISCORD_TOKEN", "token-de-teste")
os.environ.setdefault("APPLICATION_ID", "1")

import discord

from cogs.set_views import _avisar_apelido_bloqueado


class FakeLogChannel:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    async def send(self, content=None, **kwargs):
        if self.error:
            raise self.error
        self.sent.append((content, kwargs))


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


if __name__ == "__main__":
    unittest.main()
