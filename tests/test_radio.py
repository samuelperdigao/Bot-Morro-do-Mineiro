import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.radio import (
    RADIO_CONTAINER_CUSTOM_ID,
    RadioAvisoContainerView,
    RadioContainerPanelView,
    configurar_permissoes_radio,
    criar_embed_painel_radio,
    remover_avisos_radio_antigos,
    pode_alterar_radio,
)


class FakeTarget:
    def __init__(self, target_id):
        self.id = target_id


class FakeMessage:
    def __init__(self, *, author_id, embeds=None, components=None):
        self.author = SimpleNamespace(id=author_id)
        self.embeds = embeds or []
        self.components = components or []
        self.delete = AsyncMock()


class FakeHistoryChannel:
    def __init__(self, messages):
        self.messages = messages

    def history(self, *, limit):
        async def iterator():
            for message in self.messages:
                yield message

        return iterator()


class RadioPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_layout_do_painel_separa_instrucoes_e_acesso(self):
        embed = criar_embed_painel_radio()

        self.assertEqual(embed.title, "📻 Central de Rádio")
        self.assertEqual([field.name for field in embed.fields], [
            "📡 Como alterar",
            "🔒 Acesso restrito",
        ])
        self.assertIsNone(embed.timestamp)

    def test_painel_container_preserva_texto_e_botao(self):
        view = RadioContainerPanelView()

        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertIsInstance(view.children[0], discord.ui.Container)

        text_displays = [
            item for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        ]
        embed = criar_embed_painel_radio()
        self.assertEqual(text_displays[0].content, f"# {embed.title}")
        self.assertIn("Atualize a frequência oficial", text_displays[1].content)
        self.assertIn("Como alterar", text_displays[2].content)
        self.assertIn("Acesso restrito", text_displays[3].content)

        button = next(item for item in view.walk_children() if isinstance(item, discord.ui.Button))
        self.assertEqual(button.custom_id, RADIO_CONTAINER_CUSTOM_ID)
        self.assertEqual(button.label, "Alterar rádio")

    def test_aviso_container_mantem_ping_frequencia_responsavel_e_horario(self):
        momento = datetime(2026, 10, 17, 13, 45, tzinfo=timezone.utc)
        view = RadioAvisoContainerView(
            numero="4497",
            responsavel="Antony Saa | 8300",
            momento=momento,
        )

        rendered = "\n".join(
            item.content
            for item in view.walk_children()
            if isinstance(item, discord.ui.TextDisplay)
        )
        self.assertIn("@everyone", rendered)
        self.assertIn("Nova Rádio Definida", rendered)
        self.assertIn("`4497`", rendered)
        self.assertIn("Antony Saa | 8300", rendered)
        self.assertIn(f"<t:{int(momento.timestamp())}:F>", rendered)

    async def test_remove_apenas_avisos_antigos_e_preserva_painel(self):
        old_embed = FakeMessage(
            author_id=9,
            embeds=[discord.Embed(title="📻 Nova Rádio Definida")],
        )
        old_notice_view = RadioAvisoContainerView(
            numero="4497",
            responsavel="Antony",
            momento=datetime.now(timezone.utc),
        )
        old_container = FakeMessage(
            author_id=9,
            components=old_notice_view.children,
        )
        panel = FakeMessage(
            author_id=9,
            components=RadioContainerPanelView().children,
        )

        removed = await remover_avisos_radio_antigos(
            FakeHistoryChannel([old_embed, old_container, panel]),
            bot_user_id=9,
        )

        self.assertEqual(removed, 2)
        old_embed.delete.assert_awaited_once()
        old_container.delete.assert_awaited_once()
        panel.delete.assert_not_awaited()

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
