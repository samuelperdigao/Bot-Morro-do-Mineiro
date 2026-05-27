"""
core/command_config.py
Helper para carregar e cachear configurações de comandos de data/commands_config.json.
Os cogs importam is_enabled() e get_cog_config() para respeitar configs do painel web.
"""

import json
from pathlib import Path

CFG_PATH = Path(__file__).resolve().parent.parent / "data" / "commands_config.json"

_cache: dict = {}
_cache_mtime: float = 0.0


def get_cog_config(cog_name: str) -> dict:
    """Retorna a config do cog, relendo o arquivo se modificado em disco."""
    global _cache, _cache_mtime
    try:
        mtime = CFG_PATH.stat().st_mtime
        if mtime != _cache_mtime:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            _cache_mtime = mtime
    except FileNotFoundError:
        _cache = {}
    except Exception:
        pass
    return _cache.get(cog_name, {"enabled": True})


def is_enabled(cog_name: str) -> bool:
    """Retorna True se o cog/comando está habilitado nas configurações."""
    return bool(get_cog_config(cog_name).get("enabled", True))
