# -*- coding: utf-8 -*-
"""
tests/test_validator.py — testes automatizados do validador de guarda
(src/validator.py), incluindo o CRITERIO DE ACEITE #3 da especificacao:

    "Validador reprova peca-isca contendo 'Casa Ativa' e 'R$ 300 mil'."

Rodar com:
    python3 -m unittest tests/test_validator.py -v
ou
    python3 tests/test_validator.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src import validator


class TestValidatorGuardaBasica(unittest.TestCase):

    def test_criterio_aceite_3_peca_isca_casa_ativa_r300mil(self):
        """CRITERIO DE ACEITE #3: uma peca-isca contendo 'Casa Ativa' e
        'R$ 300 mil' deve ser reprovada pelo validador."""
        peca_isca = {
            "id": "li-isca",
            "canal": "linkedin",
            "formato": "texto",
            "linha": "Framework Próprio",
            "publicar_em": "2026-07-14T08:00:00",
            "texto": (
                "A Casa Ativa economizou R$ 300 mil em seis meses aplicando o "
                "nosso framework de gestão de estoque. " * 8
            ),
            "racional": "teste",
        }
        ok, motivos = validator.validate_peca(peca_isca)
        self.assertFalse(ok, "Peca-isca com 'Casa Ativa' e 'R$ 300 mil' deveria ser REPROVADA.")
        motivos_str = " | ".join(motivos)
        self.assertTrue(
            any("Casa Ativa" in m for m in motivos),
            f"Esperava motivo de reprovacao citando 'Casa Ativa'. Motivos: {motivos_str}",
        )
        self.assertTrue(
            any("monetario" in m.lower() for m in motivos),
            f"Esperava motivo de reprovacao sobre padrao monetario. Motivos: {motivos_str}",
        )

    def test_peca_limpa_e_aprovada(self):
        """Peca sem clientes reais, sem valores monetarios especificos e
        dentro dos limites de caracteres deve ser aprovada."""
        texto_valido = (
            "Você é dono da empresa ou é o funcionário mais caro dela? "
            "Essa pergunta incomoda, mas vale a pena responder com a agenda na mão.\n\n"
        ) * 10
        texto_valido = texto_valido[:1300]
        peca = {
            "id": "li-ok",
            "canal": "linkedin",
            "formato": "texto",
            "linha": "Framework Próprio",
            "publicar_em": "2026-07-14T08:00:00",
            "texto": texto_valido,
            "racional": "teste",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertTrue(ok, f"Peca limpa deveria ser aprovada. Motivos de reprovacao: {motivos}")

    def test_mencao_concorrente_reprovada(self):
        peca = {
            "id": "li-concorrente",
            "canal": "linkedin",
            "formato": "texto",
            "linha": "Tese Regional",
            "publicar_em": "2026-07-14T08:00:00",
            "texto": ("Diferente do G4, eu ensino gestão pé no chão de fábrica. " * 20)[:1300],
            "racional": "teste",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertFalse(ok)
        self.assertTrue(any("G4" in m for m in motivos))

    def test_valor_monetario_com_fonte_publica_e_permitido(self):
        texto = (
            "Segundo o IBGE (fonte pública), o PIB do Vale do Taquari é de "
            "R$ 300 milhões em determinado setor. " * 15
        )[:1300]
        peca = {
            "id": "li-fonte",
            "canal": "linkedin",
            "formato": "texto",
            "linha": "Tese Regional",
            "publicar_em": "2026-07-14T08:00:00",
            "texto": texto,
            "racional": "teste",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertTrue(ok, f"Valor com citacao de fonte publica nao deveria reprovar. Motivos: {motivos}")

    def test_linkedin_fora_do_limite_de_caracteres_reprovado(self):
        peca = {
            "id": "li-curto",
            "canal": "linkedin",
            "formato": "texto",
            "linha": "Framework Próprio",
            "publicar_em": "2026-07-14T08:00:00",
            "texto": "Texto curto demais.",
            "racional": "teste",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertFalse(ok)
        self.assertTrue(any("limite" in m.lower() for m in motivos))

    def test_carrossel_titulo_acima_do_limite_reprovado(self):
        titulo_longo = "T" * 65
        peca = {
            "id": "ig-c-limite",
            "canal": "instagram",
            "formato": "carrossel",
            "linha": "Mentoria com o Especialista",
            "publicar_em": "2026-07-13T11:30:00",
            "slides": [
                {"tipo": "capa", "kicker": "MENTORIA", "titulo": titulo_longo, "subtitulo": None},
                {"tipo": "conteudo", "numero": "1", "titulo": "ok", "corpo": "corpo ok"},
                {"tipo": "cta", "titulo": "cta", "corpo": "cta corpo"},
            ],
            "legenda": "legenda de teste",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertFalse(ok)
        self.assertTrue(any("titulo" in m.lower() for m in motivos))

    def test_card_frase_acima_do_limite_reprovado(self):
        peca = {
            "id": "ig-card-limite",
            "canal": "instagram",
            "formato": "card",
            "linha": "Tese Regional",
            "publicar_em": "2026-07-14T07:30:00",
            "frase": "F" * 95,
            "legenda": "legenda",
        }
        ok, motivos = validator.validate_peca(peca)
        self.assertFalse(ok)
        self.assertTrue(any("frase" in m.lower() for m in motivos))

    def test_validate_batch_separa_aprovadas_e_reprovadas(self):
        lote = {
            "semana": "2026-07-13",
            "pecas": [
                {
                    "id": "li-ok",
                    "canal": "linkedin",
                    "formato": "texto",
                    "linha": "Framework Próprio",
                    "publicar_em": "2026-07-14T08:00:00",
                    "texto": ("Conteúdo válido de teste. " * 60)[:1300],
                    "racional": "teste",
                },
                {
                    "id": "li-isca",
                    "canal": "linkedin",
                    "formato": "texto",
                    "linha": "Framework Próprio",
                    "publicar_em": "2026-07-14T08:00:00",
                    "texto": ("A Gasparin faturou R$ 500 mil a mais. " * 40)[:1300],
                    "racional": "teste",
                },
            ],
        }
        resultado = validator.validate_batch(lote)
        self.assertEqual(len(resultado["aprovadas"]), 1)
        self.assertEqual(len(resultado["reprovadas"]), 1)
        self.assertEqual(resultado["aprovadas"][0]["id"], "li-ok")
        self.assertEqual(resultado["reprovadas"][0]["peca"]["id"], "li-isca")


if __name__ == "__main__":
    unittest.main()
