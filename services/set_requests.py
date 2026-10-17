"""Serviço de domínio para solicitações de Set.

Views e comandos diferentes usam esta mesma transição de estado; o serviço não
conhece Discord e não altera mensagens.
"""

from __future__ import annotations

from services.db_service import (
    db_set_request_attach_message,
    db_set_request_claim,
    db_set_request_complete,
    db_set_request_create,
    db_set_request_get,
    db_set_request_list_recoverable,
    db_set_request_pending_for_user,
    db_set_request_recover_interrupted,
    db_set_request_release,
)


class SetRequestService:
    def create(
        self,
        guild_id: str,
        requester_user_id: str,
        target_name: str,
        id_jogo: str,
        approval_channel_id: str,
    ) -> str:
        return db_set_request_create(
            guild_id,
            requester_user_id,
            target_name,
            id_jogo,
            approval_channel_id,
        )

    def attach_message(self, request_id: str, message_id: str) -> None:
        db_set_request_attach_message(request_id, message_id)

    def get(self, request_id: str):
        return db_set_request_get(request_id)

    def pending_for_user(self, guild_id: str, user_id: str):
        return db_set_request_pending_for_user(guild_id, user_id)

    def claim(self, request_id: str, decided_by: str, decision: str) -> bool:
        return db_set_request_claim(request_id, decided_by, decision)

    def complete(self, request_id: str, status: str) -> bool:
        return db_set_request_complete(request_id, status)

    def release(self, request_id: str) -> bool:
        return db_set_request_release(request_id)

    def recover_interrupted(self) -> int:
        return db_set_request_recover_interrupted()

    def recoverable(self):
        return db_set_request_list_recoverable()


set_request_service = SetRequestService()
