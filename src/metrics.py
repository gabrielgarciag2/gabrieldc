# -*- coding: utf-8 -*-
"""
src/metrics.py — cliente Metricool para leitura de metricas ("Auditor").

fetch_metrics() busca, para o ciclo anterior:
  - analytics (alcance, interacoes, seguidores) via endpoint equivalente a
    getAnalyticsDataByMetrics;
  - posts publicados no periodo (para achar top-3 / bottom-3 por
    engajamento) via endpoint equivalente a getScheduledPosts.

AUTENTICACAO — CONFIRMADO em 09/07/2026 contra a doc oficial
(static.metricool.com/API+DOC/API+English.pdf) e o Help Center do
Metricool: base URL `https://app.metricool.com/api`; o token vai no
HEADER `X-Mc-Auth: <userToken>` (NAO como query param); `userId` e
`blogId` vao como query params em toda chamada.

ENDPOINTS — nivel de confianca por chamada:
  - CONFIRMADO: `GET /api/v2/analytics/reels/instagram?from&to` (padrao
    `/v2/analytics/{tipo}/{rede}` documentado oficialmente).
  - CONFIRMADO: `GET /api/stats/timeline/{metrica}?start&end` (ex.:
    `igFollowers`) para series temporais — a doc oficial grafa
    "timeling" (provavel erro de digitacao deles); usamos "timeline".
  - NAO CONFIRMADO (best-effort): endpoint exato para metricas
    POR POST (alcance/interacoes/salvamentos de cada peca publicada).
    Assumimos `GET /api/v2/analytics/posts/instagram` seguindo o
    padrao acima e a nomenclatura usada pela CLI nao-oficial da
    comunidade — CONFIRME pelo inspector do navegador (Planning >
    Analytics, filtro Fetch/XHR) antes de operar em producao, como a
    propria doc do Metricool recomenda para casos nao documentados.
  - NAO CONFIRMADO: `GET /api/v2/scheduler/posts` para listar posts
    publicados no periodo — inferido por simetria com o endpoint de
    criacao (`POST /v2/scheduler/posts`), mas nao verificado.

Fontes: https://static.metricool.com/API+DOC/API+English.pdf ·
https://help.metricool.com/en/article/how-to-get-an-endpoint-in-metricool-to-make-api-calls-15xciw7/

Em dry-run (ou se METRICOOL_USER_TOKEN nao estiver setado), fetch_metrics()
retorna um payload de metricas vazio/mock, sem chamada de rede.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("agente.metrics")

METRICOOL_API_BASE = "https://app.metricool.com/api"
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3


def _auth_headers() -> dict:
    return {"X-Mc-Auth": os.environ.get("METRICOOL_USER_TOKEN", "")}


def _auth_params() -> dict:
    return {
        "userId": os.environ.get("METRICOOL_USER_ID", ""),
        "blogId": os.environ.get("METRICOOL_BLOG_ID", ""),
    }


def _request_with_retry(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=DEFAULT_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("Falha na chamada %s %s (tentativa %d/%d): %s",
                            method, url, attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    logger.error("Todas as tentativas para %s %s falharam: %s", method, url, last_exc)
    return None


def _empty_metrics() -> dict:
    return {
        "alcance_total": None,
        "interacoes_total": None,
        "seguidores": None,
        "posts": [],
        "top_3": [],
        "bottom_3": [],
        "fonte": "mock/indisponivel",
    }


def fetch_metrics(dry_run: bool = False) -> dict:
    """Busca metricas do ciclo anterior no Metricool. Em dry-run ou sem
    credenciais configuradas, retorna metricas vazias sem chamada de
    rede (nao derruba o pipeline)."""
    token = os.environ.get("METRICOOL_USER_TOKEN")
    if dry_run or not token:
        logger.info(
            "fetch_metrics: dry-run ativo ou METRICOOL_USER_TOKEN ausente — "
            "retornando metricas vazias (sem chamada de rede)."
        )
        return _empty_metrics()

    params = _auth_params()
    headers = _auth_headers()

    # Best-effort (nao confirmado) — ver docstring do modulo.
    analytics_resp = _request_with_retry(
        "GET", f"{METRICOOL_API_BASE}/v2/analytics/posts/instagram",
        params=params, headers=headers,
    )
    posts_resp = _request_with_retry(
        "GET", f"{METRICOOL_API_BASE}/v2/scheduler/posts",
        params=params, headers=headers,
    )

    if analytics_resp is None and posts_resp is None:
        logger.warning("Nao foi possivel obter metricas do Metricool — seguindo com dados vazios.")
        return _empty_metrics()

    posts = []
    try:
        if posts_resp is not None:
            posts = posts_resp.json().get("data", []) or []
    except ValueError:
        logger.warning("Resposta de posts do Metricool nao e JSON valido.")

    analytics = {}
    try:
        if analytics_resp is not None:
            analytics = analytics_resp.json()
    except ValueError:
        logger.warning("Resposta de analytics do Metricool nao e JSON valido.")

    posts_ordenados = sorted(
        posts, key=lambda p: p.get("interactions", p.get("engagement", 0)) or 0, reverse=True
    )
    top_3 = posts_ordenados[:3]
    bottom_3 = list(reversed(posts_ordenados[-3:])) if len(posts_ordenados) >= 3 else []

    return {
        "alcance_total": analytics.get("reach"),
        "interacoes_total": analytics.get("interactions"),
        "seguidores": analytics.get("followers"),
        "posts": posts,
        "top_3": top_3,
        "bottom_3": bottom_3,
        "fonte": "metricool_api",
    }
