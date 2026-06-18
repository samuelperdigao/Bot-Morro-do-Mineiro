from config.paineis import BOTOES_LIDERANCA, PERMISSOES_PAINEL_OPERACOES


def test_painel_operacoes_nao_exibe_envio_de_avisos():
    custom_ids = {botao["custom_id"] for botao in BOTOES_LIDERANCA}

    assert "painel:avisos_farm" not in custom_ids
    assert "avisos_farm" not in PERMISSOES_PAINEL_OPERACOES


def test_painel_operacoes_usa_grade_de_duas_linhas():
    linhas = [botao["row"] for botao in BOTOES_LIDERANCA]

    assert linhas == [0, 0, 1, 1]
