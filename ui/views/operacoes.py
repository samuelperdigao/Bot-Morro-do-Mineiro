"""Painel de operações em Components V2.

O painel Container usa os mesmos callbacks da view legada para preservar o
fluxo de permissões e as respostas já existentes.
"""

import discord

from services.paineis_service import PainelOperacoesView, criar_embed_painel_operacoes


# Os IDs legados continuam em PainelOperacoesView. Os IDs separados evitam
# conflito entre as views persistentes do painel antigo e do novo Container.
PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS = {
    "painel:definir_metas": "painel_container:definir_metas",
    "painel:fazer_anuncio": "painel_container:fazer_anuncio",
    "painel:ranking": "painel_container:ranking",
}
PAINEL_OPERACOES_CONTAINER_TEST_CUSTOM_IDS = {
    legacy_id: custom_id.replace("painel_container:", "painel_container_test:")
    for legacy_id, custom_id in PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS.items()
}


class PainelOperacoesContainerView(discord.ui.LayoutView):
    """Painel de operações em Components V2 com callbacks legados."""

    def __init__(
        self,
        *,
        custom_ids: dict[str, str] | None = None,
    ):
        super().__init__(timeout=None)
        self._custom_ids = dict(custom_ids or PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS)

        self._legacy_view = PainelOperacoesView()
        self._legacy_buttons = {
            button.custom_id: button
            for button in self._legacy_view.children
            if button.custom_id in self._custom_ids
        }

        embed = criar_embed_painel_operacoes()
        buttons_by_row: dict[int, list[discord.ui.Button]] = {}
        for legacy_custom_id, custom_id in self._custom_ids.items():
            legacy_button = self._legacy_buttons[legacy_custom_id]
            button = discord.ui.Button(
                label=legacy_button.label,
                style=legacy_button.style,
                emoji=legacy_button.emoji,
                custom_id=custom_id,
            )
            button.callback = self._delegate(legacy_custom_id)
            buttons_by_row.setdefault(legacy_button.row or 0, []).append(button)

        content: list[discord.ui.LayoutItem] = [
            discord.ui.TextDisplay(f"# {embed.title}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(embed.description or ""),
            discord.ui.Separator(),
        ]
        for row in sorted(buttons_by_row):
            content.append(discord.ui.ActionRow(*buttons_by_row[row]))
        content.append(discord.ui.TextDisplay(embed.footer.text if embed.footer else ""))

        self.add_item(
            discord.ui.Container(
                *content,
                accent_color=embed.color,
            )
        )

    def _delegate(self, legacy_custom_id: str):
        async def callback(interaction: discord.Interaction):
            await self._legacy_buttons[legacy_custom_id].callback(interaction)

        return callback


# Alias com o nome de domínio mais curto, útil para integrações que tratam os
# painéis como "Operacoes" em vez de "PainelOperacoes".
OperacoesContainerPanelView = PainelOperacoesContainerView


__all__ = [
    "OperacoesContainerPanelView",
    "PAINEL_OPERACOES_CONTAINER_CUSTOM_IDS",
    "PAINEL_OPERACOES_CONTAINER_TEST_CUSTOM_IDS",
    "PainelOperacoesContainerView",
]
