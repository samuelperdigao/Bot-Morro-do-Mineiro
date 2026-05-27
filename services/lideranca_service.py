"""Servicos do painel de lideranca."""

from __future__ import annotations

import discord

DEFAULT_LIDERANCA_PANEL_CHANNEL_ID = 1506885629181689886

STATUS_LABELS = {
    "aberta": "Aberta",
    "em_andamento": "Em andamento",
    "concluida": "Concluida",
}

PRIORIDADE_LABELS = {
    "urgente": "Urgente",
    "alta": "Alta",
    "media": "Media",
    "baixa": "Baixa",
}


def _descricao_destacada(descricao: str | None, max_len: int = 650) -> str:
    texto = (descricao or "").strip()
    if not texto:
        return "> Sem descricao."
    if len(texto) > max_len:
        texto = texto[: max_len - 3].rstrip() + "..."
    linhas = texto.splitlines() or [texto]
    return "\n".join(f"> {linha}" if linha else ">" for linha in linhas)


def normalizar_prioridade(value: str) -> str:
    value = (value or "").strip().lower()
    aliases = {
        "urgente": "urgente",
        "alta": "alta",
        "media": "media",
        "média": "media",
        "baixa": "baixa",
    }
    return aliases.get(value, "media")


def criar_embed_painel_lideranca() -> discord.Embed:
    embed = discord.Embed(
        title="Painel de Lideranca",
        description=(
            "Controle pendencias internas da familia pelo painel.\n"
            "Use os botoes para criar, consultar, assumir ou concluir tarefas."
        ),
        color=discord.Color.from_rgb(47, 129, 247),
    )
    embed.add_field(
        name="Fluxo rapido",
        value="1. Crie uma pendencia\n2. Alguem assume\n3. A lideranca conclui quando resolver",
        inline=False,
    )
    embed.set_footer(text="Painel fixo da lideranca")
    return embed


def criar_embed_pendencias(rows: list, titulo: str) -> discord.Embed:
    embed = discord.Embed(
        title=titulo,
        color=discord.Color.from_rgb(241, 196, 15),
        timestamp=discord.utils.utcnow(),
    )
    if not rows:
        embed.description = "Nenhuma pendencia encontrada."
        return embed

    linhas = []
    for row in rows:
        responsavel = f"<@{row['responsavel_id']}>" if row["responsavel_id"] else "sem responsavel"
        prazo = row["prazo"] or "sem prazo"
        categoria = row["categoria"] or "geral"
        prioridade = PRIORIDADE_LABELS.get(row["prioridade"], row["prioridade"] or "Media")
        status = STATUS_LABELS.get(row["status"], row["status"])
        linhas.append(
            f"**#{row['id']} - {row['titulo']}**\n"
            f"{_descricao_destacada(row['descricao'])}\n"
            f"Status: `{status}` | Prioridade: `{prioridade}` | Categoria: `{categoria}`\n"
            f"Resp.: {responsavel} | Prazo: `{prazo}`"
        )

    embed.description = "\n\n".join(linhas)[:4000]
    embed.set_footer(text="Use o botao Assumir/Concluir e informe o ID da pendencia.")
    return embed


def criar_embed_pendencia_criada(row) -> discord.Embed:
    prioridade = PRIORIDADE_LABELS.get(row["prioridade"], row["prioridade"] or "Media")
    categoria = row["categoria"] or "geral"
    embed = discord.Embed(
        title=f"Pendencia #{row['id']} criada",
        description=f"**{row['titulo']}**\n{_descricao_destacada(row['descricao'])}",
        color=discord.Color.from_rgb(47, 129, 247),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Prioridade", value=f"`{prioridade}`", inline=True)
    embed.add_field(name="Categoria", value=f"`{categoria}`", inline=True)
    embed.add_field(name="Prazo", value=f"`{row['prazo'] or 'sem prazo'}`", inline=True)
    embed.set_footer(text="A descricao fica destacada nas consultas do painel.")
    return embed


def criar_embed_relatorio(resumo: dict) -> discord.Embed:
    embed = discord.Embed(
        title="Relatorio da Lideranca",
        color=discord.Color.from_rgb(46, 204, 113),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Abertas", value=str(resumo["abertas"]), inline=True)
    embed.add_field(name="Em andamento", value=str(resumo["andamento"]), inline=True)
    embed.add_field(name="Concluidas", value=str(resumo["concluidas"]), inline=True)
    embed.add_field(name="Urgentes abertas", value=str(resumo["urgentes_abertas"]), inline=True)
    return embed


class LiderancaPanelView(discord.ui.View):
    """View persistente do painel de lideranca."""

    def __init__(self):
        super().__init__(timeout=None)

        botoes = [
            ("Nova Pendencia", discord.ButtonStyle.primary, "lideranca:nova_pendencia", 0),
            ("Ver Pendencias", discord.ButtonStyle.secondary, "lideranca:ver_pendencias", 0),
            ("Minhas Tarefas", discord.ButtonStyle.secondary, "lideranca:minhas_tarefas", 0),
            ("Assumir/Concluir", discord.ButtonStyle.success, "lideranca:acao_pendencia", 1),
            ("Relatorio", discord.ButtonStyle.secondary, "lideranca:relatorio", 1),
        ]

        for label, style, custom_id, row in botoes:
            btn = discord.ui.Button(label=label, style=style, custom_id=custom_id, row=row)

            def _make_cb(cid: str):
                async def callback(interaction: discord.Interaction):
                    cog = interaction.client.get_cog("LiderancaCog")
                    if cog:
                        await cog.handle_lideranca_panel(interaction, cid)

                return callback

            btn.callback = _make_cb(custom_id)
            self.add_item(btn)
