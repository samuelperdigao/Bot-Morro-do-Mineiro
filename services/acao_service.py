"""Serviço de domínio para criação e participação em Ações."""

from __future__ import annotations

from dataclasses import dataclass

from services.db_service import (
    db_acao_criar,
    db_acao_finalizar,
    db_acao_get,
    db_acao_get_by_message,
    db_acao_participante_add,
    db_acao_participante_remove,
    db_acao_participantes,
)


@dataclass(frozen=True)
class ParticipantMutation:
    added: bool
    reason: str = ""


class AcaoService:
    def create(
        self,
        guild_id: str,
        acao_key: str,
        tipo: str,
        data: str,
        horario: str,
        criado_por: str,
        channel_id: str,
        message_id: str,
    ) -> int:
        return db_acao_criar(
            guild_id,
            acao_key,
            tipo,
            data,
            horario,
            criado_por,
            channel_id,
            message_id,
        )

    def get(self, acao_id: int):
        return db_acao_get(acao_id)

    def get_by_message(self, guild_id: str, message_id: str):
        return db_acao_get_by_message(guild_id, message_id)

    def participants(self, acao_id: int):
        return db_acao_participantes(acao_id)

    def add_participant(
        self,
        acao_id: int,
        user_id: str,
        user_name: str,
        origem: str,
        added_by: str | None,
        max_participants: int | None = None,
    ) -> ParticipantMutation:
        action = db_acao_get(acao_id)
        if not action or action["status"] != "aberta":
            return ParticipantMutation(False, "closed")

        participants = db_acao_participantes(acao_id)
        if any(row["user_id"] == user_id for row in participants):
            return ParticipantMutation(False, "duplicate")
        if max_participants and len(participants) >= max_participants:
            return ParticipantMutation(False, "full")

        if not db_acao_participante_add(
            acao_id, user_id, user_name, origem, added_by
        ):
            return ParticipantMutation(False, "duplicate")
        return ParticipantMutation(True)

    def remove_participant(self, acao_id: int, user_id: str) -> bool:
        action = db_acao_get(acao_id)
        if not action or action["status"] != "aberta":
            return False
        return db_acao_participante_remove(acao_id, user_id)

    def finalize(
        self,
        acao_id: int,
        resultado: str,
        finalizado_por: str,
        observacao: str | None = None,
        valor_total_centavos: int | None = None,
        valor_faccao_centavos: int | None = None,
        valor_participantes_centavos: int | None = None,
        valor_por_participante_centavos: int | None = None,
    ) -> bool:
        return db_acao_finalizar(
            acao_id,
            resultado,
            finalizado_por,
            observacao,
            valor_total_centavos,
            valor_faccao_centavos,
            valor_participantes_centavos,
            valor_por_participante_centavos,
        )


acao_service = AcaoService()
