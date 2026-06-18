"""
Dashboard de Configuração — painel centralizado usando Components V2.
Botões ≡ ficam ao lado de cada sistema via Section + accessory.

Sistemas com modais especializados (campos extras além de canal_interacao/log):
  set       → 5 campos (aprovação, log, categoria, cargo membro, cargos aprovadores)
  farm      → 4 campos (interação, log, cargos liderança, cargos permitidos)
  anuncio   → 3 campos (canal anúncio, log, cargos anunciantes)

Sistemas com modal genérico (canal_interacao + canal_log):
  meta, ausencia, encomenda, acao, hierarquia, adv

Para sistemas com dados em guild_config (ausencia, encomenda, adv, anuncio),
o dashboard sincroniza automaticamente ao salvar.
"""

import re

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.db_service import (
    db_get_guild_config,
    db_get_system_config,
    db_set_guild_config,
    db_set_system_config,
    db_ticket_config_get,
    db_ticket_config_set,
)

log = get_logger("dashboard", "dashboard.log")

# ── Components V2 types ───────────────────────────────────────────────────────

_ACTION_ROW = 1
_BUTTON     = 2
_SECTION    = 9
_TEXT       = 10
_SEPARATOR  = 14
_CONTAINER  = 17
_FLAG_V2    = 1 << 15  # IS_COMPONENTS_V2

# ── Canal fixo do dashboard ───────────────────────────────────────────────────

DASHBOARD_CHANNEL_ID = 1494692392052461588

# ── Sistemas ──────────────────────────────────────────────────────────────────

SISTEMAS = [
    {"key": "set",        "icon": "🎮", "nome": "Sistema de Set",        "desc": "Configure canais, categoria e cargos do sistema de set."},
    {"key": "farm",       "icon": "🌾", "nome": "Sistema de Farm",       "desc": "Configure canal, log e cargos do sistema de farm."},
    {"key": "farm_tickets", "icon": "🎫", "nome": "Tickets de Farm", "desc": "Configure categorias e cargos administrativos dos tickets."},
    {"key": "meta",       "icon": "🎯", "nome": "Sistema de Meta",       "desc": "Configure o sistema de metas semanais."},
    {"key": "ausencia",   "icon": "🏖️", "nome": "Sistema de Ausência",   "desc": "Configure o canal de ausências."},
    {"key": "encomenda",  "icon": "📦", "nome": "Sistema de Encomenda",  "desc": "Configure o canal de encomendas."},
    {"key": "acao",       "icon": "⚡", "nome": "Sistema de Ação",       "desc": "Configure o canal de ações/missões."},
    {"key": "anuncio",    "icon": "📢", "nome": "Sistema de Anúncio",    "desc": "Configure canal, log e cargos do sistema de anúncios."},
    {"key": "hierarquia", "icon": "👑", "nome": "Sistema de Hierarquia", "desc": "Configure o canal de hierarquia de cargos."},
    {"key": "adv",        "icon": "⚠️", "nome": "Sistema de Advertência","desc": "Configure o canal de advertências."},
]

SISTEMAS_PAG1 = SISTEMAS[:7]
SISTEMAS_PAG2 = SISTEMAS[7:]

TOTAL_PAGES = 2


def _sistema_por_key(key: str) -> dict | None:
    for s in SISTEMAS:
        if s["key"] == key:
            return s
    return None


def _parse_ids(text: str) -> list[str]:
    """Extrai IDs de Discord (17-20 dígitos) de uma string."""
    return re.findall(r"\d{17,20}", text)


# ── Payload V2 ────────────────────────────────────────────────────────────────

def _build_payload(page: int) -> dict:
    """Monta o payload Components V2 do dashboard."""
    inner = []

    if page == 0:
        inner.append({
            "type": _TEXT,
            "content": (
                "# Dashboard de Configuração (1/2)\n"
                "Configure os sistemas do bot. Clique em **≡** ao lado de cada sistema."
            ),
        })
        inner.append({"type": _SEPARATOR, "divider": True, "spacing": 1})

        for s in SISTEMAS_PAG1:
            inner.append({
                "type": _SECTION,
                "components": [{"type": _TEXT, "content": f"{s['icon']} **{s['nome']}**\n{s['desc']}"}],
                "accessory": {
                    "type": _BUTTON,
                    "label": "≡",
                    "style": 2,
                    "custom_id": f"dashboard:config_{s['key']}",
                },
            })

        inner.append({"type": _SEPARATOR, "divider": True, "spacing": 1})
        inner.append({
            "type": _ACTION_ROW,
            "components": [
                {"type": _BUTTON, "label": "←", "style": 2, "custom_id": "dashboard:p1_prev", "disabled": True},
                {"type": _BUTTON, "label": "→", "style": 2, "custom_id": "dashboard:p1_next"},
            ],
        })
    else:
        inner.append({
            "type": _TEXT,
            "content": "# Dashboard de Configuração (2/2)",
        })
        inner.append({"type": _SEPARATOR, "divider": True, "spacing": 1})

        for s in SISTEMAS_PAG2:
            inner.append({
                "type": _SECTION,
                "components": [{"type": _TEXT, "content": f"{s['icon']} **{s['nome']}**\n{s['desc']}"}],
                "accessory": {
                    "type": _BUTTON,
                    "label": "≡",
                    "style": 2,
                    "custom_id": f"dashboard:config_{s['key']}",
                },
            })

        inner.append({"type": _SEPARATOR, "divider": True, "spacing": 1})
        inner.append({
            "type": _ACTION_ROW,
            "components": [
                {"type": _BUTTON, "label": "←", "style": 2, "custom_id": "dashboard:p2_prev"},
                {"type": _BUTTON, "label": "→", "style": 2, "custom_id": "dashboard:p2_next", "disabled": True},
            ],
        })

    return {
        "flags": _FLAG_V2,
        "components": [{"type": _CONTAINER, "components": inner}],
    }


# ── HTTP helpers (raw API para V2) ────────────────────────────────────────────

async def _send_v2(channel_id: int, http, payload: dict) -> int:
    route = discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    data = await http.request(route, json=payload)
    return int(data["id"])


async def _edit_v2(interaction: discord.Interaction, payload: dict):
    route = discord.http.Route(
        "POST",
        "/interactions/{interaction_id}/{interaction_token}/callback",
        interaction_id=interaction.id,
        interaction_token=interaction.token,
    )
    await interaction.client.http.request(route, json={"type": 7, "data": payload})
    if hasattr(interaction.response, "_responded"):
        interaction.response._responded = True


async def _delete_old_dashboard(bot, cfg):
    old_msg = cfg["dashboard_message_id"] if "dashboard_message_id" in cfg.keys() else None
    old_ch  = cfg["dashboard_channel_id"]  if "dashboard_channel_id"  in cfg.keys() else None
    if old_msg and old_ch:
        try:
            ch = bot.get_channel(int(old_ch))
            if ch:
                msg = await ch.fetch_message(int(old_msg))
                await msg.delete()
        except Exception:
            pass


# ── Sincronização guild_config ────────────────────────────────────────────────

_GUILD_CONFIG_SYNC = {
    "ausencia":  lambda i_id, l_id: {"canal_ausencias_id":  i_id} if i_id else {},
    "encomenda": lambda i_id, l_id: {"canal_encomendas_id": i_id} if i_id else {},
    "adv":       lambda i_id, l_id: {"canal_adv_id":        i_id} if i_id else {},
}


def _sync_guild_config(guild_id: str, sistema_key: str, interacao_id: str | None, log_id: str | None):
    """Sincroniza guild_config para sistemas que lêem de lá por compatibilidade."""
    fn = _GUILD_CONFIG_SYNC.get(sistema_key)
    if fn:
        fields = fn(interacao_id, log_id)
        if fields:
            db_set_guild_config(guild_id, **fields)


# ── Modais especializados ─────────────────────────────────────────────────────

class SetConfigModal(discord.ui.Modal):
    """Modal com 5 campos para configurar o sistema de set."""

    def __init__(self, current: dict):
        super().__init__(title="🎮 Configurar Sistema de Set")

        self.canal_aprovacao = discord.ui.TextInput(
            label="Canal de Aprovação (ID)",
            placeholder="Cole o ID do canal de aprovações",
            required=False, max_length=20,
            default=current.get("aprovacao", ""),
        )
        self.canal_log = discord.ui.TextInput(
            label="Canal de Log (ID)",
            placeholder="Cole o ID do canal de log",
            required=False, max_length=20,
            default=current.get("log", ""),
        )
        self.categoria_privada = discord.ui.TextInput(
            label="Categoria de Pastas (ID)",
            placeholder="Cole o ID da categoria de canais privados",
            required=False, max_length=20,
            default=current.get("categoria", ""),
        )
        self.cargo_membro = discord.ui.TextInput(
            label="Cargo de Membro (ID)",
            placeholder="Cole o ID do cargo atribuído ao aprovar set",
            required=False, max_length=20,
            default=current.get("membro", ""),
        )
        self.cargos_aprovadores = discord.ui.TextInput(
            label="Cargos Aprovadores (IDs, vírgula)",
            placeholder="Ex: 111222333444555,666777888999000",
            required=False, max_length=300,
            default=current.get("aprovadores", ""),
        )
        self.add_item(self.canal_aprovacao)
        self.add_item(self.canal_log)
        self.add_item(self.categoria_privada)
        self.add_item(self.cargo_membro)
        self.add_item(self.cargos_aprovadores)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id      = str(interaction.guild_id)
        aprovacao_id  = self.canal_aprovacao.value.strip()   or None
        log_id        = self.canal_log.value.strip()          or None
        categoria_id  = self.categoria_privada.value.strip()  or None
        membro_id     = self.cargo_membro.value.strip()       or None
        aprovadores   = self.cargos_aprovadores.value.strip() or None

        # Validar IDs numéricos
        for val, nome in [
            (aprovacao_id, "Canal de Aprovação"), (log_id, "Canal de Log"),
            (categoria_id, "Categoria"),          (membro_id, "Cargo de Membro"),
        ]:
            if val and not val.isdigit():
                await interaction.response.send_message(f"❌ **{nome}** deve conter apenas números.", ephemeral=True)
                return

        # Salvar em guild_config
        guild_fields = {}
        if aprovacao_id: guild_fields["approval_channel_id"] = aprovacao_id
        if log_id:       guild_fields["log_channel_id"]       = log_id
        if categoria_id: guild_fields["private_category_id"]  = categoria_id
        if membro_id:    guild_fields["member_role_id"]        = membro_id
        if aprovadores is not None:
            ids = _parse_ids(aprovadores)
            guild_fields["approver_role_ids"] = ",".join(ids)
        if guild_fields:
            db_set_guild_config(guild_id, **guild_fields)

        # Salvar em system_config
        db_set_system_config(guild_id, "set", aprovacao_id, log_id)

        linhas = ["✅ **Sistema de Set** configurado!\n"]
        if aprovacao_id: linhas.append(f"**Canal de Aprovação:** <#{aprovacao_id}>")
        if log_id:       linhas.append(f"**Canal de Log:** <#{log_id}>")
        if categoria_id: linhas.append(f"**Categoria de Pastas:** <#{categoria_id}>")
        if membro_id:    linhas.append(f"**Cargo de Membro:** <@&{membro_id}>")
        if aprovadores:
            ids = _parse_ids(aprovadores)
            linhas.append(f"**Cargos Aprovadores:** {' '.join(f'<@&{i}>' for i in ids)}")

        embed = discord.Embed(description="\n".join(linhas), color=0x2ECC71)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Set configurado por %s (guild %s)", interaction.user, guild_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no SetConfigModal: %s", error, exc_info=True)
        try:
            await interaction.response.send_message("❌ Erro ao salvar configuração.", ephemeral=True)
        except discord.InteractionResponded:
            pass


class FarmConfigModal(discord.ui.Modal):
    """Modal com 4 campos para configurar o sistema de farm."""

    def __init__(self, current: dict):
        super().__init__(title="🌾 Configurar Sistema de Farm")

        self.canal_interacao = discord.ui.TextInput(
            label="Canal de Interação (ID)",
            placeholder="Canal onde o painel de farm fica",
            required=False, max_length=20,
            default=current.get("interacao", ""),
        )
        self.canal_log = discord.ui.TextInput(
            label="Canal de Log (ID)",
            placeholder="Canal onde os logs de farm são enviados",
            required=False, max_length=20,
            default=current.get("log", ""),
        )
        self.cargos_lideranca = discord.ui.TextInput(
            label="Cargos de Liderança (IDs, vírgula)",
            placeholder="Ex: 111222333444555,666777888999000",
            required=False, max_length=300,
            default=current.get("lideranca", ""),
        )
        self.cargos_permitidos = discord.ui.TextInput(
            label="Cargos Permitidos (IDs, vírgula)",
            placeholder="Ex: 111222333444555,666777888999000",
            required=False, max_length=300,
            default=current.get("permitidos", ""),
        )
        self.cargos_editar = discord.ui.TextInput(
            label="Cargos Editar Farm (IDs, vírgula)",
            placeholder="Podem editar farm próprio no painel de operações",
            required=False, max_length=300,
            default=current.get("editores", ""),
        )
        self.add_item(self.canal_interacao)
        self.add_item(self.canal_log)
        self.add_item(self.cargos_lideranca)
        self.add_item(self.cargos_permitidos)
        self.add_item(self.cargos_editar)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id    = str(interaction.guild_id)
        interacao_id = self.canal_interacao.value.strip()   or None
        log_id       = self.canal_log.value.strip()          or None
        lideranca    = self.cargos_lideranca.value.strip()   or None
        permitidos   = self.cargos_permitidos.value.strip()  or None
        editores     = self.cargos_editar.value.strip()      or None

        for val, nome in [(interacao_id, "Canal de Interação"), (log_id, "Canal de Log")]:
            if val and not val.isdigit():
                await interaction.response.send_message(f"❌ **{nome}** deve conter apenas números.", ephemeral=True)
                return

        # Salvar em system_config
        db_set_system_config(guild_id, "farm", interacao_id, log_id)

        # Salvar cargos em guild_config
        guild_fields = {}
        if lideranca is not None:
            ids = _parse_ids(lideranca)
            guild_fields["cargos_lideranca_farm"] = ",".join(ids)
        if permitidos is not None:
            ids = _parse_ids(permitidos)
            guild_fields["cargos_permitidos_farm"] = ",".join(ids)
        if editores is not None:
            ids = _parse_ids(editores)
            guild_fields["cargos_editar_farm"] = ",".join(ids)
        if guild_fields:
            db_set_guild_config(guild_id, **guild_fields)

        linhas = ["✅ **Sistema de Farm** configurado!\n"]
        if interacao_id: linhas.append(f"**Canal de Interação:** <#{interacao_id}>")
        if log_id:       linhas.append(f"**Canal de Log:** <#{log_id}>")
        if lideranca:
            ids = _parse_ids(lideranca)
            linhas.append(f"**Liderança:** {' '.join(f'<@&{i}>' for i in ids)}")
        if permitidos:
            ids = _parse_ids(permitidos)
            linhas.append(f"**Permitidos:** {' '.join(f'<@&{i}>' for i in ids)}")
        if editores:
            ids = _parse_ids(editores)
            linhas.append(f"**Editores Farm:** {' '.join(f'<@&{i}>' for i in ids)}")

        embed = discord.Embed(description="\n".join(linhas), color=0x2ECC71)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Farm configurado por %s (guild %s)", interaction.user, guild_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no FarmConfigModal: %s", error, exc_info=True)
        try:
            await interaction.response.send_message("❌ Erro ao salvar configuração.", ephemeral=True)
        except discord.InteractionResponded:
            pass


class AnuncioConfigModal(discord.ui.Modal):
    """Modal com 3 campos para configurar o sistema de anúncios."""

    def __init__(self, current: dict):
        super().__init__(title="📢 Configurar Sistema de Anúncio")

        self.canal_anuncio = discord.ui.TextInput(
            label="Canal de Anúncios (ID)",
            placeholder="Canal onde os anúncios serão publicados",
            required=False, max_length=20,
            default=current.get("canal", ""),
        )
        self.canal_log = discord.ui.TextInput(
            label="Canal de Log (ID)",
            placeholder="Canal onde os logs de anúncios são enviados",
            required=False, max_length=20,
            default=current.get("log", ""),
        )
        self.cargos_anuncio = discord.ui.TextInput(
            label="Cargos Anunciantes (IDs, vírgula)",
            placeholder="Ex: 111222333444555,666777888999000",
            required=False, max_length=300,
            default=current.get("cargos", ""),
        )
        self.add_item(self.canal_anuncio)
        self.add_item(self.canal_log)
        self.add_item(self.cargos_anuncio)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id   = str(interaction.guild_id)
        canal_id   = self.canal_anuncio.value.strip()  or None
        log_id     = self.canal_log.value.strip()       or None
        cargos     = self.cargos_anuncio.value.strip()  or None

        for val, nome in [(canal_id, "Canal de Anúncios"), (log_id, "Canal de Log")]:
            if val and not val.isdigit():
                await interaction.response.send_message(f"❌ **{nome}** deve conter apenas números.", ephemeral=True)
                return

        # Salvar em system_config
        db_set_system_config(guild_id, "anuncio", canal_id, log_id)

        # Salvar em guild_config para compatibilidade com AnuncioPainelView
        guild_fields = {}
        if canal_id: guild_fields["canal_anuncio_id"] = canal_id
        if cargos is not None:
            ids = _parse_ids(cargos)
            guild_fields["cargos_anuncio"] = ",".join(ids)
        if guild_fields:
            db_set_guild_config(guild_id, **guild_fields)

        linhas = ["✅ **Sistema de Anúncio** configurado!\n"]
        if canal_id: linhas.append(f"**Canal de Anúncios:** <#{canal_id}>")
        if log_id:   linhas.append(f"**Canal de Log:** <#{log_id}>")
        if cargos:
            ids = _parse_ids(cargos)
            linhas.append(f"**Cargos Anunciantes:** {' '.join(f'<@&{i}>' for i in ids)}")

        embed = discord.Embed(description="\n".join(linhas), color=0x2ECC71)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Anúncio configurado por %s (guild %s)", interaction.user, guild_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no AnuncioConfigModal: %s", error, exc_info=True)
        try:
            await interaction.response.send_message("❌ Erro ao salvar configuração.", ephemeral=True)
        except discord.InteractionResponded:
            pass


class FarmTicketsConfigModal(discord.ui.Modal, title="Configurar Tickets de Farm"):
    def __init__(self, current: dict | None = None):
        super().__init__()
        current = current or {}
        self.categories = discord.ui.TextInput(
            label="IDs das categorias de tickets",
            placeholder="Separe múltiplas categorias por vírgula",
            default=",".join(current.get("category_ids", [])) or None,
            required=True,
            max_length=500,
        )
        self.admin_roles = discord.ui.TextInput(
            label="IDs dos cargos administradores",
            placeholder="Separe múltiplos cargos por vírgula",
            default=",".join(current.get("admin_role_ids", [])) or None,
            required=True,
            max_length=500,
        )
        self.add_item(self.categories)
        self.add_item(self.admin_roles)

    async def on_submit(self, interaction: discord.Interaction):
        category_ids = [int(value) for value in _parse_ids(self.categories.value)]
        role_ids = [int(value) for value in _parse_ids(self.admin_roles.value)]
        if not category_ids or not role_ids:
            await interaction.response.send_message(
                "Informe ao menos uma categoria e um cargo administrativo válidos.", ephemeral=True
            )
            return
        invalid_categories = [value for value in category_ids if not isinstance(interaction.guild.get_channel(value), discord.CategoryChannel)]
        invalid_roles = [value for value in role_ids if interaction.guild.get_role(value) is None]
        if invalid_categories or invalid_roles:
            await interaction.response.send_message(
                "Há IDs que não correspondem a categorias ou cargos deste servidor.", ephemeral=True
            )
            return
        farm_log = db_get_system_config(str(interaction.guild_id), "farm")
        if not farm_log or not farm_log["canal_log_id"]:
            await interaction.response.send_message(
                "Configure primeiro o canal de log do Sistema de Farm.", ephemeral=True
            )
            return
        db_ticket_config_set(str(interaction.guild_id), category_ids, role_ids)
        await interaction.response.send_message(
            "✅ Tickets de farm configurados. O canal de log existente do Farm será reutilizado.",
            ephemeral=True,
        )


class SystemConfigModal(discord.ui.Modal):
    """Modal genérico: canal_interacao + canal_log, com sync opcional para guild_config."""

    def __init__(self, sistema_key: str, sistema_nome: str,
                 current_interacao: str = "", current_log: str = ""):
        super().__init__(title=f"Configurar {sistema_nome}"[:45])
        self.sistema_key = sistema_key

        self.canal_interacao = discord.ui.TextInput(
            label="Canal de Interação (ID do canal)",
            placeholder="Cole o ID do canal",
            required=False, max_length=20,
            default=current_interacao,
        )
        self.canal_log = discord.ui.TextInput(
            label="Canal de Log (ID do canal)",
            placeholder="Cole o ID do canal",
            required=False, max_length=20,
            default=current_log,
        )
        self.add_item(self.canal_interacao)
        self.add_item(self.canal_log)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id     = str(interaction.guild_id)
        interacao_id = self.canal_interacao.value.strip() or None
        log_id       = self.canal_log.value.strip()        or None

        for val, nome in [(interacao_id, "Canal de Interação"), (log_id, "Canal de Log")]:
            if val and not val.isdigit():
                await interaction.response.send_message(
                    f"❌ O **{nome}** deve conter apenas números.", ephemeral=True
                )
                return

        # Valida canais no servidor
        guild = interaction.guild
        for val, nome in [(interacao_id, "Canal de Interação"), (log_id, "Canal de Log")]:
            if val:
                ch = guild.get_channel(int(val))
                if ch is None:
                    try:
                        ch = await guild.fetch_channel(int(val))
                    except Exception:
                        await interaction.response.send_message(
                            f"❌ Canal `{val}` (**{nome}**) não encontrado neste servidor.", ephemeral=True
                        )
                        return

        db_set_system_config(guild_id, self.sistema_key, interacao_id, log_id)

        # Sincroniza guild_config para sistemas legados
        _sync_guild_config(guild_id, self.sistema_key, interacao_id, log_id)

        sistema = _sistema_por_key(self.sistema_key)
        nome_sistema = sistema["nome"] if sistema else self.sistema_key

        linhas = [f"✅ **{nome_sistema}** configurado com sucesso!\n"]
        linhas.append(f"**Canal de Interação:** {'<#' + interacao_id + '>' if interacao_id else '_não definido_'}")
        linhas.append(f"**Canal de Log:** {'<#' + log_id + '>' if log_id else '_não definido_'}")

        embed = discord.Embed(description="\n".join(linhas), color=0x2ECC71)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Sistema '%s' configurado por %s (guild %s)", self.sistema_key, interaction.user, guild_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Erro no SystemConfigModal: %s", error, exc_info=True)
        try:
            await interaction.response.send_message("❌ Erro ao salvar configuração.", ephemeral=True)
        except discord.InteractionResponded:
            pass


# ── Handler de botão de configuração ─────────────────────────────────────────

async def _handle_config_button(interaction: discord.Interaction, sistema_key: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ Você precisa da permissão **Gerenciar Servidor** para configurar sistemas.",
            ephemeral=True,
        )
        return

    sistema = _sistema_por_key(sistema_key)
    if not sistema:
        await interaction.response.send_message("❌ Sistema não encontrado.", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    row = db_get_system_config(guild_id, sistema_key)
    current_interacao = (row["canal_interacao_id"] or "") if row else ""
    current_log       = (row["canal_log_id"]       or "") if row else ""
    cfg = db_get_guild_config(guild_id)

    def _cfg(col: str) -> str:
        if cfg is None:
            return ""
        try:
            return cfg[col] or ""
        except (IndexError, KeyError):
            return ""

    if sistema_key == "set":
        modal = SetConfigModal(current={
            "aprovacao":  _cfg("approval_channel_id"),
            "log":        _cfg("log_channel_id"),
            "categoria":  _cfg("private_category_id"),
            "membro":     _cfg("member_role_id"),
            "aprovadores": _cfg("approver_role_ids"),
        })

    elif sistema_key == "farm":
        modal = FarmConfigModal(current={
            "interacao":  current_interacao,
            "log":        current_log,
            "lideranca":  _cfg("cargos_lideranca_farm"),
            "permitidos": _cfg("cargos_permitidos_farm"),
            "editores":   _cfg("cargos_editar_farm"),
        })

    elif sistema_key == "farm_tickets":
        modal = FarmTicketsConfigModal(current=db_ticket_config_get(guild_id))

    elif sistema_key == "anuncio":
        modal = AnuncioConfigModal(current={
            "canal":  _cfg("canal_anuncio_id") or current_interacao,
            "log":    current_log,
            "cargos": _cfg("cargos_anuncio"),
        })

    else:
        modal = SystemConfigModal(
            sistema_key=sistema_key,
            sistema_nome=sistema["nome"],
            current_interacao=current_interacao,
            current_log=current_log,
        )

    await interaction.response.send_modal(modal)


# ── Dispatcher View (persistente) ─────────────────────────────────────────────

class _DashboardDispatcher(discord.ui.View):
    """View registrada apenas para roteamento persistente de custom_ids.
    Nunca é renderizada diretamente — a mensagem usa payload V2 raw."""

    def __init__(self):
        super().__init__(timeout=None)

        # Botões de config — 10 sistemas, 5 por row (rows 0 e 1)
        for i, s in enumerate(SISTEMAS):
            btn = discord.ui.Button(
                custom_id=f"dashboard:config_{s['key']}",
                style=discord.ButtonStyle.secondary,
                label="≡",
                row=0 if i < 5 else 1,
            )

            def _make_cb(key: str):
                async def cb(inter: discord.Interaction):
                    await _handle_config_button(inter, key)
                return cb

            btn.callback = _make_cb(s["key"])
            self.add_item(btn)

        # Botões de navegação (rows 2-3)
        nav_defs = [
            ("dashboard:p1_prev", None, 2),
            ("dashboard:p1_next", 1,    2),
            ("dashboard:p2_prev", 0,    3),
            ("dashboard:p2_next", None, 3),
        ]
        for cid, target_page, row in nav_defs:
            btn = discord.ui.Button(
                custom_id=cid,
                style=discord.ButtonStyle.secondary,
                label="→",
                row=row,
            )
            if target_page is not None:
                def _make_nav(p: int):
                    async def cb(inter: discord.Interaction):
                        await _edit_v2(inter, _build_payload(p))
                    return cb
                btn.callback = _make_nav(target_page)
            else:
                async def _noop(inter: discord.Interaction):
                    await inter.response.defer()
                btn.callback = _noop
            self.add_item(btn)


# ── Cog ───────────────────────────────────────────────────────────────────────

class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(_DashboardDispatcher())

    @app_commands.command(
        name="setup_dashboard",
        description="Posta o dashboard de configuração no canal fixo do bot.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        channel = self.bot.get_channel(DASHBOARD_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(DASHBOARD_CHANNEL_ID)
            except Exception:
                await interaction.followup.send(
                    f"❌ Canal fixo do dashboard (`{DASHBOARD_CHANNEL_ID}`) não encontrado.",
                    ephemeral=True,
                )
                return

        cfg = db_get_guild_config(guild_id)
        if cfg:
            await _delete_old_dashboard(self.bot, cfg)

        payload = _build_payload(0)
        msg_id = await _send_v2(DASHBOARD_CHANNEL_ID, self.bot.http, payload)

        db_set_guild_config(
            guild_id,
            dashboard_channel_id=str(DASHBOARD_CHANNEL_ID),
            dashboard_message_id=str(msg_id),
        )

        await interaction.followup.send(
            f"✅ Dashboard postado em <#{DASHBOARD_CHANNEL_ID}>!", ephemeral=True
        )
        log.info("Dashboard postado (guild %s, msg %s)", guild_id, msg_id)

    @setup_dashboard.error
    async def _setup_dashboard_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
        else:
            log.error("Erro no /setup_dashboard: %s", error, exc_info=True)
            try:
                await interaction.response.send_message("❌ Ocorreu um erro inesperado.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("❌ Ocorreu um erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardCog(bot))
    log.info("DashboardCog carregado com sucesso.")
