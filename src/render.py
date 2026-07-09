# -*- coding: utf-8 -*-
"""
src/render.py — "Fabrica de Arte".

Portado de gerar_carrosseis.py (fornecido como insumo), mantendo o mesmo
sistema visual (Navy/Gold/off-white, 1080x1350, footer @gabrielgarciadc,
dots de paginacao, capa/conteudo/CTA com botao dourado).

Funcao publica:
    render(peca_json: dict, output_dir: Path | None = None) -> list[Path]

- canal instagram + formato "carrossel" -> 1 PNG por slide, "{id}_{nn}.png"
- canal instagram + formato "card"       -> 1 PNG, "{id}.png"
- canal linkedin (texto puro)            -> nao gera imagem, lista vazia

Regra de overflow (secao 5 da especificacao): se o texto (titulo OU corpo)
excede a caixa disponivel, a fonte e reduzida em passos de 4px ate caber
(minimo 32px). Se mesmo no minimo o texto nao couber, o corpo e truncado
com reticencias e um aviso e logado.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("agente.render")

W, H = 1080, 1350
NAVY = (31, 56, 100)
NAVY_DARK = (22, 40, 72)
GOLD = (191, 144, 0)
GOLD_LIGHT = (255, 242, 204)
WHITE = (255, 255, 255)
OFFWHITE = (247, 247, 245)
GRAY = (90, 96, 108)

# Caminhos padrao das fontes DejaVu (presentes por default na maioria das
# distros Linux usadas pelo runner do GitHub Actions / ubuntu-latest).
FB_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
FR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]

MIN_FONT_SIZE = 32
FONT_STEP = 4

_FONT_CACHE: dict = {}


def _first_existing(paths: list) -> Optional[str]:
    for p in paths:
        if Path(p).exists():
            return p
    return None


def _font_path(bold: bool) -> Optional[str]:
    candidates = FB_CANDIDATES if bold else FR_CANDIDATES
    return _first_existing(candidates)


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    key = (bold, size)
    if key not in _FONT_CACHE:
        path = _font_path(bold)
        if path is None:
            # Fallback: fonte padrao do Pillow (sem escala, so para nao
            # quebrar em ambientes sem DejaVu instalada).
            logger.warning("Fonte DejaVu nao encontrada, usando fonte default do Pillow.")
            _FONT_CACHE[key] = ImageFont.load_default()
        else:
            _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, maxw: int) -> list:
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if draw.textlength(cur + " " + w, font=f) <= maxw:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _block_height(draw, text, f, maxw, lh=1.28) -> int:
    lines = wrap(draw, text, f, maxw)
    return int(len(lines) * f.size * lh)


def fit_font_and_wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    bold: bool,
    start_size: int,
    maxw: int,
    max_height: int,
    lh: float = 1.28,
    label: str = "",
) -> tuple:
    """Regra de overflow: reduz a fonte em passos de FONT_STEP ate o bloco
    de texto caber em `max_height`, com minimo MIN_FONT_SIZE. Se mesmo no
    minimo nao couber, trunca o texto com reticencias e loga aviso.
    Retorna (font_obj, texto_final, lines)."""
    size = start_size
    while size >= MIN_FONT_SIZE:
        f = font(bold, size)
        height = _block_height(draw, text, f, maxw, lh)
        if height <= max_height:
            return f, text, wrap(draw, text, f, maxw)
        size -= FONT_STEP

    # Nao coube nem no tamanho minimo: truncar com reticencias.
    f = font(bold, MIN_FONT_SIZE)
    truncated = text
    while truncated and _block_height(draw, truncated + "…", f, maxw, lh) > max_height:
        truncated = truncated[:-1]
    truncated = (truncated.rstrip() + "…") if truncated else "…"
    logger.warning(
        "Overflow de texto em '%s': truncado com reticencias na fonte minima (%dpx).",
        label, MIN_FONT_SIZE,
    )
    return f, truncated, wrap(draw, truncated, f, maxw)


def draw_text_block(draw, text, f, x, y, maxw, fill, lh=1.28):
    lines = wrap(draw, text, f, maxw)
    size = f.size
    for ln in lines:
        draw.text((x, y), ln, font=f, fill=fill)
        y += int(size * lh)
    return y


def footer(draw, idx, total, dark_bg):
    col = WHITE if dark_bg else NAVY
    draw.text((80, H - 100), "@gabrielgarciadc", font=font(True, 30), fill=col)
    dot_x = W - 80 - (total * 26)
    for i in range(total):
        cx = dot_x + i * 26
        cy = H - 86
        r = 7 if i == idx else 5
        color = GOLD if i == idx else ((120, 135, 165) if dark_bg else (200, 205, 215))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def slide_cover(kicker: str, title: str, sub: Optional[str] = None) -> Image.Image:
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=GOLD)
    d.rectangle([80, 170, 150, 178], fill=GOLD)
    d.text((80, 200), kicker.upper(), font=font(True, 32), fill=GOLD)

    maxw = W - 160
    # Area disponivel para titulo (+subtitulo opcional) antes do "arraste"
    title_max_h = (H - 190 - 60) - 300 if not sub else int((H - 190 - 60 - 300) * 0.62)
    f_title, title_final, _ = fit_font_and_wrap(
        d, title, True, 84, maxw, max(title_max_h, MIN_FONT_SIZE * 2), 1.18, label="capa.titulo"
    )
    y = draw_text_block(d, title_final, f_title, 80, 300, maxw, WHITE, 1.18)
    if sub:
        sub_max_h = (H - 190 - 60) - y
        f_sub, sub_final, _ = fit_font_and_wrap(
            d, sub, False, 42, maxw, max(sub_max_h, MIN_FONT_SIZE), 1.3, label="capa.subtitulo"
        )
        draw_text_block(d, sub_final, f_sub, 80, y + 50, maxw, (200, 210, 228), 1.3)
    d.text((80, H - 190), "arraste  →", font=font(True, 40), fill=GOLD)
    return img


def slide_content(kicker, title, body, idx, total, num=None, light=True) -> Image.Image:
    bg = OFFWHITE if light else NAVY
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=GOLD)
    tcol = NAVY if light else WHITE
    bcol = GRAY if light else (205, 213, 230)
    maxw = W - 160

    if num:
        d.text((80, 150), num, font=font(True, 150), fill=GOLD)
        d.text((80, 330), kicker.upper(), font=font(True, 30), fill=GOLD)
        ty = 390
    else:
        d.rectangle([80, 170, 150, 178], fill=GOLD)
        d.text((80, 200), kicker.upper(), font=font(True, 30), fill=GOLD)
        ty = 270

    footer_top = H - 130  # respeita area do footer
    total_max_h = footer_top - ty - 45

    # Reserva ~40% da altura para o titulo, resto para o corpo (ajustado
    # dinamicamente pela funcao de fit, que reduz cada bloco de forma
    # independente se necessario).
    title_budget = int(total_max_h * 0.4)
    f_title, title_final, _ = fit_font_and_wrap(
        d, title, True, 62, maxw, max(title_budget, MIN_FONT_SIZE * 2), 1.2, label="conteudo.titulo"
    )
    y = draw_text_block(d, title_final, f_title, 80, ty, maxw, tcol, 1.2)

    body_budget = footer_top - (y + 45)
    f_body, body_final, _ = fit_font_and_wrap(
        d, body, False, 42, maxw, max(body_budget, MIN_FONT_SIZE), 1.34, label="conteudo.corpo"
    )
    draw_text_block(d, body_final, f_body, 80, y + 45, maxw, bcol, 1.34)

    footer(d, idx, total, not light)
    return img


def slide_cta(title, body, idx, total) -> Image.Image:
    img = Image.new("RGB", (W, H), NAVY_DARK)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=GOLD)
    d.rectangle([80, 170, 150, 178], fill=GOLD)
    d.text((80, 200), "AGORA É COM VOCÊ", font=font(True, 30), fill=GOLD)
    maxw = W - 160

    footer_top = H - 130
    button_h = 110 + 70  # botao + espaco antes dele
    total_max_h = footer_top - 280 - button_h

    title_budget = int(total_max_h * 0.45)
    f_title, title_final, _ = fit_font_and_wrap(
        d, title, True, 70, maxw, max(title_budget, MIN_FONT_SIZE * 2), 1.2, label="cta.titulo"
    )
    y = draw_text_block(d, title_final, f_title, 80, 280, maxw, WHITE, 1.2)

    body_budget = footer_top - button_h - (y + 50)
    f_body, body_final, _ = fit_font_and_wrap(
        d, body, False, 44, maxw, max(body_budget, MIN_FONT_SIZE), 1.34, label="cta.corpo"
    )
    y = draw_text_block(d, body_final, f_body, 80, y + 50, maxw, (205, 213, 230), 1.34)

    bx, by = 80, min(y + 70, footer_top - 110)
    d.rounded_rectangle([bx, by, bx + 640, by + 110], radius=16, fill=GOLD)
    d.text((bx + 40, by + 30), "Siga @gabrielgarciadc", font=font(True, 40), fill=NAVY_DARK)
    footer(d, idx, total, True)
    return img


def slide_card(frase: str) -> Image.Image:
    """Card unico (1 frase de impacto, sem paginacao/footer de carrossel,
    mas mantendo o sistema visual: capa navy + kicker + rodape com @)."""
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=GOLD)
    d.rectangle([80, 170, 150, 178], fill=GOLD)
    d.text((80, 200), "GABRIEL GARCIA", font=font(True, 30), fill=GOLD)

    maxw = W - 160
    max_h = (H - 240) - 300
    f, frase_final, _ = fit_font_and_wrap(
        d, frase, True, 80, maxw, max(max_h, MIN_FONT_SIZE * 2), 1.25, label="card.frase"
    )
    # centraliza verticalmente dentro da area disponivel
    lines = wrap(d, frase_final, f, maxw)
    block_h = int(len(lines) * f.size * 1.25)
    y = 300 + max(0, (max_h - block_h) // 2)
    draw_text_block(d, frase_final, f, 80, y, maxw, WHITE, 1.25)

    d.text((80, H - 100), "@gabrielgarciadc", font=font(True, 30), fill=WHITE)
    return img


def _default_output_dir(semana: str) -> Path:
    base = Path(__file__).resolve().parent.parent / "output" / semana
    base.mkdir(parents=True, exist_ok=True)
    return base


def _render_carrossel(peca: dict, out_dir: Path) -> list:
    slides = peca.get("slides", [])
    n = len(slides)
    paths = []
    for i, slide in enumerate(slides):
        tipo = slide.get("tipo")
        if tipo == "capa":
            img = slide_cover(
                peca.get("linha", ""), slide.get("titulo", ""), slide.get("subtitulo")
            )
        elif tipo == "cta":
            img = slide_cta(slide.get("titulo", ""), slide.get("corpo", ""), i, n)
        else:  # "conteudo"
            light = (i % 2 == 1)
            img = slide_content(
                peca.get("linha", ""),
                slide.get("titulo", ""),
                slide.get("corpo", ""),
                i, n,
                num=slide.get("numero"),
                light=light,
            )
        fname = f"{peca['id']}_{i+1:02d}.png"
        fpath = out_dir / fname
        img.save(fpath, optimize=True)
        paths.append(fpath)
    return paths


def _render_card(peca: dict, out_dir: Path) -> list:
    img = slide_card(peca.get("frase", ""))
    fpath = out_dir / f"{peca['id']}.png"
    img.save(fpath, optimize=True)
    return [fpath]


def render(peca_json: dict, output_dir: Optional[Path] = None, semana: str = "semana") -> list:
    """Renderiza uma peca (dict do contrato §4.1) em PNG(s) e retorna a
    lista de Paths gerados. Pecas de LinkedIn (texto puro) nao geram
    imagem — retorna lista vazia."""
    canal = peca_json.get("canal")
    formato = peca_json.get("formato")
    out_dir = output_dir or _default_output_dir(semana)
    out_dir.mkdir(parents=True, exist_ok=True)

    if canal == "linkedin":
        return []
    if canal == "instagram" and formato == "carrossel":
        return _render_carrossel(peca_json, out_dir)
    if canal == "instagram" and formato == "card":
        return _render_card(peca_json, out_dir)

    logger.warning("Peca %s com canal/formato desconhecido (%s/%s) — nada renderizado.",
                    peca_json.get("id"), canal, formato)
    return []


def render_images(lote: dict, output_dir: Optional[Path] = None) -> dict:
    """Renderiza todas as pecas de um lote (§4.1) e retorna
    {id_peca: [Path, ...]}. Falha de uma peca nao aborta as demais."""
    semana = lote.get("semana", "semana")
    out_dir = output_dir or _default_output_dir(semana)
    resultado = {}
    for peca in lote.get("pecas", []):
        try:
            resultado[peca["id"]] = render(peca, out_dir, semana)
        except Exception:
            logger.exception("Falha ao renderizar peca %s — pulando.", peca.get("id"))
            resultado[peca.get("id", "desconhecida")] = []
    return resultado
