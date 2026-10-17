"""API de compatibilidade do repositório do Baú.

O código de persistência existente em ``cogs.bau_core`` continua sendo a
implementação até que os testes e consumidores permitam sua movimentação
física. Este módulo evita novos imports entre cogs.
"""

from cogs.bau_core import (
    BauRepository,
    CATEGORIAS,
    DuplicateOperationError,
    MovementLine,
    OperationResult,
    StaleOperationError,
    TOTAL_PRODUTOS,
    UndoOperation,
    UndoResult,
    agora_str,
)

__all__ = [
    "BauRepository",
    "CATEGORIAS",
    "DuplicateOperationError",
    "MovementLine",
    "OperationResult",
    "StaleOperationError",
    "TOTAL_PRODUTOS",
    "UndoOperation",
    "UndoResult",
    "agora_str",
]
