import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import json
import os

# ─────────────────────────────────────────────
#  CONFIGURAÇÕES
# ─────────────────────────────────────────────
CANAL_AUSENCIAS_ID = 1474869321187459147
ARQUIVO_JSON       = "ausencias.json"
COR_EMBED          = 0xF0A500  # laranja

# ─────────────────────────────────────────────
#  HELPERS DE JSON
# ─────────────────────────────────────────────
def carregar():
    if not os.path.exists(ARQUIVO_JSON):
        return {}
    with open(ARQUIVO_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar(dados):
    with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
#  MODAL — formulário que abre ao clicar
# ─────────────────────────────────────────────
class AusenciaModal(discord.ui.Modal, title="📋 Registrar Ausência"):

    dias = discord.ui.TextInput(
        label="Quantos dias ficará fora?",
        placeholder="Ex: 5  (máximo 7 dias)",
        min_length=1,
        max_length=1,
        required=True,
    )

    motivo = discord.ui.TextInput(
        label="Motivo da ausência",
        placeholder="Ex: Viagem, trabalho, problemas pessoais...",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.dias.value.strip().isdigit():
            await interaction.followup.send("❌ Digite apenas o número de dias.", ephemeral=True)
            return

        dias_int = int(self.dias.value.strip())

        if dias_int < 1:
            await interaction.followup.send("❌ O número de dias precisa ser pelo menos 1.", ephemeral=True)
            return

        if dias_int > 7:
            await interaction.followup.send(
                "❌ Ausências acima de **7 dias** resultam em **PD automático**.\n"
                "Entre em contato com a administração.",
                ephemeral=True
            )
            return

        motivo_texto = self.motivo.value.strip() or "Não informado"
        alerta_pd    = dias_int > 3

        inicio = datetime.utcnow()
        fim    = inicio + timedelta(days=dias_int)

        dados   = carregar()
        user_id = str(interaction.user.id)

        dados[user_id] = {
            "nome"      : interaction.user.display_name,
            "dias"      : dias_int,
            "motivo"    : motivo_texto,
            "inicio"    : inicio.isoformat(),
            "fim"       : fim.isoformat(),
            "avisado"   : False,
            "message_id": None,
        }
        salvar(dados)

        aviso_pd = (
            "\n\n⚠️ **Atenção:** você está no limite. Se ultrapassar **7 dias sem novo aviso**, "
            "receberá **PD automático**."
            if alerta_pd else ""
        )

        canal = interaction.guild.get_channel(CANAL_AUSENCIAS_ID)
        if canal is None:
            await interaction.followup.send(
                "❌ Canal de ausências não encontrado. Avise um admin.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏖️ Registro de Ausência",
            color=COR_EMBED,
            timestamp=inicio,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.description = (
            f"**{interaction.user.display_name}** estará ausente do RP por **{dias_int} dia(s)**."
            + aviso_pd
        )
        embed.add_field(name="👤 Jogador",    value=interaction.user.mention,          inline=True)
        embed.add_field(name="📅 Dias fora",  value=f"`{dias_int} dia(s)`",            inline=True)
        embed.add_field(name="🔙 Retorno",    value=f"`{fim.strftime('%d/%m/%Y')}`",   inline=True)
        embed.add_field(name="📝 Motivo",     value=motivo_texto,                      inline=False)
        embed.set_footer(text="Sistema de Ausências • Cidade")

        msg = await canal.send(embed=embed)

        dados[user_id]["message_id"] = msg.id
        salvar(dados)

        await interaction.followup.send(
            f"✅ Ausência registrada com sucesso! Confira em {canal.mention}.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
        except Exception:
            pass

# ─────────────────────────────────────────────
#  VIEW — painel com botão persistente
# ─────────────────────────────────────────────
class AusenciaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 Registrar Ausência",
        style=discord.ButtonStyle.primary,
        custom_id="ausencia_panel:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AusenciaModal())

# ─────────────────────────────────────────────
#  COG
# ─────────────────────────────────────────────
class Ausencia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.verificar_ausencias.start()

    async def cog_load(self):
        self.bot.add_view(AusenciaPanelView())

    @app_commands.command(
        name="setup_ausencia",
        description="Posta o painel de registro de ausência no canal atual. (Apenas admins)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_ausencia(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏖️ Sistema de Ausência",
            description=(
                "Vai ficar fora da cidade por um tempo?\n\n"
                "Clique no botão abaixo para registrar sua ausência.\n\n"
                "📌 **Regras:**\n"
                "• Ausências de até **3 dias** — registre e fique tranquilo\n"
                "• Ausências de **3 a 7 dias** — registre com atenção ao prazo\n"
                "• **Mais de 7 dias sem aviso** — PD automático aplicado\n\n"
                "Sempre renove seu aviso se precisar de mais tempo."
            ),
            color=COR_EMBED,
        )
        embed.set_footer(text="Sistema de Ausências • Cidade")

        view = AusenciaPanelView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Painel de ausências postado!", ephemeral=True)

    @app_commands.command(
        name="ausencias",
        description="Lista todos os jogadores atualmente ausentes."
    )
    async def listar_ausencias(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        dados  = carregar()
        agora  = datetime.utcnow()
        ativos = {
            uid: v for uid, v in dados.items()
            if datetime.fromisoformat(v["fim"]) > agora
        }

        if not ativos:
            await interaction.followup.send("✅ Nenhum jogador ausente no momento.")
            return

        embed = discord.Embed(
            title="📋 Jogadores em Ausência",
            color=COR_EMBED,
            timestamp=agora,
        )
        embed.set_footer(text="Sistema de Ausências • Cidade")

        for uid, info in ativos.items():
            fim_dt = datetime.fromisoformat(info["fim"])
            restam = max((fim_dt - agora).days + 1, 0)
            embed.add_field(
                name=f"👤 {info['nome']}",
                value=(
                    f"Retorno: `{fim_dt.strftime('%d/%m/%Y')}`\n"
                    f"Dias restantes: `{restam}`\n"
                    f"Motivo: {info['motivo']}"
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @tasks.loop(hours=1)
    async def verificar_ausencias(self):
        await self.bot.wait_until_ready()
        dados       = carregar()
        agora       = datetime.utcnow()
        salvar_flag = False

        for uid, info in dados.items():
            fim_dt = datetime.fromisoformat(info["fim"])

            if agora >= fim_dt and not info.get("avisado"):
                guild = self.bot.guilds[0] if self.bot.guilds else None
                if guild:
                    membro = guild.get_member(int(uid))
                    if membro:
                        try:
                            await membro.send(
                                f"⏰ **Sua ausência venceu hoje ({fim_dt.strftime('%d/%m/%Y')}).**\n"
                                f"Se precisar de mais tempo, registre uma nova ausência pelo painel.\n"
                                f"Lembre-se: mais de **7 dias sem aviso** resulta em **PD automático**."
                            )
                        except discord.Forbidden:
                            pass

                dados[uid]["avisado"] = True
                salvar_flag = True

        if salvar_flag:
            salvar(dados)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ausencia(bot))