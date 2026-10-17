"""Ponto de entrada estável para o ciclo de vida do banco local.

O serviço existente continua sendo a implementação compatível durante a
migração. Novos módulos devem depender desta fachada, não do módulo monolítico
diretamente.
"""

from services.db_service import get_conn, init_db


def initialize_database():
    """Inicializa o esquema local e aplica migrações idempotentes."""

    return init_db()


__all__ = ["get_conn", "initialize_database"]
