"""
Configuração centralizada dos painéis de operações e set.
Níveis de acesso, permissões, visual (cores, botões).
"""

# ═════════════════════════════════════════════════════════════════
# NÍVEIS DE ACESSO
# ═════════════════════════════════════════════════════════════════

NIVEIS_ACESSO = {
    "lider": 0,        # acesso completo ao painel
    "vice_lider": 1,   # acesso completo ao painel
    "gerente": 2,      # acesso completo ao painel
    "membro": 3        # acesso limitado (apenas farm pessoal)
}

# Conjunto de níveis com acesso de liderança — usado para verificações
NIVEIS_LIDERANCA: frozenset[str] = frozenset({"lider", "vice_lider", "gerente"})

# ═════════════════════════════════════════════════════════════════
# PERMISSÕES: função -> níveis que acessam
# ═════════════════════════════════════════════════════════════════

PERMISSOES_PAINEL_OPERACOES = {
    "ver_meu_farm": ["lider", "vice_lider", "gerente", "membro"],
    "aprovar_farm": ["lider", "vice_lider", "gerente"],
    "editar_farm":  ["lider", "vice_lider", "gerente"],
    "definir_metas":["lider", "vice_lider", "gerente"],
    "fazer_anuncio":["lider", "vice_lider", "gerente"],
    "avisos_farm":  ["lider", "vice_lider", "gerente"],
    "recolhimento": ["lider", "vice_lider", "gerente"],
    "ver_ranking":  ["lider", "vice_lider", "gerente", "membro"],
    "acao":         ["lider", "vice_lider", "gerente", "membro"],
    "ausencia":     ["lider", "vice_lider", "gerente", "membro"],
    "encomenda":    ["lider", "vice_lider", "gerente", "membro"],
}

# ═════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO VISUAL: PAINEL DE OPERAÇÕES
# ═════════════════════════════════════════════════════════════════

PAINEL_OPERACOES_CONFIG = {
    "titulo": "⚙️ PAINEL DE OPERAÇÕES — Morro do Mineiro",
    "descricao": "Selecione uma opção abaixo para executar uma função.",
    "cor": 0x1F1F1F,  # Cinza escuro
}

# Botões visíveis para MEMBRO
BOTOES_MEMBRO = []

# Botões visíveis para GERENTE, VICE LÍDER, LÍDER
BOTOES_LIDERANCA = [
    {"label": "Aprovar Farm",   "emoji": "✅", "custom_id": "painel:aprovar_farm",  "style": "success",   "row": 0},
    {"label": "Definir Metas",  "emoji": "🎯", "custom_id": "painel:definir_metas", "style": "secondary", "row": 0},
    {"label": "Enviar Avisos",  "emoji": "⚠️", "custom_id": "painel:avisos_farm",   "style": "danger",    "row": 1},
    {"label": "Fazer Anúncio",  "emoji": "📢", "custom_id": "painel:fazer_anuncio", "style": "secondary", "row": 1},
    {"label": "Recolhimento",   "emoji": "📥", "custom_id": "painel:recolhimento",  "style": "primary",   "row": 2},
    {"label": "Ranking Geral",  "emoji": "🏆", "custom_id": "painel:ranking",       "style": "primary",   "row": 2},
]

# Grid: 2 botões por linha
GRID_LAYOUT = 2

# ═════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO VISUAL: PAINEL DE SET
# ═════════════════════════════════════════════════════════════════

PAINEL_SET_CONFIG = {
    "titulo": "🎮 PAINEL DE SET — Bem-vindo à Familia",
    "descricao": """
**Como fazer seu SET:**

1️⃣ Clique no botão "📝 Pedir Set"
2️⃣ Preencha seu ID de jogo (numérico)
3️⃣ Preencha o apelido desejado (máximo 32 caracteres)
4️⃣ Aguarde aprovação dos gerentes

⏱️ **Tempo médio:** 30 minutos a 1 hora
⚠️ **Importante:** Não saia do servidor durante o processo!

═══════════════════════════════════════════════════════════════════
""",
    "cor": 0xFFD700,  # Dourado (Morro theme)
}

# Botão único do painel de set
BOTOES_SET = [
    {"label": "📝 Pedir Set", "custom_id": "painel_set:pedir", "style": "primary"},
]
