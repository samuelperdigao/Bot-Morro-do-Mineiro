"""
core/config.py - Centraliza as variáveis de ambiente do projeto.

Após a migração multi-server, apenas TOKEN e APPLICATION_ID ficam aqui.
Toda configuração por servidor é armazenada na tabela guild_config do banco.
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
# Segredo operacional opcional. Quando existe, substitui somente DISCORD_TOKEN
# e permite rotacionar o token sem copiar ou reescrever o .env.
TOKEN_OVERRIDE_FILE = BASE_DIR / ".env.token"
if TOKEN_OVERRIDE_FILE.exists():
    token_override = (dotenv_values(TOKEN_OVERRIDE_FILE).get("DISCORD_TOKEN") or "").strip()
    if not token_override:
        raise RuntimeError("Arquivo .env.token existe sem DISCORD_TOKEN válido")
    os.environ["DISCORD_TOKEN"] = token_override


def _env(key: str, required: bool = True) -> str:
    val = os.getenv(key, "").strip()
    if required and not val:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {key}")
    return val


def _env_int(key: str) -> int:
    return int(_env(key))


def _env_int_optional(key: str, default: int | None = None) -> int | None:
    val = os.getenv(key, "").strip()
    return int(val) if val else default


# ── Bot ───────────────────────────────────────────────────────────────────────
TOKEN          = _env("DISCORD_TOKEN")
APPLICATION_ID = _env_int("APPLICATION_ID")

# Canais globais legados. Quando possivel, prefira configuracao por servidor.
CANAL_LOG_ENTRADA_ID = _env_int_optional("CANAL_LOG_ENTRADA_ID", 1474869321187459143)
CANAL_LOG_PD_ID      = _env_int_optional("CANAL_LOG_PD_ID", 1496346120111259743)

# ── Arquivos de dados ─────────────────────────────────────────────────────────
DATA_DIR     = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH      = DATA_DIR / (_env("ARQUIVO_BANCO_FARM", required=False) or "farm.db")
TZ_STR       = _env("FUSO_HORARIO_FARM", required=False) or "America/Sao_Paulo"

# Mantidos apenas para a função de migração de dados legados
CHANNEL_MAP_FILE = DATA_DIR / "channel_map.json"
AUSENCIAS_FILE   = DATA_DIR / "ausencias.json"
