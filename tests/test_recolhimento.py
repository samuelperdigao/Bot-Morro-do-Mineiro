import unittest

from cogs.recolhimento import (
    LIMITE_FIELD,
    ORCAMENTO_ENTREGAS,
    RecolhimentoDinheiroView,
    _dividir_linhas_em_fields,
    _motivo_ciclo_fechado,
    _parse_valor_recolhimento,
    _view_para_ciclo,
    build_embed_dinheiro,
    build_embed_farm,
)


def _ciclo(**extra):
    base = {
        "id": 7,
        "guild_id": "1",
        "channel_id": "2",
        "message_id": "3",
        "tipo": "dinheiro",
        "semana_inicio": "2026-11-09",
        "semana_fim": "2026-11-15",
        "pago": 0,
        "pago_por": None,
        "data_pagamento": None,
        "observacao_pagamento": None,
        "encerrado": 0,
    }
    base.update(extra)
    return base


def _entrega_dinheiro(i: int, valor: float = 1500.5):
    return {
        "data": "2026-11-10T20:00:00-03:00",
        "valor": valor,
        "registrado_por": "123456789012345678",
        "alvo_user_id": str(1000 + i),
        "alvo_nome": f"Membro com nome razoavelmente longo {i}",
        "alvo_pasta_id": "999",
        "folha": None, "opio": None, "seringa": None, "agulha": None,
    }


def _tamanho_embed(embed) -> int:
    total = len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "")
    for field in embed.fields:
        total += len(field.name) + len(field.value)
    return total


class ParseValorTests(unittest.TestCase):
    def test_valores_validos(self):
        self.assertEqual(_parse_valor_recolhimento("1500"), 1500)
        self.assertEqual(_parse_valor_recolhimento("1.500"), 1500)
        self.assertEqual(_parse_valor_recolhimento("R$ 1.500,50"), 1500.5)
        # Antes "1500.50" virava R$ 150.050,00.
        self.assertEqual(_parse_valor_recolhimento("1500.50"), 1500.5)

    def test_valores_invalidos(self):
        for raw in ("", "0", "inf", "nan", "1e9", "-10", "abc", "1_000"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    _parse_valor_recolhimento(raw)


class EmbedTests(unittest.TestCase):
    def test_muitas_entregas_respeitam_limites_do_discord(self):
        for qtd in (1, 7, 30, 200):
            with self.subTest(qtd=qtd):
                entregas = [_entrega_dinheiro(i) for i in range(qtd)]
                embed = build_embed_dinheiro(_ciclo(), entregas)
                self.assertLessEqual(len(embed.fields), 25)
                for field in embed.fields:
                    self.assertLessEqual(len(field.value), LIMITE_FIELD)
                    self.assertLessEqual(len(field.name), 256)
                self.assertLessEqual(_tamanho_embed(embed), 6000)

    def test_total_considera_todas_as_entregas_mesmo_ocultas(self):
        entregas = [_entrega_dinheiro(i, valor=100) for i in range(200)]
        embed = build_embed_dinheiro(_ciclo(), entregas)
        total = next(f for f in embed.fields if "Total" in f.name)
        self.assertIn("20.000,00", total.value)
        nomes = " ".join(f.name for f in embed.fields)
        self.assertIn("oculta", nomes)

    def test_farm_com_muitas_entregas(self):
        entregas = []
        for i in range(60):
            e = _entrega_dinheiro(i)
            e.update({"valor": None, "folha": 10, "opio": 20, "seringa": 30, "agulha": 40})
            entregas.append(e)
        embed = build_embed_farm(_ciclo(tipo="farm"), entregas)
        for field in embed.fields:
            self.assertLessEqual(len(field.value), LIMITE_FIELD)
        self.assertLessEqual(_tamanho_embed(embed), 6000)
        total = next(f for f in embed.fields if "Total" in f.name)
        self.assertIn("600", total.value)

    def test_divisao_preserva_entregas_recentes(self):
        linhas = [f"linha {i:04d} " + "x" * 80 for i in range(500)]
        blocos, omitidas = _dividir_linhas_em_fields(linhas)
        texto = "\n".join(blocos)
        self.assertIn("linha 0499", texto)
        self.assertNotIn("linha 0000", texto)
        self.assertEqual(omitidas + texto.count("\n") + 1, 500)
        self.assertLessEqual(len(texto), ORCAMENTO_ENTREGAS)

    def test_status_pago_e_encerrado(self):
        pago = build_embed_dinheiro(
            _ciclo(pago=1, pago_por="5", data_pagamento="2026-11-15T10:00:00", observacao_pagamento="PIX"), []
        )
        self.assertIn("✅", next(f for f in pago.fields if f.name == "Status").value)
        encerrado = build_embed_dinheiro(_ciclo(encerrado=1), [])
        self.assertIn("Encerrado", next(f for f in encerrado.fields if f.name == "Status").value)


class EstadoCicloTests(unittest.IsolatedAsyncioTestCase):
    async def test_view_segue_estado(self):
        self.assertIsNone(_view_para_ciclo(_ciclo(pago=1)))

        aberto = _view_para_ciclo(_ciclo())
        self.assertIsInstance(aberto, RecolhimentoDinheiroView)
        self.assertFalse(aberto.registrar.disabled)
        self.assertFalse(aberto.pagar.disabled)

        encerrado = _view_para_ciclo(_ciclo(encerrado=1))
        self.assertTrue(encerrado.registrar.disabled)
        self.assertFalse(encerrado.pagar.disabled)
        for view in (aberto, encerrado):
            view.stop()

    def test_registro_recusado_em_ciclo_fechado(self):
        self.assertIsNone(_motivo_ciclo_fechado(_ciclo()))
        self.assertIsNotNone(_motivo_ciclo_fechado(_ciclo(pago=1)))
        self.assertIsNotNone(_motivo_ciclo_fechado(_ciclo(encerrado=1)))
        self.assertIsNotNone(_motivo_ciclo_fechado(None))


if __name__ == "__main__":
    unittest.main()
