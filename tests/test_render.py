# -*- coding: utf-8 -*-
"""
tests/test_render.py — teste automatizado da REGRA DE OVERFLOW do
renderizador (src/render.py), CRITERIO DE ACEITE #4 da especificacao:

    "Overflow de texto reduz fonte sem estourar a arte (teste com titulo
    de 120 chars)."

Rodar com:
    python3 -m unittest tests.test_render -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src import render


class TestOverflowRegraDeFonte(unittest.TestCase):

    def setUp(self):
        self.img = Image.new("RGB", (render.W, render.H), (255, 255, 255))
        self.draw = ImageDraw.Draw(self.img)

    def test_titulo_120_chars_reduz_fonte_sem_estourar(self):
        """Titulo de ~120 caracteres nao cabe no tamanho inicial (84px) —
        a funcao de fit deve reduzir a fonte (em passos de 4px, minimo
        32px) ate caber na caixa disponivel."""
        titulo_120 = (
            "Este é um título propositalmente muito longo, com mais de cento e vinte "
            "caracteres, para forçar o estouro da caixa de texto do slide de capa."
        )
        self.assertGreaterEqual(len(titulo_120), 120)

        maxw = render.W - 160
        max_height = 350  # caixa deliberadamente pequena para forcar reducao

        f_final, texto_final, lines = render.fit_font_and_wrap(
            self.draw, titulo_120, True, 84, maxw, max_height, 1.18, label="teste.titulo120"
        )

        # A fonte deve ter sido reduzida abaixo do tamanho inicial (84px).
        self.assertLess(f_final.size, 84, "A fonte deveria ter sido reduzida para caber na caixa.")
        # Nunca abaixo do minimo definido pela especificacao (32px).
        self.assertGreaterEqual(f_final.size, render.MIN_FONT_SIZE)
        # O bloco final (com a fonte escolhida) deve caber na altura maxima.
        altura_final = render._block_height(self.draw, texto_final, f_final, maxw, 1.18)
        self.assertLessEqual(
            altura_final, max_height,
            f"Bloco de texto (altura {altura_final}) nao deveria estourar a caixa ({max_height}).",
        )

    def test_texto_extremo_e_truncado_com_reticencias_na_fonte_minima(self):
        """Se mesmo no tamanho minimo o texto nao couber, deve ser
        truncado com reticencias (nunca estourar a arte)."""
        texto_gigante = "Palavra " * 300  # texto absurdamente longo
        maxw = render.W - 160
        max_height = 150  # caixa minuscula, impossivel caber mesmo no minimo

        f_final, texto_final, _ = render.fit_font_and_wrap(
            self.draw, texto_gigante, False, 42, maxw, max_height, 1.34, label="teste.overflow_extremo"
        )

        self.assertEqual(f_final.size, render.MIN_FONT_SIZE)
        self.assertTrue(texto_final.endswith("…"), "Texto que nao cabe nem no minimo deve ser truncado com reticencias.")

    def test_render_carrossel_com_titulo_120_chars_nao_lanca_excecao(self):
        """Teste de integracao: renderizar um slide de capa real com
        titulo de 120+ chars deve produzir um PNG valido, sem excecao,
        graças a regra de overflow."""
        import tempfile

        titulo_120 = (
            "Este é um título propositalmente muito longo, com mais de cento e vinte "
            "caracteres, para forçar o estouro da caixa de texto do slide de capa real."
        )
        peca = {
            "id": "ig-teste-overflow",
            "canal": "instagram",
            "formato": "carrossel",
            "linha": "Teste",
            "slides": [
                {"tipo": "capa", "kicker": "TESTE", "titulo": titulo_120, "subtitulo": None},
                {"tipo": "conteudo", "numero": "1", "titulo": "Slide 2", "corpo": "corpo curto"},
                {"tipo": "cta", "titulo": "Encerramento", "corpo": "cta curto"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = render.render(peca, Path(tmp), semana="teste")
            self.assertEqual(len(paths), 3)
            for p in paths:
                self.assertTrue(p.exists())
                with Image.open(p) as img:
                    self.assertEqual(img.size, (render.W, render.H))


if __name__ == "__main__":
    unittest.main()
