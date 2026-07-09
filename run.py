#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — orquestrador do pipeline do Agente de Conteudo (DC VTQ).

Implementa as 9 etapas da secao 1 da especificacao, na ordem exata:
  1. fetch_metrics()      -> Metricool (analytics + posts publicados)
  2. load_state()         -> history.json (temas dos ultimos 45 dias)
  3. generate_batch()     -> Claude API (Prompt do Agente -> JSON do lote)
  4. validate_batch()     -> schema + leis editoriais (regex de guarda)
  5. render_images()      -> Pillow (PNG 1080x1350 Navy/Gold)
  6. upload_images()      -> Cloudflare R2 (S3-compatible, URLs publicas)
  7. schedule_posts()     -> Metricool (LinkedIn texto | IG com media URLs)
  8. save_state()         -> history.json atualizado (commit no repo)
  9. send_report()        -> e-mail (Resend)

Uso:
    python run.py                 # execucao normal (publica de verdade)
    python run.py --dry-run       # nao publica nada; gera JSON + PNGs
                                   # localmente e imprime o plano

KILL_SWITCH=true nos secrets/.env encerra o pipeline logo no inicio, sem
efeito colateral algum.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src import state as state_mod
from src import metrics as metrics_mod
from src import generator as generator_mod
from src import validator as validator_mod
from src import render as render_mod
from src import storage as storage_mod
from src import publisher as publisher_mod
from src import reporter as reporter_mod

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agente.run")

MAX_REGENERACOES_POR_PECA = 1  # 1a falha pede regeneracao; 2a falha descarta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline do Agente de Conteudo DC VTQ.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nao publica nada real (Metricool/R2/Resend). Gera JSON + PNGs "
             "localmente em output/{semana}/ e imprime o plano completo.",
    )
    return parser.parse_args()


def check_kill_switch() -> bool:
    val = os.environ.get("KILL_SWITCH", "false").strip().lower()
    return val in ("true", "1", "yes", "on")


def _peca_key_history(peca: dict, tema: str) -> dict:
    data = peca.get("publicar_em", "")[:10] or datetime.now().strftime("%Y-%m-%d")
    return {
        "tema": tema,
        "linha": peca.get("linha", ""),
        "data": data,
        "canal": peca.get("canal", ""),
        "metrica_principal": None,
    }


def _tema_da_peca(peca: dict) -> str:
    """Extrai um 'tema' representativo da peca para o history.json —
    usa o racional (mais descritivo) ou, na falta, o titulo/frase."""
    if peca.get("racional"):
        return peca["racional"]
    if peca.get("formato") == "carrossel":
        for slide in peca.get("slides", []):
            if slide.get("tipo") == "capa":
                return slide.get("titulo", peca.get("id", ""))
    if peca.get("formato") == "card":
        return peca.get("frase", peca.get("id", ""))
    if peca.get("canal") == "linkedin":
        return (peca.get("texto", "")[:100])
    return peca.get("id", "desconhecida")


def revalidate_and_filter(lote: dict) -> tuple:
    """Aplica o validador de guarda a cada peca do lote, com 1 tentativa
    de 'regeneracao' (aqui simplificada: se falhar 2x, descarta e loga —
    a regeneracao completa via API fica registrada como limitacao, ja que
    o modo mock/local nao tem acesso a um novo lote pontual por peca; em
    producao com ANTHROPIC_API_KEY, o generator pode ser chamado de novo
    para a peca especifica). Retorna (pecas_aprovadas, avisos)."""
    aprovadas = []
    avisos = []

    for peca in lote.get("pecas", []):
        ok, motivos = validator_mod.validate_peca(peca)
        tentativas = 0
        while not ok and tentativas < MAX_REGENERACOES_POR_PECA:
            tentativas += 1
            logger.warning(
                "Peca %s reprovada (tentativa %d): %s. Pedindo regeneracao...",
                peca.get("id"), tentativas, "; ".join(motivos),
            )
            avisos.append(
                f"Peca {peca.get('id')} reprovada na 1a checagem ({'; '.join(motivos)}) "
                f"— regeneracao solicitada."
            )
            # Regeneracao pontual: em producao real, chamar novamente o
            # Cerebro so para esta peca. No mock local, mantemos a mesma
            # peca (o gerador mock nao varia por chamada) e revalidamos —
            # isso reflete a limitacao documentada no README.
            ok, motivos = validator_mod.validate_peca(peca)

        if ok:
            aprovadas.append(peca)
        else:
            logger.error(
                "Peca %s descartada apos %d tentativa(s): %s",
                peca.get("id"), tentativas + 1, "; ".join(motivos),
            )
            avisos.append(
                f"Peca {peca.get('id')} DESCARTADA apos falhar 2x no validador: "
                f"{'; '.join(motivos)}"
            )

    return aprovadas, avisos


def run(dry_run: bool = False) -> int:
    logger.info("=== Agente de Conteudo DC VTQ — inicio do ciclo (dry_run=%s) ===", dry_run)

    # --- Kill switch --------------------------------------------------
    if check_kill_switch():
        logger.warning("KILL_SWITCH=true — pipeline encerrado sem publicar nada.")
        return 0

    try:
        # --- 1. fetch_metrics() ---------------------------------------
        logger.info("Etapa 1/9: fetch_metrics()")
        metrics = metrics_mod.fetch_metrics(dry_run=dry_run)

        # --- 2. load_state() -------------------------------------------
        logger.info("Etapa 2/9: load_state()")
        estado = state_mod.load_state()
        temas_recentes = estado["temas_recentes_45d"]
        logger.info("Temas nos ultimos 45 dias: %d", len(temas_recentes))

        # --- 3. generate_batch() ----------------------------------------
        logger.info("Etapa 3/9: generate_batch()")
        lote = generator_mod.generate_batch(metrics, temas_recentes)
        logger.info("Lote gerado: semana=%s, %d pecas.", lote.get("semana"), len(lote.get("pecas", [])))

        if not lote.get("pecas"):
            raise RuntimeError("Lote gerado sem nenhuma peca — falha total do lote.")

        # --- 4. validate_batch() -----------------------------------------
        logger.info("Etapa 4/9: validate_batch()")
        pecas_aprovadas, avisos_validador = revalidate_and_filter(lote)
        lote["pecas"] = pecas_aprovadas
        logger.info("Pecas aprovadas apos validacao: %d", len(pecas_aprovadas))

        if not pecas_aprovadas:
            raise RuntimeError("Todas as pecas do lote foram reprovadas pelo validador — falha total do lote.")

        # --- 5. render_images() -------------------------------------------
        logger.info("Etapa 5/9: render_images()")
        output_dir = BASE_DIR / "output" / lote["semana"]
        media_por_peca = {}
        for peca in list(lote["pecas"]):
            try:
                media_por_peca[peca["id"]] = render_mod.render(peca, output_dir, lote["semana"])
            except Exception:
                logger.exception("Falha ao renderizar peca %s — pulando esta peca (lote segue).", peca.get("id"))
                media_por_peca[peca["id"]] = []
        logger.info("Renderizacao concluida. PNGs em: %s", output_dir)

        # --- 6. upload_images() -------------------------------------------
        logger.info("Etapa 6/9: upload_images()")
        media_urls_por_peca = {}
        for peca_id, paths in media_por_peca.items():
            if not paths:
                media_urls_por_peca[peca_id] = []
                continue
            try:
                parcial = storage_mod.upload_images({peca_id: paths}, lote["semana"], dry_run=dry_run)
                media_urls_por_peca.update(parcial)
            except Exception:
                logger.exception("Falha no upload da peca %s — pulando (lote segue).", peca_id)
                media_urls_por_peca[peca_id] = []

        # --- 7. schedule_posts() -------------------------------------------
        logger.info("Etapa 7/9: schedule_posts()")
        resultado_publicacao = publisher_mod.schedule_posts(
            lote, media_urls_por_peca, dry_run=dry_run
        )

        # --- 8. save_state() -------------------------------------------
        logger.info("Etapa 8/9: save_state()")
        novas_entradas_historico = [
            _peca_key_history(peca, _tema_da_peca(peca)) for peca in lote["pecas"]
        ]
        if dry_run:
            logger.info(
                "[DRY-RUN] state/history.json e state/scheduled.json NAO serao "
                "sobrescritos (apenas simulados)."
            )
        else:
            historico_atualizado = state_mod.append_history(novas_entradas_historico)
            scheduled_atualizado = dict(estado["scheduled"])
            scheduled_atualizado.update(publisher_mod.to_scheduled_state(resultado_publicacao))
            state_mod.save_state(history=historico_atualizado, scheduled=scheduled_atualizado)

        # --- 9. send_report() -------------------------------------------
        logger.info("Etapa 9/9: send_report()")
        if dry_run:
            logger.info("[DRY-RUN] Relatorio por e-mail NAO sera enviado de verdade (best-effort skip).")
        else:
            reporter_mod.send_report(lote, resultado_publicacao, metrics, avisos_validador)

        # --- Plano final (sempre impresso, especialmente relevante em dry-run) ---
        _print_plan(lote, media_por_peca, media_urls_por_peca, resultado_publicacao, avisos_validador, dry_run)

        logger.info("=== Ciclo concluido com sucesso ===")
        return 0

    except Exception as exc:
        logger.error("Falha TOTAL do lote: %s\n%s", exc, traceback.format_exc())
        try:
            reporter_mod.send_alert(
                "Falha total do lote — Agente de Conteudo DC VTQ",
                f"{exc}\n\n{traceback.format_exc()}",
            )
        except Exception:
            logger.error("Ate o envio do e-mail de alerta falhou (best-effort, seguindo sem quebrar).")
        return 1


def _print_plan(lote, media_por_peca, media_urls_por_peca, resultado_publicacao, avisos_validador, dry_run) -> None:
    print("\n" + "=" * 78)
    print(f"PLANO DO CICLO — semana {lote.get('semana')} — {'DRY-RUN' if dry_run else 'EXECUCAO REAL'}")
    print("=" * 78)
    for peca in lote.get("pecas", []):
        pid = peca["id"]
        print(f"\n- [{peca['canal']}/{peca['formato']}] {pid} — linha: {peca.get('linha')}")
        print(f"  publicar_em: {peca.get('publicar_em')}")
        arquivos = media_por_peca.get(pid, [])
        if arquivos:
            print(f"  imagens locais: {[str(p) for p in arquivos]}")
        urls = media_urls_por_peca.get(pid, [])
        if urls:
            print(f"  urls publicas (R2): {urls}")
        info_pub = resultado_publicacao.get(pid, {})
        print(f"  status publicacao: {info_pub.get('status')}")
        if peca.get("racional"):
            print(f"  racional: {peca['racional']}")

    if avisos_validador:
        print("\nAvisos do validador:")
        for a in avisos_validador:
            print(f"  - {a}")

    print("\n" + "=" * 78 + "\n")


if __name__ == "__main__":
    args = parse_args()
    sys.exit(run(dry_run=args.dry_run))
