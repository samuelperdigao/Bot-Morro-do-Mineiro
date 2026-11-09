import re
import unittest
from pathlib import Path

from core.money import fmt_input_valor, parse_money_br

ROOT = Path(__file__).resolve().parent.parent


class ParseMoneyBrTests(unittest.TestCase):
    def test_formatos_brasileiros(self):
        self.assertEqual(parse_money_br("50000"), 50000)
        self.assertEqual(parse_money_br("50.000"), 50000)
        self.assertEqual(parse_money_br("R$ 50.000"), 50000)
        self.assertEqual(parse_money_br("1.500.000"), 1500000)
        self.assertEqual(parse_money_br("50.000,50"), 50000.5)
        self.assertEqual(parse_money_br("1500,5"), 1500.5)
        self.assertEqual(parse_money_br(""), 0)
        self.assertEqual(parse_money_br("   "), 0)
        self.assertEqual(parse_money_br(None), 0)

    def test_ponto_decimal_nao_multiplica_valor(self):
        # Antes "50000.0" virava 500000 ao editar um lancamento.
        self.assertEqual(parse_money_br("50000.0"), 50000)
        self.assertEqual(parse_money_br("1500.50"), 1500.5)

    def test_rejeita_valores_invalidos(self):
        for raw in ("inf", "nan", "-inf", "1e9", "-10", "abc", "1,2,3", "10,5.000", "1,234", "."):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_money_br(raw)

    def test_rejeita_valor_acima_do_teto(self):
        with self.assertRaises(ValueError):
            parse_money_br("99999999999999999")

    def test_valor_pre_preenchido_volta_igual(self):
        for valor in (50000.0, 1500.5, 1200, 0.5):
            with self.subTest(valor=valor):
                self.assertEqual(parse_money_br(fmt_input_valor(valor)), valor)

    def test_farm_usa_o_parser_central(self):
        from cogs.farm import _parse_money

        self.assertEqual(_parse_money("50000.0"), 50000)
        with self.assertRaises(ValueError):
            _parse_money("inf")


class LembretesFarmTests(unittest.TestCase):
    def test_lembretes_nao_usam_get_em_sqlite_row(self):
        # sqlite3.Row nao tem .get(): a chamada derrubava as tasks de aviso.
        fonte = (ROOT / "cogs" / "farm.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\brow\.get\(", fonte))


if __name__ == "__main__":
    unittest.main()
