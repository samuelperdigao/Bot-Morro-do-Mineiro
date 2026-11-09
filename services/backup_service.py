"""
services/backup_service.py - Backup dos bancos SQLite do bot.

Usa a API de backup do SQLite (sqlite3.Connection.backup), que gera uma
cópia consistente mesmo com o bot gravando (modo WAL). Cada cópia é
compactada em .gz e as mais antigas que a retenção são apagadas.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.config import BASE_DIR, DB_PATH

BACKUP_DIR = BASE_DIR / "backups"
RETENCAO_PADRAO = 14  # cópias mantidas por banco

BANCOS: dict[str, Path] = {
    "farm": DB_PATH,
    "bau": BASE_DIR / "bau.db",
}


@dataclass
class BackupResultado:
    nome: str
    caminho: Path
    tamanho_bytes: int


def backup_banco(
    nome: str,
    origem: Path,
    destino_dir: Path = BACKUP_DIR,
    retencao: int = RETENCAO_PADRAO,
    agora: datetime | None = None,
) -> BackupResultado | None:
    """Gera <destino_dir>/<nome>-AAAAMMDD-HHMMSS.db.gz. Retorna None se o banco não existir."""
    origem = Path(origem)
    if not origem.exists():
        return None

    destino_dir.mkdir(parents=True, exist_ok=True)
    carimbo = (agora or datetime.now()).strftime("%Y%m%d-%H%M%S")
    temporario = destino_dir / f"{nome}-{carimbo}.db"
    final = destino_dir / f"{nome}-{carimbo}.db.gz"

    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(temporario)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    # Confere se a cópia abre e está íntegra antes de compactar.
    check = sqlite3.connect(temporario)
    try:
        resultado = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if resultado != "ok":
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"Backup de {nome} falhou no integrity_check: {resultado}")

    with temporario.open("rb") as f_in, gzip.open(final, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    temporario.unlink(missing_ok=True)

    _aplicar_retencao(nome, destino_dir, retencao)
    return BackupResultado(nome=nome, caminho=final, tamanho_bytes=final.stat().st_size)


def _aplicar_retencao(nome: str, destino_dir: Path, retencao: int) -> None:
    copias = sorted(destino_dir.glob(f"{nome}-*.db.gz"))
    for antiga in copias[:-retencao] if retencao > 0 else []:
        antiga.unlink(missing_ok=True)


def backup_todos(destino_dir: Path = BACKUP_DIR, retencao: int = RETENCAO_PADRAO) -> list[BackupResultado]:
    """Faz backup de todos os bancos conhecidos. Bancos inexistentes são ignorados."""
    agora = datetime.now()
    resultados = []
    for nome, caminho in BANCOS.items():
        resultado = backup_banco(nome, caminho, destino_dir, retencao, agora)
        if resultado is not None:
            resultados.append(resultado)
    return resultados


if __name__ == "__main__":
    # Uso manual ou pelo deploy:  python -m services.backup_service
    for item in backup_todos():
        print(f"{item.nome}: {item.caminho} ({item.tamanho_bytes} bytes)")
