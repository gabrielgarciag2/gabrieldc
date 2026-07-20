# -*- coding: utf-8 -*-
"""
src/render.py — "Fabrica de Arte".

Sistema visual unificado (branco/preto/azul, com azul petróleo como
destaque pontual), 1080x1350, footer @gabrielgarciadc, dots de
paginacao, capa/conteudo/CTA com botao azul.

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

# Paleta editorial unica (branco / preto / azul), com azul petroleo
# reservado para destaques pontuais. Usada em todos os formatos —
# carrossel e card — para manter identidade visual consistente.
WHITE = (255, 255, 255)
WHITE_SOFT = (223, 228, 234)   # branco suave p/ texto secundario em fundo escuro
BLACK = (17, 17, 20)
BLACK_SOFT = (60, 64, 72)      # preto suave p/ texto secundario em fundo claro
BLUE = (10, 102, 194)          # azul primario — kickers, botoes, links, dots ativos
BLUE_TINT = (198, 214, 230)    # tom claro do azul — elementos secundarios em fundo claro
PETROL = (11, 61, 74)          # azul petroleo — destaque pontual (capa)
PETROL_TINT = (70, 100, 112)   # tom do petroleo — elementos secundarios em fundo escuro

# Paleta do card branco (retrato + gancho/virada) — mesma paleta unificada.
CARD_BLACK = BLACK
CARD_BLUE = BLUE
CARD_GRAY = BLACK_SOFT
CARD_GRAY_DARK = BLACK_SOFT
CARD_DIVIDER = (225, 227, 230)
CARD_ICON = BLACK_SOFT

PHOTO_PATH = Path(__file__).resolve().parent.parent / "assets" / "gabriel-garcia.jpg"
CARD_NAME = "Gabriel Garcia"
CARD_ROLE_LINE1 = "CEO Dale Carnegie Vale do Taquari"
CARD_ROLE_LINE2 = "Master Trainer | Trainer Certificado"

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
    col = WHITE if dark_bg else BLACK
    draw.text((80, H - 100), "@gabrielgarciadc", font=font(True, 30), fill=col)
    dot_x = W - 80 - (total * 26)
    for i in range(total):
        cx = dot_x + i * 26
        cy = H - 86
        r = 7 if i == idx else 5
        color = BLUE if i == idx else (PETROL_TINT if dark_bg else BLUE_TINT)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def slide_cover(kicker: str, title: str, sub: Optional[str] = None) -> Image.Image:
    img = Image.new("RGB", (W, H), PETROL)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=BLUE)
    d.rectangle([80, 170, 150, 178], fill=BLUE)
    d.text((80, 200), kicker.upper(), font=font(True, 32), fill=BLUE)

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
        draw_text_block(d, sub_final, f_sub, 80, y + 50, maxw, WHITE_SOFT, 1.3)
    d.text((80, H - 190), "arraste  →", font=font(True, 40), fill=BLUE)
    return img


def slide_content(kicker, title, body, idx, total, num=None, light=True) -> Image.Image:
    bg = WHITE if light else BLACK
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=BLUE)
    tcol = BLACK if light else WHITE
    bcol = BLACK_SOFT if light else WHITE_SOFT
    maxw = W - 160

    if num:
        d.text((80, 150), num, font=font(True, 150), fill=BLUE)
        d.text((80, 330), kicker.upper(), font=font(True, 30), fill=BLUE)
        ty = 390
    else:
        d.rectangle([80, 170, 150, 178], fill=BLUE)
        d.text((80, 200), kicker.upper(), font=font(True, 30), fill=BLUE)
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
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=BLUE)
    d.rectangle([80, 170, 150, 178], fill=BLUE)
    d.text((80, 200), "AGORA É COM VOCÊ", font=font(True, 30), fill=BLUE)
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
    y = draw_text_block(d, body_final, f_body, 80, y + 50, maxw, WHITE_SOFT, 1.34)

    bx, by = 80, min(y + 70, footer_top - 110)
    d.rounded_rectangle([bx, by, bx + 640, by + 110], radius=16, fill=BLUE)
    d.text((bx + 40, by + 30), "Siga @gabrielgarciadc", font=font(True, 40), fill=WHITE)
    footer(d, idx, total, True)
    return img


def _circular_photo(path: Path, diameter: int) -> Optional[Image.Image]:
    """Carrega a foto real do perfil e recorta em circulo (cover-crop
    quadrado + mascara elipse). Retorna None (e loga aviso) se o arquivo
    nao existir — o card e renderizado sem foto nesse caso, nunca com
    imagem gerada/substituta."""
    if not path.exists():
        logger.warning("Foto de perfil nao encontrada em %s — card sera renderizado sem foto.", path)
        return None
    img = Image.open(path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter, diameter], fill=255)
    out = Image.new("RGBA", (diameter, diameter))
    out.paste(img, (0, 0), mask)
    return out


def _linkedin_badge(d: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    d.rounded_rectangle([x, y, x + size, y + size], radius=max(4, int(size * 0.18)), fill=CARD_BLUE)
    bf = font(True, int(size * 0.6))
    tw = d.textlength("in", font=bf)
    d.text((x + (size - tw) / 2, y + size * 0.16), "in", font=bf, fill=WHITE)


def _icon_comment(d: ImageDraw.ImageDraw, x: int, y: int, s: int, color, width: int = 5) -> None:
    d.rounded_rectangle([x, y, x + s, y + s * 0.78], radius=s * 0.22, outline=color, width=width)
    d.polygon(
        [(x + s * 0.16, y + s * 0.78 - 2), (x + s * 0.16, y + s * 1.02), (x + s * 0.42, y + s * 0.78 - 2)],
        fill=color,
    )


def _icon_heart(d: ImageDraw.ImageDraw, x: int, y: int, s: int, color) -> None:
    # Glifo de coracao (contorno) da propria fonte DejaVu Sans — mais limpo
    # e fiel que uma aproximacao desenhada com primitivas.
    f = font(True, int(s * 1.55))
    d.text((x, y - s * 0.28), "\u2661", font=f, fill=color)


def _icon_share(d: ImageDraw.ImageDraw, x: int, y: int, s: int, color, width: int = 4) -> None:
    r = s * 0.1
    p1, p2, p3 = (x, y + s * 0.5), (x + s, y), (x + s, y + s)
    d.line([p1, p2], fill=color, width=width)
    d.line([p1, p3], fill=color, width=width)
    for p in (p1, p2, p3):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], outline=color, width=width)


def _fit_gancho_virada(
    d: ImageDraw.ImageDraw, gancho: str, virada: str, maxw: int, max_h: int,
    lh: float = 1.28, start_size: int = 64,
) -> tuple:
    """Encontra o maior tamanho de fonte (ate MIN_FONT_SIZE) em que gancho
    + virada, wrapped separadamente (cada um comeca em linha nova), cabem
    juntos em max_h. Retorna (font, linhas_gancho, linhas_virada)."""
    size = start_size
    while size >= MIN_FONT_SIZE:
        f = font(True, size)
        g_lines = wrap(d, gancho, f, maxw)
        v_lines = wrap(d, virada, f, maxw)
        total_h = int((len(g_lines) + len(v_lines)) * f.size * lh)
        if total_h <= max_h:
            return f, g_lines, v_lines
        size -= FONT_STEP
    f = font(True, MIN_FONT_SIZE)
    logger.warning("Overflow em card.gancho/virada: usando fonte minima (%dpx) mesmo sem caber.", MIN_FONT_SIZE)
    return f, wrap(d, gancho, f, maxw), wrap(d, virada, f, maxw)


def slide_card(gancho: str, virada: str) -> Image.Image:
    """Card unico: fundo branco, foto de perfil circular, nome + badge
    LinkedIn, subtitulo (cargo), frase em duas cores (gancho preto +
    virada azul), divisor e rodape com icones + @gabrielgarciadc."""
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    pad = 80

    photo_d = 110
    photo_y = 100
    photo = _circular_photo(PHOTO_PATH, photo_d)
    if photo:
        img.paste(photo, (pad, photo_y), photo)
    text_x = pad + photo_d + 28

    name_font = font(True, 44)
    d.text((text_x, photo_y + 4), CARD_NAME, font=name_font, fill=CARD_BLACK)
    name_w = d.textlength(CARD_NAME, font=name_font)
    _linkedin_badge(d, int(text_x + name_w + 14), photo_y + 8, 32)

    sub_font = font(False, 27)
    d.text((text_x, photo_y + 58), CARD_ROLE_LINE1, font=sub_font, fill=CARD_GRAY)
    d.text((text_x, photo_y + 92), CARD_ROLE_LINE2, font=sub_font, fill=CARD_GRAY)

    maxw = W - 2 * pad
    quote_top = photo_y + photo_d + 70
    divider_y = H - 220
    max_h = divider_y - quote_top - 30
    f, gancho_lines, virada_lines = _fit_gancho_virada(
        d, gancho, virada, maxw, max(max_h, MIN_FONT_SIZE * 2)
    )
    lh = 1.28
    block_h = int((len(gancho_lines) + len(virada_lines)) * f.size * lh)
    # Alinha perto do topo da area (nao centraliza no espaco todo ate o
    # divisor) para que frases curtas nao fiquem "flutuando" no meio.
    y = quote_top + min(40, max(0, (max_h - block_h) // 2))
    for ln in gancho_lines:
        d.text((pad, y), ln, font=f, fill=CARD_BLACK)
        y += int(f.size * lh)
    for ln in virada_lines:
        d.text((pad, y), ln, font=f, fill=CARD_BLUE)
        y += int(f.size * lh)

    d.line([(pad, divider_y), (W - pad, divider_y)], fill=CARD_DIVIDER, width=2)

    icon_y = divider_y + 45
    icon_s = 38
    gap = 32
    _icon_comment(d, pad, icon_y, icon_s, CARD_ICON)
    _icon_heart(d, pad + icon_s + gap, icon_y, icon_s, CARD_ICON)
    _icon_share(d, pad + 2 * (icon_s + gap), icon_y, icon_s, CARD_ICON)

    handle_font = font(True, 30)
    handle = "@gabrielgarciadc"
    hw = d.textlength(handle, font=handle_font)
    d.text((W - pad - hw, icon_y + 4), handle, font=handle_font, fill=CARD_GRAY_DARK)

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
    img = slide_card(peca.get("gancho", ""), peca.get("virada", ""))
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
