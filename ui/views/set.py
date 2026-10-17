"""Superfície de compatibilidade e novas interfaces visuais de Set."""

import discord

from config.paineis import BOTOES_SET, PAINEL_SET_CONFIG
from cogs.set_views import ApprovalView, SetModal, SetPanelView, register_persistent_views


# Namespace separado para o painel experimental. Os IDs legados continuam nas
# views SetPanelView e PainelSetView e não são reutilizados nesta view.
SET_CONTAINER_TEST_CUSTOM_ID = "set_container_test:pedir"


class SetContainerPanelView(discord.ui.LayoutView):
    """Painel Container de Set para publicação controlada em canal de teste."""

    def __init__(self):
        super().__init__(timeout=None)

        button = discord.ui.Button(
            label=BOTOES_SET[0]["label"],
            style=discord.ButtonStyle.primary,
            custom_id=SET_CONTAINER_TEST_CUSTOM_ID,
        )
        button.callback = self._pedir_set

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"# {PAINEL_SET_CONFIG['titulo']}"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(PAINEL_SET_CONFIG["descricao"]),
                discord.ui.Separator(),
                discord.ui.ActionRow(button),
                discord.ui.TextDisplay("Clique no botão abaixo para iniciar seu SET"),
                accent_color=PAINEL_SET_CONFIG["cor"],
            )
        )

    async def _pedir_set(self, interaction: discord.Interaction):
        """Encaminha para o mesmo modal e fluxo usado pelos painéis atuais."""
        await interaction.response.send_modal(SetModal())


__all__ = [
    "ApprovalView",
    "SetContainerPanelView",
    "SetModal",
    "SetPanelView",
    "SET_CONTAINER_TEST_CUSTOM_ID",
    "register_persistent_views",
]
