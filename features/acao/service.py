"""API pública do domínio de Ação durante a migração gradual."""

from services.acao_service import AcaoService, ParticipantMutation, acao_service

__all__ = ["AcaoService", "ParticipantMutation", "acao_service"]
