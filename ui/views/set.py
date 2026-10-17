"""Superfície de compatibilidade e novas interfaces visuais de Set."""

import discord

from config.paineis import BOTOES_SET, PAINEL_SET_CONFIG
from cogs.set_views import ApprovalView, SetModal, SetPanelView, register_persistent_views


# Os IDs legados continuam nas views SetPanelView e PainelSetView e não são
# reutilizados nesta view. O namespace de teste permanece registrado para as
# mensagens de validação já publicadas.
SET_CONTAINER_CUSTOM_ID = "set_container:pedir"
SET_CONTAINER_TEST_CUSTOM_ID = "set_container_test:pedir"


class SetContainerPanelView(discord.ui.LayoutView):
    """Painel de Set em Components V2 que reaproveita o SetModal atual."""

    def __init__(
        self,
        *,
        custom_id: str = SET_CONTAINER_CUSTOM_ID,
        title: str | None = None,
        description: str | None = None,
        footer: str = "Clique no botão abaixo para iniciar seu SET",
        accent_color: discord.Colour | int | None = None,
        logo_filename: str | None = None,
    ):
        super().__init__(timeout=None)

        button = discord.ui.Button(
            label=BOTOES_SET[0]["label"],
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        )
        button.callback = self._pedir_set

        content = [
            discord.ui.TextDisplay(f"# {title or PAINEL_SET_CONFIG['titulo']}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(description or PAINEL_SET_CONFIG["descricao"]),
        ]
        if logo_filename:
            content.append(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(f"attachment://{logo_filename}")
                )
            )
        content.extend(
            (
                discord.ui.Separator(),
                discord.ui.ActionRow(button),
                discord.ui.TextDisplay(footer),
            )
        )

        self.add_item(
            discord.ui.Container(
                *content,
                accent_color=accent_color or PAINEL_SET_CONFIG["cor"],
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
    "SET_CONTAINER_CUSTOM_ID",
    "SET_CONTAINER_TEST_CUSTOM_ID",
    "register_persistent_views",
]
