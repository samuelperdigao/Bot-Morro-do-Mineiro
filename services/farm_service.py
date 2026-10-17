"""API pública do domínio Farm.

Este serviço mantém a implementação SQLite atual atrás de nomes de domínio.
Os aliases de compatibilidade no cog podem ser removidos depois que os demais
adaptadores migrarem para esta API.
"""

from services import db_service


class FarmService:
    DINHEIRO_ITEMS = db_service.DINHEIRO_ITEMS
    DINHEIRO_LIMPO_ITEM = db_service.DINHEIRO_LIMPO_ITEM
    DINHEIRO_SUJO_ITEM = db_service.DINHEIRO_SUJO_ITEM

    initialize = staticmethod(db_service.init_db)
    current_week_id = staticmethod(db_service.current_week_id)
    now = staticmethod(db_service.now_tz)
    valid_window = staticmethod(db_service.janela_valida)
    format_datetime = staticmethod(db_service.fmt_dt)
    classify_result = staticmethod(db_service.classificar_resultado)

    meta_dinheiro_ativo = staticmethod(db_service.db_meta_dinheiro_ativo)
    meta_dinheiro_itens_ativos = staticmethod(db_service.db_meta_dinheiro_itens_ativos)
    meta_itens_ativos = staticmethod(db_service.db_meta_itens_ativos)
    meta_tipo_efetivo = staticmethod(db_service.db_meta_tipo_efetivo)
    progresso_itens = staticmethod(db_service.db_prog_itens)
    evento_itens = staticmethod(db_service.db_evento_itens)
    ultimo_evento = staticmethod(db_service.db_get_ultimo_evento)
    get_meta = staticmethod(db_service.db_get_meta)
    set_meta = staticmethod(db_service.db_set_meta)
    set_meta_dinheiro = staticmethod(db_service.db_set_meta_dinheiro)
    get_progresso = staticmethod(db_service.db_get_progresso)
    ensure_progresso = staticmethod(db_service.db_ensure_progresso)
    lancar = staticmethod(db_service.db_lancar)
    editar_evento = staticmethod(db_service.db_editar_evento)
    editar_ultimo_evento = staticmethod(db_service.db_editar_ultimo_evento)
    verificar_conclusao = staticmethod(db_service.db_verificar_conclusao)
    salvar_painel = staticmethod(db_service.db_salvar_painel)
    limpar_painel = staticmethod(db_service.db_limpar_painel)
    aprovar = staticmethod(db_service.db_aprovar)
    lista_progresso = staticmethod(db_service.db_lista_progresso)
    eventos_usuario = staticmethod(db_service.db_eventos_usuario)
    ranking_semana = staticmethod(db_service.db_ranking_semana)
    get_guild_config = staticmethod(db_service.db_get_guild_config)
    is_configured = staticmethod(db_service.db_is_farm_configured)
    get_lideranca_role_ids = staticmethod(db_service.db_get_lideranca_role_ids)
    get_permitidos_role_ids = staticmethod(db_service.db_get_permitidos_role_ids)
    all_configured_guilds = staticmethod(db_service.db_all_configured_guilds)


farm_service = FarmService()

__all__ = ["FarmService", "farm_service"]
