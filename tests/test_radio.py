import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.radio import (
    configurar_permissoes_radio,
    criar_embed_painel_radio,
    pode_alterar_radio,
)


class FakeTarget:
    def __init__(self, target_id):
        self.id = target_id


class RadioPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_layout_do_painel_separa_instrucoes_e_acesso(self):
        embed = criar_embed_painel_radio()

        self.assertEqual(embed.title, "📻 Central de Rádio")
        self.assertEqual([field.name for field in embed.fields], [
            "📡 Como alterar",
            "🔒 Acesso restrito",
        ])
        self.assertIsNone(embed.timestamp)

    def test_administrador_pode_alterar(self):
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=True),
            roles=[],
        )

        self.assertTrue(pode_alterar_radio(member))

    def test_todos_os_cargos_de_gerente_podem_alterar(self):
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False),
            roles=[SimpleNamespace(name="| Gerente de Farm")],
        )

        self.assertTrue(pode_alterar_radio(member))

    def test_membro_comum_nao_pode_alterar(self):
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False),
            roles=[SimpleNamespace(name="| Membro")],
        )

        self.assertFalse(pode_alterar_radio(member))

    async def test_canal_bloqueia_texto_e_threads_para_everyone(self):
        everyone = FakeTarget(1)
        bot_member = FakeTarget(2)
        canal = SimpleNamespace(
            guild=SimpleNamespace(default_role=everyone, me=bot_member),
            overwrites={},
            overwrites_for=lambda _role: discord.PermissionOverwrite(view_channel=True),
            edit=AsyncMock(),
        )

        await configurar_permissoes_radio(canal)

        overwrites = canal.edit.await_args.kwargs["overwrites"]
        member_overwrite = overwrites[everyone]
        bot_overwrite = overwrites[bot_member]
        self.assertTrue(member_overwrite.view_channel)
        self.assertFalse(member_overwrite.send_messages)
        self.assertFalse(member_overwrite.send_messages_in_threads)
        self.assertFalse(member_overwrite.create_public_threads)
        self.assertFalse(member_overwrite.create_private_threads)
        self.assertTrue(bot_overwrite.send_messages)
        self.assertTrue(bot_overwrite.embed_links)
        self.assertTrue(bot_overwrite.mention_everyone)


if __name__ == "__main__":
    unittest.main()
