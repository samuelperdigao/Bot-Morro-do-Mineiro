"""
core/logger.py - Função centralizada de criação de loggers rotativos.
"""

import logging
import logging.handlers
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Handler de console (usado pelo main.py)
console_handler = logging.StreamHandler()
console_handler.setFormatter(_fmt)


def get_logger(name: str, filename: str | None = None) -> logging.Logger:
    """
    Retorna um logger com handler rotativo em logs/<filename>.
    Se filename for None, usa logs/<name>.log.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    fname = filename or f"{name}.log"
    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / fname,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(_fmt)
    logger.addHandler(fh)
    return logger
