"""Isola a suíte do ambiente local: sem `.env` real e sem o `bau.db` do projeto."""

import os

import pytest

os.environ.setdefault("DISCORD_TOKEN", "token-de-teste")
os.environ.setdefault("APPLICATION_ID", "1")


@pytest.fixture(scope="session", autouse=True)
def _banco_do_bau_temporario(tmp_path_factory):
    from services.bau_service import bau_service

    bau_service.repository.db_path = tmp_path_factory.mktemp("bau") / "bau.db"
    bau_service.repository.initialize()
