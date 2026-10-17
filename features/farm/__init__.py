"""Domínio de Farm."""

from features.farm.catalog import MATERIAIS_POR_COLETE
from services.farm_service import FarmService, farm_service

__all__ = ["FarmService", "MATERIAIS_POR_COLETE", "farm_service"]
