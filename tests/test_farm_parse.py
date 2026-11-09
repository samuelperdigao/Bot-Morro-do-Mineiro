import unittest

from cogs.farm import _fmt_input_valor, _parse_money


class ParseMoneyTests(unittest.TestCase):
    def test_formatos_brasileiros(self):
        self.assertEqual(_parse_money("50000"), 50000)
        self.assertEqual(_parse_money("50.000"), 50000)
        self.assertEqual(_parse_money("R$ 50.000"), 50000)
        self.assertEqual(_parse_money("1.500.000"), 1500000)
        self.assertEqual(_parse_money("50.000,50"), 50000.5)
        self.assertEqual(_parse_money("1500,5"), 1500.5)
        self.assertEqual(_parse_money(""), 0)
        self.assertEqual(_parse_money("   "), 0)

    def test_ponto_decimal_nao_multiplica_valor(self):
        # Antes "50000.0" virava 500000 ao editar um lancamento.
        self.assertEqual(_parse_money("50000.0"), 50000)
        self.assertEqual(_parse_money("1500.50"), 1500.5)

    def test_rejeita_valores_invalidos(self):
        for raw in ("inf", "nan", "-inf", "1e9", "-10", "abc", "1,2,3", "10,5.000"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    _parse_money(raw)

    def test_rejeita_valor_acima_do_teto(self):
        with self.assertRaises(ValueError):
            _parse_money("99999999999999999")

    def test_valor_pre_preenchido_volta_igual(self):
        for valor in (50000.0, 1500.5, 1200, 0.5):
            with self.subTest(valor=valor):
                self.assertEqual(_parse_money(_fmt_input_valor(valor)), valor)


if __name__ == "__main__":
    unittest.main()
