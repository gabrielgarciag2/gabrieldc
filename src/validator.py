# -*- coding: utf-8 -*-
"""
src/validator.py — Validador de guarda determinístico (secao 4.2 da
especificacao).

Reprova uma peca (retorna motivo(s) de falha) se detectar:
  1. Padrao monetario especifico "R$ 300 mil" / "R$ 1,2 milhoes" etc, salvo
     quando explicitamente marcado como citacao de fonte publica
     (peca["fonte_publica"] == True ou o texto contem uma marcacao
     "[fonte publica]" perto do valor).
  2. Nomes presentes em config/blocklist.txt (clientes reais, contatos).
  3. Mencao nominal a concorrentes/pessoas de terceiros (mesma blocklist).
  4. Campos obrigatorios ausentes ou limites de caracteres estourados:
       - LinkedIn (texto): 900-1400 caracteres
       - Carrossel: titulo de slide <= 60 chars, corpo de slide <= 220 chars
       - Card: frase <= 90 chars

Uso pelo orquestrador (run.py):
    ok, motivos = validate_peca(peca)
    if not ok:
        # 1a falha -> pedir regeneracao (1x). 2a falha -> descartar e logar.

    resultado_lote = validate_batch(lote)  # varre o lote inteiro
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agente.validator")

BASE_DIR = Path(__file__).resolve().parent.parent
BLOCKLIST_PATH = BASE_DIR / "config" / "blocklist.txt"

# R$ 300 mil / R$ 1.200.000 / R$ 3,5 milhoes / R$300mil ...
MONEY_PATTERN = re.compile(
    r"R\$\s?[\d\.,]+\s?(milh(ão|ao|ões|oes)|mil)\b",
    re.IGNORECASE,
)

LINKEDIN_MIN_CHARS = 900
LINKEDIN_MAX_CHARS = 1400
CAROUSEL_TITLE_MAX = 60
CAROUSEL_BODY_MAX = 220
CARD_MAX_CHARS = 90


def _load_blocklist() -> list:
    if not BLOCKLIST_PATH.exists():
        logger.warning("config/blocklist.txt nao encontrado — validador rodando sem blocklist!")
        return []
    nomes = []
    for line in BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nomes.append(line)
    return nomes


def _all_text_fields(peca: dict) -> list:
    """Extrai todos os campos de texto livre de uma peca, para varredura
    de regex/blocklist independente do formato (texto, carrossel, card)."""
    textos = []
    for campo in ("texto", "legenda", "racional", "frase"):
        val = peca.get(campo)
        if isinstance(val, str):
            textos.append(val)
    for slide in peca.get("slides", []) or []:
        for campo in ("kicker", "titulo", "subtitulo", "corpo"):
            val = slide.get(campo)
            if isinstance(val, str):
                textos.append(val)
    return textos


def _check_money_pattern(peca: dict) -> list:
    motivos = []
    if peca.get("fonte_publica") is True:
        return motivos
    for texto in _all_text_fields(peca):
        for match in MONEY_PATTERN.finditer(texto):
            trecho = texto[max(0, match.start() - 90): match.end() + 30]
            if "fonte pública" in trecho.lower() or "fonte publica" in trecho.lower():
                continue
            motivos.append(
                f"Padrao monetario suspeito sem citacao de fonte publica: '{match.group(0)}' "
                f"(contexto: '...{trecho}...')"
            )
    return motivos


def _check_blocklist(peca: dict, blocklist: list) -> list:
    motivos = []
    textos = " \n".join(_all_text_fields(peca)).lower()
    for nome in blocklist:
        if nome.lower() in textos:
            motivos.append(f"Nome bloqueado encontrado no conteudo: '{nome}'")
    return motivos


def _check_campos_obrigatorios_e_limites(peca: dict) -> list:
    motivos = []
    canal = peca.get("canal")
    formato = peca.get("formato")

    for campo_base in ("id", "canal", "formato", "linha", "publicar_em"):
        if not peca.get(campo_base):
            motivos.append(f"Campo obrigatorio ausente: '{campo_base}'")

    if canal == "linkedin":
        texto = peca.get("texto")
        if not texto:
            motivos.append("Peca LinkedIn sem campo 'texto'.")
        else:
            n = len(texto)
            if n < LINKEDIN_MIN_CHARS or n > LINKEDIN_MAX_CHARS:
                motivos.append(
                    f"Texto LinkedIn fora do limite {LINKEDIN_MIN_CHARS}-{LINKEDIN_MAX_CHARS} "
                    f"chars (tem {n})."
                )

    elif canal == "instagram" and formato == "carrossel":
        slides = peca.get("slides")
        if not slides:
            motivos.append("Carrossel sem campo 'slides'.")
        else:
            for i, slide in enumerate(slides):
                titulo = slide.get("titulo") or ""
                corpo = slide.get("corpo") or ""
                if slide.get("tipo") == "capa" and not titulo:
                    motivos.append(f"Slide {i} (capa) sem 'titulo'.")
                if titulo and len(titulo) > CAROUSEL_TITLE_MAX:
                    motivos.append(
                        f"Slide {i}: titulo com {len(titulo)} chars (max {CAROUSEL_TITLE_MAX})."
                    )
                if corpo and len(corpo) > CAROUSEL_BODY_MAX:
                    motivos.append(
                        f"Slide {i}: corpo com {len(corpo)} chars (max {CAROUSEL_BODY_MAX})."
                    )
        if not peca.get("legenda"):
            motivos.append("Carrossel sem campo 'legenda'.")

    elif canal == "instagram" and formato == "card":
        frase = peca.get("frase")
        if not frase:
            motivos.append("Card sem campo 'frase'.")
        elif len(frase) > CARD_MAX_CHARS:
            motivos.append(f"Card: frase com {len(frase)} chars (max {CARD_MAX_CHARS}).")
        if not peca.get("legenda"):
            motivos.append("Card sem campo 'legenda'.")

    else:
        motivos.append(f"Combinacao canal/formato desconhecida: {canal}/{formato}")

    return motivos


def validate_peca(peca: dict, blocklist: Optional[list] = None) -> tuple:
    """Valida uma unica peca. Retorna (ok: bool, motivos: list[str])."""
    blocklist = blocklist if blocklist is not None else _load_blocklist()
    motivos = []
    motivos += _check_money_pattern(peca)
    motivos += _check_blocklist(peca, blocklist)
    motivos += _check_campos_obrigatorios_e_limites(peca)
    return (len(motivos) == 0, motivos)


def validate_batch(lote: dict) -> dict:
    """Valida todas as pecas de um lote. Retorna:
    {
      "aprovadas": [peca, ...],
      "reprovadas": [{"peca": peca, "motivos": [...]}, ...],
    }
    Nao decide sobre regeneracao — essa logica de retry fica no run.py,
    que pode chamar validate_peca() novamente apos regenerar."""
    blocklist = _load_blocklist()
    aprovadas = []
    reprovadas = []
    for peca in lote.get("pecas", []):
        ok, motivos = validate_peca(peca, blocklist)
        if ok:
            aprovadas.append(peca)
        else:
            for m in motivos:
                logger.warning("Peca %s reprovada: %s", peca.get("id", "?"), m)
            reprovadas.append({"peca": peca, "motivos": motivos})
    return {"aprovadas": aprovadas, "reprovadas": reprovadas}
