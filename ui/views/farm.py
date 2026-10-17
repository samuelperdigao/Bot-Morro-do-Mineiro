"""Superfície de compatibilidade e novas interfaces visuais do Farm."""

import discord

from cogs.farm import EditarUltimoModal, EscolherTipoMetaView, FarmView
from cogs.farm_painel import FarmPainelView, _build_painel_embed


# IDs exclusivos dos painéis Container. Os IDs legados continuam em
# FarmPainelView e LegacyFarmLaunchView.
FARM_CONTAINER_CUSTOM_IDS = {
    "farm_painel:abrir_ticket": "farm_container:abrir_ticket",
    "farm_painel:abrir_ticket_membro": "farm_container:abrir_ticket_membro",
    "farm_painel:abrir_ticket_cargo": "farm_container:abrir_ticket_cargo",
    "farm_painel:excluir_ticket_admin": "farm_container:excluir_ticket_admin",
}
FARM_CONTAINER_TEST_CUSTOM_IDS = {
    "farm_painel:abrir_ticket": "farm_container_test:abrir_ticket",
    "farm_painel:abrir_ticket_membro": "farm_container_test:abrir_ticket_membro",
    "farm_painel:abrir_ticket_cargo": "farm_container_test:abrir_ticket_cargo",
    "farm_painel:excluir_ticket_admin": "farm_container_test:excluir_ticket_admin",
}


class FarmContainerPanelView(discord.ui.LayoutView):
    """Painel público de Farm em Components V2 com callbacks legados."""

    def __init__(self, *, custom_ids: dict[str, str] | None = None):
        super().__init__(timeout=None)
        self._custom_ids = dict(custom_ids or FARM_CONTAINER_CUSTOM_IDS)
        self._legacy_view = FarmPainelView()
        self._legacy_buttons = {
            button.custom_id: button
            for button in self._legacy_view.children
            if button.custom_id in self._custom_ids
        }
        embed = _build_painel_embed()

        public_button = self._new_button("farm_painel:abrir_ticket")
        member_button = self._new_button("farm_painel:abrir_ticket_membro")
        role_button = self._new_button("farm_painel:abrir_ticket_cargo")
        delete_button = self._new_button("farm_painel:excluir_ticket_admin")

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"# {embed.title}"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(embed.description),
                discord.ui.Separator(),
                discord.ui.ActionRow(public_button, member_button),
                discord.ui.ActionRow(role_button, delete_button),
                discord.ui.TextDisplay(embed.footer.text),
                accent_color=embed.color,
            )
        )

    def _new_button(self, legacy_custom_id: str) -> discord.ui.Button:
        legacy_button = self._legacy_buttons[legacy_custom_id]
        button = discord.ui.Button(
            label=legacy_button.label,
            style=legacy_button.style,
            emoji=legacy_button.emoji,
            custom_id=self._custom_ids[legacy_custom_id],
        )
        button.callback = self._delegate(legacy_custom_id)
        return button

    def _delegate(self, legacy_custom_id: str):
        async def callback(interaction: discord.Interaction):
            await self._legacy_buttons[legacy_custom_id].callback(interaction)

        return callback


__all__ = [
    "EditarUltimoModal",
    "EscolherTipoMetaView",
    "FarmContainerPanelView",
    "FarmView",
    "FARM_CONTAINER_CUSTOM_IDS",
    "FARM_CONTAINER_TEST_CUSTOM_IDS",
]
