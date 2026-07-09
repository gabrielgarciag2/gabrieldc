# -*- coding: utf-8 -*-
"""
src/state.py — persistencia de estado do pipeline.

Mantem:
  - state/history.json: lista de pecas ja publicadas (ou geradas), usada
    para montar a janela de anti-repeticao de 45 dias que e enviada ao
    Cerebro (Claude API) a cada ciclo.
  - state/scheduled.json: mapa {id_peca: {metricool_id, uuid, url_planner}}
    persistido apos cada agendamento bem-sucedido no Metricool.

Contrato de cada item de history.json (secao 9 da especificacao):
    {"tema": str, "linha": str, "data": "YYYY-MM-DD", "canal": str,
     "metrica_principal": float|int|None}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("agente.state")

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
HISTORY_PATH = STATE_DIR / "history.json"
SCHEDULED_PATH = STATE_DIR / "scheduled.json"

JANELA_ANTI_REPETICAO_DIAS = 45


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        logger.warning("Arquivo de estado %s nao existe, usando default.", path)
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Falha ao ler %s (%s). Usando default vazio.", path, exc)
        return default


def _write_json(path: Path, data: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
    tmp_path.replace(path)


def load_state() -> dict:
    """Carrega history.json e scheduled.json e devolve tambem a lista de
    temas dos ultimos 45 dias (para o prompt anti-repeticao do Cerebro)."""
    history = _read_json(HISTORY_PATH, [])
    scheduled = _read_json(SCHEDULED_PATH, {})

    if not isinstance(history, list):
        logger.warning("history.json nao e uma lista - resetando para [].")
        history = []
    if not isinstance(scheduled, dict):
        logger.warning("scheduled.json nao e um dict - resetando para {}.")
        scheduled = {}

    temas_recentes = get_recent_temas(history, JANELA_ANTI_REPETICAO_DIAS)

    return {
        "history": history,
        "scheduled": scheduled,
        "temas_recentes_45d": temas_recentes,
    }


def get_recent_temas(history: list, dias: int = JANELA_ANTI_REPETICAO_DIAS) -> list:
    """Retorna os temas (strings) publicados/gerados nos ultimos `dias` dias."""
    limite = datetime.now() - timedelta(days=dias)
    temas: list = []
    for item in history:
        try:
            data_item = datetime.fromisoformat(str(item.get("data", "")))
        except ValueError:
            continue
        if data_item >= limite:
            tema = item.get("tema")
            if tema:
                temas.append(tema)
    return temas


def append_history(entries: list) -> list:
    """Adiciona novas entradas ao history.json (em memoria) e retorna a
    lista completa ja podada de itens com mais de 90 dias (higiene de
    arquivo - a janela de anti-repeticao em si e de 45 dias)."""
    history = _read_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    history.extend(entries)

    limite_poda = datetime.now() - timedelta(days=90)
    podado = []
    for item in history:
        try:
            data_item = datetime.fromisoformat(str(item.get("data", "")))
        except ValueError:
            podado.append(item)
            continue
        if data_item >= limite_poda:
            podado.append(item)
    return podado


def save_state(history: Optional[list] = None, scheduled: Optional[dict] = None) -> None:
    """Persiste history.json e/ou scheduled.json. Passe None para nao
    tocar em um dos dois arquivos."""
    if history is not None:
        _write_json(HISTORY_PATH, history)
        logger.info("state/history.json salvo com %d itens.", len(history))
    if scheduled is not None:
        _write_json(SCHEDULED_PATH, scheduled)
        logger.info("state/scheduled.json salvo com %d itens.", len(scheduled))
