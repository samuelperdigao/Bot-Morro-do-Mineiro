"""Serviço de armazenamento do Baú sem migração automática de dados."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from infrastructure.repositories.bau import BauRepository


@dataclass(frozen=True)
class BauStoragePaths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "bau.db"

    @property
    def panel_reference(self) -> Path:
        return self.root / "bau_painel.json"

    @property
    def managers_panel_reference(self) -> Path:
        return self.root / "bau_gerentes_painel.json"


class BauService:
    def __init__(self, root: Path | None = None) -> None:
        self.paths = BauStoragePaths(root or Path(__file__).resolve().parent.parent)
        self.repository = BauRepository(self.paths.database)

    @staticmethod
    def load_panel_reference(path: Path) -> tuple[int | None, int | None]:
        if not path.exists():
            return None, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return int(data["channel_id"]), int(data["message_id"])
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None, None

    @staticmethod
    def save_panel_reference(path: Path, channel_id: int, message_id: int) -> None:
        path.write_text(
            json.dumps({"channel_id": channel_id, "message_id": message_id}),
            encoding="utf-8",
        )


bau_service = BauService()

__all__ = ["BauService", "BauStoragePaths", "bau_service"]
