"""
cogs/hierarquia.py - Painel de gerenciamento de hierarquia de cargos.

Embed fixo no canal configurado (sistema "hierarquia" via dashboard).
Quem pode usar: | 01 Dono, | 02, | 03
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import db_get_system_config
from services.log_service import send_log

log = get_logger("hierarquia", "bot.log")

COR_HIERARQUIA = 0xFFD700
FOOTER_HIERARQUIA = "Morro do Mineiro — Sistema de Hierarquia"

HIERARQUIA_CARGOS = [
    "| Pedir Set",
    "| Membro",
    "| Gerente de Recrutamento",
    "| Gerente de Ação",
    "| Gerente de Farm",
    "| Gerente de Produção",
    "| Gerente Geral",
    "| 03",
    "| 02",
    "| 01 Dono",
]

CARGOS_IGNORADOS = {
    "| Bots", "| Programador Dev", "| Loritta", "| Rio Bot",
    "| Server Booster", "| Medal", "| Morro Do Mineiro", "| Advertência",
}

CARGOS_AUTORIZADOS = {"| 01 Dono", "| 02", "| 03"}
CARGOS_AUTORIZADOS_IDS = {1474869320684146847, 1474869320684146846, 1490821840191619322}


def _tem_permissao(member: discord.Member) -> bool:
    return any(
        r.name in CARGOS_AUTORIZADOS or r.id in CARGOS_AUTORIZADOS_IDS
        for r in member.roles
    )


def _cargo_hierarquia_atual(member: discord.Member) -> discord.Role | None:
    """Retorna o cargo de hierarquia mais alto que o membro possui."""
    melhor = None
    melhor_idx = -1
    for role in member.roles:
        if role.name in HIERARQUIA_CARGOS:
            idx = HIERARQUIA_CARGOS.index(role.name)
            if idx > melhor_idx:
                melhor_idx = idx
                melhor = role
    return melhor


def _tipo_mudanca(cargo_anterior: str | None, cargo_novo: str) -> str:
    if cargo_anterior is None:
        return "ATRIBUIÇÃO"
    idx_ant = HIERARQUIA_CARGOS.index(cargo_anterior) if cargo_anterior in HIERARQUIA_CARGOS else -1
    idx_nov = HIERARQUIA_CARGOS.index(cargo_novo) if cargo_novo in HIERARQUIA_CARGOS else -1
    if idx_nov > idx_ant:
        return "PROMOÇÃO"
    if idx_nov < idx_ant:
        return "REBAIXAMENTO"
    return "REATRIBUIÇÃO"


# ── View de seleção de cargo (segunda etapa) ──────────────────────────────────

class CargosSelectView(discord.ui.View):
    def __init__(self, executor: discord.Member, membro_alvo: discord.Member):
        super().__init__(timeout=120)
        self.executor = executor
        self.membro_alvo = membro_alvo

        options = [
            discord.SelectOption(label=nome, value=nome)
            for nome in HIERARQUIA_CARGOS
        ]
        select = discord.ui.Select(
            placeholder="Selecione o novo cargo...",
            options=options,
            custom_id="hierarquia:select_cargo",
        )
        select.callback = self._on_cargo_select
        self.add_item(select)

    async def _on_cargo_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.executor.id:
            await interaction.response.send_message(
                "❌ Apenas quem iniciou pode usar este menu.", ephemeral=True
            )
            return

        novo_cargo_nome = interaction.data["values"][0]
        guild = interaction.guild

        novo_cargo = discord.utils.get(guild.roles, name=novo_cargo_nome)
        if novo_cargo is None:
            await interaction.response.send_message(
                f"❌ Cargo **{novo_cargo_nome}** não encontrado neste servidor.",
                ephemeral=True,
            )
            return

        cargo_anterior = _cargo_hierarquia_atual(self.membro_alvo)
        cargo_anterior_nome = cargo_anterior.name if cargo_anterior else None
        tipo = _tipo_mudanca(cargo_anterior_nome, novo_cargo_nome)

        # Remove todos os cargos de hierarquia e aplica o novo
        cargos_para_remover = [
            r for r in self.membro_alvo.roles
            if r.name in HIERARQUIA_CARGOS
        ]
        try:
            if cargos_para_remover:
                await self.membro_alvo.remove_roles(*cargos_para_remover, reason=f"Hierarquia por {self.executor}")
            await self.membro_alvo.add_roles(novo_cargo, reason=f"Hierarquia por {self.executor}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Sem permissão para alterar cargos deste membro.", ephemeral=True
            )
            return
        except Exception as e:
            log.error("Erro ao alterar cargo de hierarquia: %s", e, exc_info=True)
            await interaction.response.send_message("❌ Erro ao aplicar o cargo.", ephemeral=True)
            return

        tipo_emoji = "⬆️" if tipo == "PROMOÇÃO" else ("⬇️" if tipo == "REBAIXAMENTO" else "🔄")
        confirmacao = discord.Embed(
            title=f"{tipo_emoji} Hierarquia Atualizada",
            color=COR_HIERARQUIA,
            timestamp=discord.utils.utcnow(),
        )
        confirmacao.add_field(name="👤 Membro", value=self.membro_alvo.mention, inline=True)
        confirmacao.add_field(name="📉 Cargo anterior", value=cargo_anterior_nome or "_nenhum_", inline=True)
        confirmacao.add_field(name="📈 Novo cargo", value=f"**{novo_cargo_nome}**", inline=True)
        confirmacao.add_field(name="🏷️ Tipo", value=f"`{tipo}`", inline=True)
        confirmacao.set_footer(text=FOOTER_HIERARQUIA)

        await interaction.response.edit_message(embed=confirmacao, view=None)

        log_embed = discord.Embed(
            title=f"{tipo_emoji} Hierarquia Atualizada — {tipo}",
            color=COR_HIERARQUIA,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(
            name="⚙️ Executado por",
            value=f"{self.executor.mention}\n`{self.executor.id}`",
            inline=True,
        )
        log_embed.add_field(
            name="👤 Membro afetado",
            value=f"{self.membro_alvo.mention}\n`{self.membro_alvo.id}`",
            inline=True,
        )
        log_embed.add_field(name="📉 Cargo anterior", value=cargo_anterior_nome or "_nenhum_", inline=True)
        log_embed.add_field(name="📈 Novo cargo", value=f"**{novo_cargo_nome}**", inline=True)
        log_embed.add_field(name="🏷️ Tipo", value=f"`{tipo}`", inline=True)
        log_embed.set_footer(text=FOOTER_HIERARQUIA)

        await send_log(interaction.client, guild, "hierarquia", log_embed)
        log.info(
            "Hierarquia: %s → %s → %s (tipo=%s, executor=%s)",
            self.membro_alvo.id, cargo_anterior_nome, novo_cargo_nome, tipo, self.executor.id,
        )

        self.stop()


# ── View de seleção de membro (primeira etapa) ────────────────────────────────

class MembrosSelectView(discord.ui.View):
    def __init__(self, executor: discord.Member):
        super().__init__(timeout=120)
        self.executor = executor

        select = discord.ui.UserSelect(
            placeholder="Selecione o membro...",
            custom_id="hierarquia:select_membro",
        )
        select.callback = self._on_membro_select
        self.add_item(select)

    async def _on_membro_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.executor.id:
            await interaction.response.send_message(
                "❌ Apenas quem iniciou pode usar este menu.", ephemeral=True
            )
            return

        user_ids = interaction.data.get("values", [])
        if not user_ids:
            await interaction.response.send_message("❌ Nenhum membro selecionado.", ephemeral=True)
            return

        membro = interaction.guild.get_member(int(user_ids[0]))
        if membro is None:
            try:
                membro = await interaction.guild.fetch_member(int(user_ids[0]))
            except Exception:
                await interaction.response.send_message("❌ Membro não encontrado no servidor.", ephemeral=True)
                return

        cargo_atual = _cargo_hierarquia_atual(membro)
        embed = discord.Embed(
            title="👑 Selecione o Novo Cargo",
            description=(
                f"**Membro:** {membro.mention}\n"
                f"**Cargo atual:** {cargo_atual.name if cargo_atual else '_nenhum_'}\n\n"
                "Escolha o novo cargo de hierarquia:"
            ),
            color=COR_HIERARQUIA,
        )
        embed.set_footer(text=FOOTER_HIERARQUIA)

        view = CargosSelectView(executor=self.executor, membro_alvo=membro)
        await interaction.response.edit_message(embed=embed, view=view)
        self.stop()


# ── View do painel principal (persistente) ────────────────────────────────────

class HierarquiaPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="👑 Gerenciar Hierarquia",
        style=discord.ButtonStyle.primary,
        custom_id="hierarquia:gerenciar",
    )
    async def gerenciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _tem_permissao(interaction.user):
            await interaction.response.send_message(
                "❌ Você não tem permissão para gerenciar a hierarquia.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="👑 Gerenciar Hierarquia",
            description="Selecione o membro que deseja promover ou rebaixar:",
            color=COR_HIERARQUIA,
        )
        embed.set_footer(text=FOOTER_HIERARQUIA)

        view = MembrosSelectView(executor=interaction.user)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ── Embed fixo do painel ──────────────────────────────────────────────────────

def _build_painel_embed() -> discord.Embed:
    lista_cargos = "\n".join(
        f"`{i+1}.` {nome}" for i, nome in enumerate(HIERARQUIA_CARGOS)
    )
    embed = discord.Embed(
        title="👑 Painel de Hierarquia — Morro do Mineiro",
        description=(
            "Gerencie os cargos de hierarquia do servidor.\n\n"
            f"**Cargos disponíveis (do menor ao maior):**\n{lista_cargos}\n\n"
            "Use o botão abaixo para promover ou rebaixar um membro."
        ),
        color=COR_HIERARQUIA,
    )
    embed.set_footer(text=FOOTER_HIERARQUIA)
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class HierarquiaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(HierarquiaPainelView())

    @app_commands.command(
        name="setup_hierarquia",
        description="Posta o painel de hierarquia no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_hierarquia(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        row = db_get_system_config(guild_id, "hierarquia")
        if not row or not row["canal_interacao_id"]:
            await interaction.followup.send(
                "❌ Configure o canal do sistema de Hierarquia no dashboard primeiro.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(row["canal_interacao_id"]))
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(int(row["canal_interacao_id"]))
            except Exception:
                await interaction.followup.send(
                    "❌ Canal configurado não encontrado.", ephemeral=True
                )
                return

        await channel.send(embed=_build_painel_embed(), view=HierarquiaPainelView())
        await interaction.followup.send(
            f"✅ Painel de hierarquia postado em {channel.mention}!", ephemeral=True
        )
        log.info("Painel hierarquia postado (guild %s, canal %s)", guild_id, channel.id)

    @setup_hierarquia.error
    async def _setup_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
        else:
            log.error("Erro em /setup_hierarquia: %s", error, exc_info=True)
            try:
                await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HierarquiaCog(bot))
    log.info("HierarquiaCog carregado com sucesso.")
