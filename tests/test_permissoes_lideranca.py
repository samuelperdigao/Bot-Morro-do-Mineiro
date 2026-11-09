import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import bau_gerentes, disparo
from ui.views.disparo import BROADCAST_CONTAINER_CUSTOM_IDS, BroadcastContainerView

LIDERANCA_ROLE_ID = 555


def _membro(*role_ids: int, admin: bool = False, manage_guild: bool = False):
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.mention = "<@42>"
    member.guild = SimpleNamespace(id=1)
    member.roles = [SimpleNamespace(id=role_id) for role_id in role_ids]
    member.guild_permissions = SimpleNamespace(administrator=admin, manage_guild=manage_guild)
    return member


def _interaction(user):
    response = SimpleNamespace(
        send_message=AsyncMock(),
        send_modal=AsyncMock(),
        is_done=MagicMock(return_value=False),
    )
    return SimpleNamespace(user=user, guild=SimpleNamespace(id=1), response=response)


@patch("cogs.disparo.db_get_lideranca_role_ids", return_value=[LIDERANCA_ROLE_ID])
class DisparoPermissaoTests(unittest.IsolatedAsyncioTestCase):
    def test_pode_disparar(self, _ids):
        self.assertTrue(disparo.pode_disparar(_membro(LIDERANCA_ROLE_ID)))
        self.assertTrue(disparo.pode_disparar(_membro(admin=True)))
        self.assertTrue(disparo.pode_disparar(_membro(manage_guild=True)))
        self.assertFalse(disparo.pode_disparar(_membro(999)))
        self.assertFalse(disparo.pode_disparar(SimpleNamespace(id=1)))

    async def test_painel_v2_bloqueia_quem_nao_e_lideranca(self, _ids):
        view = BroadcastContainerView()
        for container_custom_id in BROADCAST_CONTAINER_CUSTOM_IDS.values():
            with self.subTest(custom_id=container_custom_id):
                interaction = _interaction(_membro(999))
                button = next(
                    item
                    for item in view.walk_children()
                    if getattr(item, "custom_id", None) == container_custom_id
                )
                await button.callback(interaction)
                interaction.response.send_message.assert_awaited_once_with(
                    disparo.MSG_SEM_PERMISSAO, ephemeral=True
                )
                interaction.response.send_modal.assert_not_awaited()

    async def test_painel_v2_abre_modal_para_lideranca(self, _ids):
        view = BroadcastContainerView()
        interaction = _interaction(_membro(LIDERANCA_ROLE_ID))
        button = next(
            item
            for item in view.walk_children()
            if getattr(item, "custom_id", None) == BROADCAST_CONTAINER_CUSTOM_IDS["broadcast_message_button"]
        )
        await button.callback(interaction)
        interaction.response.send_modal.assert_awaited_once()

    async def test_modal_revalida_permissao(self, _ids):
        interaction = _interaction(_membro(999))
        await disparo.BroadcastModal().on_submit(interaction)
        interaction.response.send_message.assert_awaited_once_with(
            disparo.MSG_SEM_PERMISSAO, ephemeral=True
        )

    def test_embed_informa_restricao(self, _ids):
        campos = {field.name: field.value for field in disparo.build_broadcast_embed().fields}
        self.assertIn("liderança", campos["🔓 Permissão"])

    def test_comando_exige_gerenciar_servidor(self, _ids):
        comando = disparo.DisparoCog.painel_disparo
        self.assertTrue(comando.default_permissions.manage_guild)


@patch("cogs.bau_gerentes.db_get_lideranca_role_ids", return_value=[LIDERANCA_ROLE_ID])
class BauGerentesPermissaoTests(unittest.IsolatedAsyncioTestCase):
    async def test_painel_so_responde_a_lideranca(self, _ids):
        view = bau_gerentes.BauGerentesPainelView()

        negado = _interaction(_membro(999))
        self.assertFalse(await view.interaction_check(negado))
        negado.response.send_message.assert_awaited_once()

        permitido = _interaction(_membro(LIDERANCA_ROLE_ID))
        self.assertTrue(await view.interaction_check(permitido))
        permitido.response.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
