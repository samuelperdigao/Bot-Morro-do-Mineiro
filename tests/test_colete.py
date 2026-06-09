import unittest

from cogs.colete import calcular_fabricacao


class ColeteCalculationTests(unittest.TestCase):
    def test_calcula_um_colete(self):
        self.assertEqual(
            calcular_fabricacao(1),
            {
                "ferro": 20,
                "plastico": 10,
                "tecido": 1,
                "aluminio": 20,
                "borracha": 10,
                "custo": 1000,
            },
        )

    def test_calcula_limite_de_dez_coletes(self):
        self.assertEqual(
            calcular_fabricacao(10),
            {
                "ferro": 200,
                "plastico": 100,
                "tecido": 10,
                "aluminio": 200,
                "borracha": 100,
                "custo": 10000,
            },
        )

    def test_rejeita_quantidade_fora_do_limite(self):
        for quantidade in (0, 11):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(ValueError):
                    calcular_fabricacao(quantidade)


if __name__ == "__main__":
    unittest.main()
