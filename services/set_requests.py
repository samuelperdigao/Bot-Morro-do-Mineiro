"""Serviço de domínio para solicitações de Set.

Views e comandos diferentes usam esta mesma transição de estado; o serviço não
conhece Discord e não altera mensagens.
"""

from __future__ import annotations

from infrastructure.repositories.set_requests import set_request_repository


class SetRequestService:
    def create(
        self,
        guild_id: str,
        requester_user_id: str,
        target_name: str,
        id_jogo: str,
        approval_channel_id: str,
    ) -> str:
        return set_request_repository.create(
            guild_id,
            requester_user_id,
            target_name,
            id_jogo,
            approval_channel_id,
        )

    def attach_message(self, request_id: str, message_id: str) -> None:
        set_request_repository.attach_message(request_id, message_id)

    def get(self, request_id: str):
        return set_request_repository.get(request_id)

    def pending_for_user(self, guild_id: str, user_id: str):
        return set_request_repository.pending_for_user(guild_id, user_id)

    def claim(self, request_id: str, decided_by: str, decision: str) -> bool:
        return set_request_repository.claim(request_id, decided_by, decision)

    def complete(self, request_id: str, status: str) -> bool:
        return set_request_repository.complete(request_id, status)

    def release(self, request_id: str) -> bool:
        return set_request_repository.release(request_id)

    def recover_interrupted(self) -> int:
        return set_request_repository.recover_interrupted()

    def recoverable(self):
        return set_request_repository.recoverable()


set_request_service = SetRequestService()
