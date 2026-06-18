import unittest

from cogs.colete import ColetePanelView, calcular_fabricacao


class ColeteCalculationTests(unittest.IsolatedAsyncioTestCase):
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

    def test_calcula_limite_de_cem_coletes(self):
        self.assertEqual(
            calcular_fabricacao(100),
            {
                "ferro": 2000,
                "plastico": 1000,
                "tecido": 100,
                "aluminio": 2000,
                "borracha": 1000,
                "custo": 100000,
            },
        )

    def test_rejeita_quantidade_fora_do_limite(self):
        for quantidade in (0, 101):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(ValueError):
                    calcular_fabricacao(quantidade)

    async def test_painel_distribui_quantidades_em_quatro_seletores(self):
        seletores = ColetePanelView().children

        self.assertEqual(len(seletores), 4)
        self.assertEqual(
            [[int(opcao.value) for opcao in seletor.options] for seletor in seletores],
            [
                list(range(1, 26)),
                list(range(26, 51)),
                list(range(51, 76)),
                list(range(76, 101)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
