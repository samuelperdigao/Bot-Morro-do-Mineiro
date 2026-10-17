"""Repositório compatível para Ações."""

from services import db_service


class AcaoRepository:
    create = staticmethod(db_service.db_acao_criar)
    get = staticmethod(db_service.db_acao_get)
    get_by_message = staticmethod(db_service.db_acao_get_by_message)
    participants = staticmethod(db_service.db_acao_participantes)
    add_participant = staticmethod(db_service.db_acao_participante_add)
    remove_participant = staticmethod(db_service.db_acao_participante_remove)
    finalize = staticmethod(db_service.db_acao_finalizar)


acao_repository = AcaoRepository()

__all__ = ["AcaoRepository", "acao_repository"]
