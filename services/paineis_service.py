"""
Serviços auxiliares para renderizar e gerenciar painéis.
"""

from pathlib import Path

import discord
from discord import Embed
from config.paineis import (
    PAINEL_OPERACOES_CONFIG, PAINEL_SET_CONFIG,
    BOTOES_MEMBRO, BOTOES_LIDERANCA, BOTOES_SET,
    GRID_LAYOUT, NIVEIS_LIDERANCA,
)

BASE_DIR = Path(__file__).resolve().parent.parent
PAINEL_SET_LOGO_PATH = BASE_DIR / "assets" / "paineis" / "mdm-logo.png"
PAINEL_SET_LOGO_FILENAME = "mdm-logo.png"

_STYLE_MAP = {
    "primary":   discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success":   discord.ButtonStyle.success,
    "danger":    discord.ButtonStyle.danger,
}


# ── Views persistentes ─────────────────────────────────────────────────────────

class PainelOperacoesView(discord.ui.View):
    """View persistente do painel de operações."""

    def __init__(self):
        super().__init__(timeout=None)
        for i, cfg in enumerate(BOTOES_LIDERANCA):
            btn = discord.ui.Button(
                label=cfg["label"],
                emoji=cfg.get("emoji"),
                style=_STYLE_MAP.get(cfg["style"], discord.ButtonStyle.secondary),
                custom_id=cfg["custom_id"],
                row=cfg.get("row", i // GRID_LAYOUT),
            )
            # Closure captura custom_id corretamente via argumento padrão
            def _make_cb(cid: str):
                async def callback(interaction: discord.Interaction):
                    cog = interaction.client.get_cog("PaineisCog")
                    if cog:
                        await cog._handle_painel_operacoes(interaction, cid)
                return callback
            btn.callback = _make_cb(cfg["custom_id"])
            self.add_item(btn)


class PainelSetView(discord.ui.View):
    """View persistente do painel de set (1 botão)."""

    def __init__(self):
        super().__init__(timeout=None)
        for cfg in BOTOES_SET:
            btn = discord.ui.Button(
                label=cfg["label"],
                emoji=cfg.get("emoji"),
                style=_STYLE_MAP.get(cfg["style"], discord.ButtonStyle.primary),
                custom_id=cfg["custom_id"],
            )
            def _make_cb(cid: str):
                async def callback(interaction: discord.Interaction):
                    cog = interaction.client.get_cog("PaineisCog")
                    if cog:
                        await cog._handle_painel_set(interaction, cid)
                return callback
            btn.callback = _make_cb(cfg["custom_id"])
            self.add_item(btn)


# ── Builders de embed ──────────────────────────────────────────────────────────

def obter_botoes_visiveis(nivel_acesso: str) -> list:
    """Retorna botões visíveis para o nível de acesso."""
    if nivel_acesso in NIVEIS_LIDERANCA:
        return BOTOES_LIDERANCA
    return BOTOES_MEMBRO


def criar_embed_painel_operacoes() -> Embed:
    """Cria o embed estático do painel de operações."""
    embed = Embed(
        title=PAINEL_OPERACOES_CONFIG["titulo"],
        description=PAINEL_OPERACOES_CONFIG["descricao"],
        color=PAINEL_OPERACOES_CONFIG["cor"],
    )
    embed.set_footer(text="Use os botões abaixo para navegar")
    return embed


def criar_embed_painel_set() -> Embed:
    """Cria o embed estático do painel de set."""
    embed = Embed(
        title=PAINEL_SET_CONFIG["titulo"],
        description=PAINEL_SET_CONFIG["descricao"],
        color=PAINEL_SET_CONFIG["cor"],
    )
    if PAINEL_SET_LOGO_PATH.exists():
        embed.set_image(url=f"attachment://{PAINEL_SET_LOGO_FILENAME}")
    embed.set_footer(text="Clique no botão abaixo para iniciar seu SET")
    return embed


def painel_set_logo_file() -> discord.File | None:
    """Anexo com a logo exibida no painel de set (None se o arquivo sumir)."""
    if not PAINEL_SET_LOGO_PATH.exists():
        return None
    return discord.File(PAINEL_SET_LOGO_PATH, filename=PAINEL_SET_LOGO_FILENAME)
