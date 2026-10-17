"""Superfície de compatibilidade e novas interfaces visuais de Ação."""

import discord

from cogs.acao import (
    AcaoParticipantesView,
    AcaoSelectView,
    AcaoTipoView,
    AdicionarMembroPaginadoView,
    RemoverMembroView,
)
from cogs.acao_painel import AcaoPainelView, _build_painel_embed


# Namespace exclusivo do painel Container de teste. O ID legado continua em
# AcaoPainelView e o painel de participantes permanece inalterado.
ACAO_CONTAINER_TEST_CUSTOM_ID = "acao_container_test:iniciar"


class AcaoContainerPanelView(discord.ui.LayoutView):
    """Painel inicial de Ação em Components V2 para publicação controlada."""

    def __init__(self):
        super().__init__(timeout=None)
        self._legacy_view = AcaoPainelView()
        self._legacy_button = next(
            button
            for button in self._legacy_view.children
            if button.custom_id == "acao_painel:iniciar"
        )
        embed = _build_painel_embed()

        button = discord.ui.Button(
            label=self._legacy_button.label,
            style=self._legacy_button.style,
            emoji=self._legacy_button.emoji,
            custom_id=ACAO_CONTAINER_TEST_CUSTOM_ID,
        )
        button.callback = self._iniciar

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"# {embed.title}"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(embed.description),
                discord.ui.Separator(),
                discord.ui.ActionRow(button),
                discord.ui.TextDisplay(embed.footer.text),
                accent_color=embed.color,
            )
        )

    async def _iniciar(self, interaction: discord.Interaction):
        """Encaminha para o mesmo fluxo de seleção de tipo e modal atual."""
        await self._legacy_button.callback(interaction)

__all__ = [
    "ACAO_CONTAINER_TEST_CUSTOM_ID",
    "AcaoContainerPanelView",
    "AcaoParticipantesView",
    "AcaoSelectView",
    "AcaoTipoView",
    "AdicionarMembroPaginadoView",
    "RemoverMembroView",
]
