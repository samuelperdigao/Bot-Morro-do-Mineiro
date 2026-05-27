"""Handlers do painel de lideranca."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core.permissions import is_lideranca
from services.db_service import (
    db_get_lideranca_role_ids,
    db_lideranca_assumir_pendencia,
    db_lideranca_concluir_pendencia,
    db_lideranca_criar_pendencia,
    db_lideranca_get_pendencia,
    db_lideranca_listar_pendencias,
    db_lideranca_resumo,
)
from services.lideranca_service import (
    LiderancaPanelView,
    criar_embed_pendencia_criada,
    criar_embed_pendencias,
    criar_embed_relatorio,
    normalizar_prioridade,
)

log = logging.getLogger("lideranca")


class NovaPendenciaModal(discord.ui.Modal, title="Nova Pendencia"):
    titulo = discord.ui.TextInput(
        label="Titulo",
        placeholder="Ex: Conferir bau de armas",
        max_length=100,
    )
    descricao = discord.ui.TextInput(
        label="Descricao",
        placeholder="Explique o que precisa ser resolvido.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    categoria = discord.ui.TextInput(
        label="Categoria",
        placeholder="Ex: bau, financeiro, membro, veiculos",
        required=False,
        max_length=60,
    )
    prioridade = discord.ui.TextInput(
        label="Prioridade",
        placeholder="urgente, alta, media ou baixa",
        required=False,
        max_length=20,
    )
    prazo = discord.ui.TextInput(
        label="Prazo",
        placeholder="Ex: hoje 22h, sexta, sem prazo",
        required=False,
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        pendencia_id = db_lideranca_criar_pendencia(
            guild_id=guild_id,
            titulo=self.titulo.value.strip(),
            descricao=self.descricao.value.strip(),
            categoria=(self.categoria.value.strip() or "geral"),
            prioridade=normalizar_prioridade(self.prioridade.value),
            prazo=(self.prazo.value.strip() or "sem prazo"),
            criado_por_id=str(interaction.user.id),
        )
        row = db_lideranca_get_pendencia(guild_id, pendencia_id)
        await interaction.response.send_message(
            embed=criar_embed_pendencia_criada(row),
            ephemeral=True,
        )
        log.info("Pendencia #%s criada por %s (guild %s)", pendencia_id, interaction.user, guild_id)


class AcaoPendenciaModal(discord.ui.Modal, title="Assumir ou Concluir Pendencia"):
    pendencia_id = discord.ui.TextInput(
        label="ID da pendencia",
        placeholder="Ex: 12",
        max_length=10,
    )
    acao = discord.ui.TextInput(
        label="Acao",
        placeholder="assumir ou concluir",
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        raw_id = self.pendencia_id.value.strip()
        if not raw_id.isdigit():
            await interaction.response.send_message("Informe um ID numerico valido.", ephemeral=True)
            return

        pendencia_id = int(raw_id)
        acao = self.acao.value.strip().lower()
        if acao in {"assumir", "pegar", "responsavel"}:
            ok = db_lideranca_assumir_pendencia(guild_id, pendencia_id, str(interaction.user.id))
            msg = f"Voce assumiu a pendencia `#{pendencia_id}`." if ok else "Pendencia nao encontrada ou ja concluida."
        elif acao in {"concluir", "resolver", "feito", "finalizar"}:
            ok = db_lideranca_concluir_pendencia(guild_id, pendencia_id, str(interaction.user.id))
            msg = f"Pendencia `#{pendencia_id}` concluida." if ok else "Pendencia nao encontrada ou ja concluida."
        else:
            msg = "Acao invalida. Use `assumir` ou `concluir`."

        await interaction.response.send_message(msg, ephemeral=True)
        log.info("Acao pendencia #%s/%s por %s (guild %s)", pendencia_id, acao, interaction.user, guild_id)


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


class PendenciaActionView(discord.ui.View):
    def __init__(self, guild_id: str, author_id: int, rows: list):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.author_id = author_id
        self.selected_id: int | None = None

        options = []
        for row in rows[:25]:
            status = "andamento" if row["status"] == "em_andamento" else row["status"]
            prioridade = row["prioridade"] or "media"
            responsavel = "com resp." if row["responsavel_id"] else "sem resp."
            options.append(
                discord.SelectOption(
                    label=_truncate(f"#{row['id']} - {row['titulo']}", 100),
                    value=str(row["id"]),
                    description=_truncate(f"{status} | {prioridade} | {responsavel}", 100),
                )
            )

        select = discord.ui.Select(
            placeholder="Escolha a pendencia",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

        async def select_callback(interaction: discord.Interaction):
            if not self._same_author(interaction):
                await interaction.response.send_message("Essa selecao nao e sua.", ephemeral=True)
                return

            self.selected_id = int(select.values[0])
            self.assumir_btn.disabled = False
            self.concluir_btn.disabled = False
            await interaction.response.edit_message(
                content=f"Pendencia selecionada: `#{self.selected_id}`. Agora escolha uma acao.",
                view=self,
            )

        select.callback = select_callback
        self.add_item(select)

        self.assumir_btn = discord.ui.Button(
            label="Assumir",
            style=discord.ButtonStyle.success,
            row=1,
            disabled=True,
        )
        self.concluir_btn = discord.ui.Button(
            label="Concluir",
            style=discord.ButtonStyle.danger,
            row=1,
            disabled=True,
        )

        async def assumir_callback(interaction: discord.Interaction):
            await self._run_action(interaction, "assumir")

        async def concluir_callback(interaction: discord.Interaction):
            await self._run_action(interaction, "concluir")

        self.assumir_btn.callback = assumir_callback
        self.concluir_btn.callback = concluir_callback
        self.add_item(self.assumir_btn)
        self.add_item(self.concluir_btn)

    def _same_author(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def _run_action(self, interaction: discord.Interaction, action: str):
        if not self._same_author(interaction):
            await interaction.response.send_message("Essa acao nao e sua.", ephemeral=True)
            return

        if self.selected_id is None:
            await interaction.response.send_message(
                "Selecione uma pendencia na lista primeiro.",
                ephemeral=True,
            )
            return

        if action == "assumir":
            ok = db_lideranca_assumir_pendencia(self.guild_id, self.selected_id, str(interaction.user.id))
            msg = f"Voce assumiu a pendencia `#{self.selected_id}`." if ok else "Pendencia nao encontrada ou ja concluida."
        else:
            ok = db_lideranca_concluir_pendencia(self.guild_id, self.selected_id, str(interaction.user.id))
            msg = f"Pendencia `#{self.selected_id}` concluida." if ok else "Pendencia nao encontrada ou ja concluida."

        rows = db_lideranca_listar_pendencias(self.guild_id, limit=25)
        embed = criar_embed_pendencias(rows, "Pendencias Abertas")
        view = PendenciaActionView(self.guild_id, self.author_id, rows) if rows else None
        await interaction.response.edit_message(content=msg, embed=embed, view=view)
        log.info("Pendencia #%s %s por %s (guild %s)", self.selected_id, action, interaction.user, self.guild_id)


class LiderancaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(LiderancaPanelView())

    def _tem_permissao(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        return is_lideranca(member, db_get_lideranca_role_ids(str(interaction.guild_id)))

    async def handle_lideranca_panel(self, interaction: discord.Interaction, custom_id: str):
        if not self._tem_permissao(interaction):
            await interaction.response.send_message(
                "Voce nao tem permissao para usar o painel de lideranca.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)
        action = custom_id.removeprefix("lideranca:")

        try:
            if action == "nova_pendencia":
                await interaction.response.send_modal(NovaPendenciaModal())

            elif action == "ver_pendencias":
                rows = db_lideranca_listar_pendencias(guild_id, limit=15)
                await interaction.response.send_message(
                    embed=criar_embed_pendencias(rows, "Pendencias Abertas"),
                    ephemeral=True,
                )

            elif action == "minhas_tarefas":
                rows = db_lideranca_listar_pendencias(
                    guild_id,
                    responsavel_id=str(interaction.user.id),
                    limit=15,
                )
                await interaction.response.send_message(
                    embed=criar_embed_pendencias(rows, "Minhas Tarefas"),
                    ephemeral=True,
                )

            elif action == "acao_pendencia":
                rows = db_lideranca_listar_pendencias(guild_id, limit=25)
                if not rows:
                    await interaction.response.send_message(
                        "Nao existem pendencias abertas para assumir ou concluir.",
                        ephemeral=True,
                    )
                    return
                await interaction.response.send_message(
                    content="Escolha uma pendencia na lista e depois clique em Assumir ou Concluir.",
                    embed=criar_embed_pendencias(rows, "Assumir ou Concluir Pendencia"),
                    view=PendenciaActionView(guild_id, interaction.user.id, rows),
                    ephemeral=True,
                )

            elif action == "relatorio":
                await interaction.response.send_message(
                    embed=criar_embed_relatorio(db_lideranca_resumo(guild_id)),
                    ephemeral=True,
                )

            else:
                await interaction.response.send_message("Acao desconhecida.", ephemeral=True)

        except Exception as exc:
            log.error("Erro no painel lideranca/%s: %s", custom_id, exc, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Erro interno no painel.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LiderancaCog(bot))
