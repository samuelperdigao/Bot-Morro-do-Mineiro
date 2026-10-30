"""Repositório compatível para solicitações de Set."""

from services import db_service


class SetRequestRepository:
    create = staticmethod(db_service.db_set_request_create)
    attach_message = staticmethod(db_service.db_set_request_attach_message)
    get = staticmethod(db_service.db_set_request_get)
    get_by_message = staticmethod(db_service.db_set_request_get_by_message)
    pending_for_user = staticmethod(db_service.db_set_request_pending_for_user)
    recoverable = staticmethod(db_service.db_set_request_list_recoverable)
    recover_interrupted = staticmethod(db_service.db_set_request_recover_interrupted)
    claim = staticmethod(db_service.db_set_request_claim)
    complete = staticmethod(db_service.db_set_request_complete)
    release = staticmethod(db_service.db_set_request_release)
    discard_unposted = staticmethod(db_service.db_set_request_discard_unposted)


set_request_repository = SetRequestRepository()

__all__ = ["SetRequestRepository", "set_request_repository"]
