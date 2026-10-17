"""Painel de disparo em Components V2.

O painel legado continua registrado para atender mensagens antigas. A view
abaixo usa IDs próprios e encaminha os cliques para os mesmos callbacks.
"""

from __future__ import annotations

import discord

from cogs.disparo import BroadcastView, build_broadcast_embed


BROADCAST_CONTAINER_CUSTOM_IDS = {
    "broadcast_message_button": "broadcast_container:message",
    "broadcast_delete_last_button": "broadcast_container:delete_last",
}


class BroadcastContainerView(discord.ui.LayoutView):
    """Central de disparo renderizada como Container, sem embed."""

    def __init__(
        self,
        *,
        custom_ids: dict[str, str] | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self._custom_ids = dict(custom_ids or BROADCAST_CONTAINER_CUSTOM_IDS)

        legacy_view = BroadcastView()
        self._legacy_buttons = {
            button.custom_id: button
            for button in legacy_view.children
            if button.custom_id in self._custom_ids
        }

        embed = build_broadcast_embed()
        buttons = [
            self._new_button(legacy_custom_id)
            for legacy_custom_id in self._custom_ids
        ]

        # Os quatro campos são mantidos em TextDisplays separados. Sem um
        # Separator entre cada campo, o Container fica dentro do limite de
        # componentes e ainda preserva a hierarquia visual do embed anterior.
        content: list[discord.ui.LayoutItem] = [
            discord.ui.TextDisplay(f"# {embed.title}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(embed.description or ""),
        ]
        content.extend(
            discord.ui.TextDisplay(f"**{field.name}**\n{field.value}")
            for field in embed.fields
        )
        content.extend(
            (
                discord.ui.Separator(),
                discord.ui.ActionRow(*buttons),
                discord.ui.TextDisplay(embed.footer.text if embed.footer else ""),
            )
        )

        self.add_item(
            discord.ui.Container(
                *content,
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


__all__ = ["BROADCAST_CONTAINER_CUSTOM_IDS", "BroadcastContainerView"]
