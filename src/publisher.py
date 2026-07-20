# -*- coding: utf-8 -*-
"""
src/publisher.py — Publicador (Metricool), secao 7 da especificacao.

PADRAO ATUAL (cadencia 2x/dia, 08h/19h — ver src/generator.py): toda peca
e publicada em duplo-canal (Instagram + LinkedIn) no MESMO post do
Metricool via build_combined_payload() — mesma imagem, mesmo texto,
`providers` com as duas redes. Esse e o formato confirmado como o que
esta realmente em uso na fila viva do Metricool.

build_linkedin_payload / build_instagram_payload (payloads por canal
separado) sao mantidos como COPIA LITERAL dos contratos JSON das secoes
7.1 e 7.2 da especificacao original, apenas parametrizando os campos
variaveis (texto/media/data/legenda) — usados hoje só como fallback de
compatibilidade para lotes antigos (ver `_build_payload_for_peca`).

AUTENTICACAO — CONFIRMADO contra a documentacao oficial (04/09/2024,
static.metricool.com/API+DOC/API+English.pdf) e o Help Center do
Metricool em 09/07/2026:
  - Base URL: https://app.metricool.com/api
  - Toda chamada exige 3 identificadores: o token vai no HEADER
    `X-Mc-Auth: <userToken>` — NAO como query param. `userId` e `blogId`
    vao como QUERY PARAMS.
  - Endpoint de agendamento CONFIRMADO: `POST /v2/scheduler/posts`
    (com `blogId` e `userId` na query string).

MIDIA EXTERNA — PASSO CONFIRMADO QUE FALTAVA NA ESPECIFICACAO ORIGINAL:
A doc oficial mostra que, para publicar com uma URL de midia externa
(nosso caso: PNGs hospedados no R2), e preciso primeiro "normalizar" a
URL numa chamada a parte, ANTES de agendar o post:
  GET /api/actions/normalize/image/url?url=<url_da_midia>&blogId=&userId=
Isso copia a midia para os servidores do Metricool e devolve uma nova
URL — e essa URL (nao a URL original do R2) que deve entrar no array
`media` do payload de `/v2/scheduler/posts`. Sem esse passo, o Metricool
pode falhar ao tentar baixar a imagem da nossa URL R2 no momento de
publicar. Implementado em `normalize_media_url()` abaixo.

AINDA NAO CONFIRMADO (best-effort — reveja antes de ir para producao real):
os nomes exatos dos campos de resposta do POST /v2/scheduler/posts (aqui
assumimos `id`, `uuid`, `previewUrl`/`url`) nao foram verificados contra
um payload de resposta real; confirme com uma chamada de teste
(`draft: true`) e ajuste `schedule_posts()`/`to_scheduled_state()` se os
nomes de campo vierem diferentes.

Fontes: https://static.metricool.com/API+DOC/API+English.pdf ·
https://help.metricool.com/en/article/basic-guide-for-api-integration-abukgf/
Em dry-run, nenhuma chamada de rede e feita: o payload e apenas
impresso/retornado.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("agente.publisher")

METRICOOL_API_BASE = "https://app.metricool.com/api"
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
TIMEZONE = "America/Sao_Paulo"


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def build_linkedin_payload(texto: str, publicar_em: str) -> dict:
    """Contrato da secao 7.1 da especificacao (LinkedIn, texto, publica
    sozinho), com `creationDate` e `saveExternalMediaFiles` adicionados —
    presentes no exemplo oficial de payload da doc do Metricool mas
    ausentes do exemplo (mais enxuto) da especificacao. Incluir esses
    campos extras nao deve quebrar nada; remova-os se o Metricool
    reclamar em teste real."""
    return {
        "autoPublish": True, "draft": False, "descendants": [], "firstCommentText": "",
        "hasNotReadNotes": False, "media": [], "mediaAltText": [],
        "providers": [{"network": "linkedin"}],
        "publicationDate": {"dateTime": publicar_em, "timezone": TIMEZONE},
        "creationDate": {"dateTime": _now_iso(), "timezone": TIMEZONE},
        "saveExternalMediaFiles": False,
        "shortener": False, "smartLinkData": {"ids": []},
        "text": texto,
        "linkedinData": {"previewIncluded": True, "type": "POST"},
    }


def build_combined_payload(texto_ou_legenda: str, media_urls: list, publicar_em: str) -> dict:
    """Payload PADRAO ATUAL (cadencia 2x/dia, 08h/19h): um unico post do
    Metricool publicado SIMULTANEAMENTE em Instagram e LinkedIn — mesma
    imagem, mesmo texto — via `providers: [{"network":"instagram"},
    {"network":"linkedin"}]`. Este e o formato CONFIRMADO como o que esta
    realmente em uso na fila viva do Metricool (ver nota de auditoria da
    fila, tarefa #35), substituindo os payloads separados
    build_linkedin_payload()/build_instagram_payload() abaixo — mantidos
    apenas como referencia do contrato original de secoes 7.1/7.2 da
    especificacao, caso um dia seja necessario voltar a publicar por
    canal separado."""
    return {
        "autoPublish": True, "draft": False,
        "media": list(media_urls),
        "mediaAltText": ["" for _ in media_urls],
        "providers": [{"network": "instagram"}, {"network": "linkedin"}],
        "publicationDate": {"dateTime": publicar_em, "timezone": TIMEZONE},
        "creationDate": {"dateTime": _now_iso(), "timezone": TIMEZONE},
        "saveExternalMediaFiles": False,
        "text": texto_ou_legenda,
        "instagramData": {"type": "POST", "autoPublish": True},
        "linkedinData": {"previewIncluded": True, "type": "POST"},
        "descendants": [], "firstCommentText": "", "hasNotReadNotes": False,
        "shortener": False, "smartLinkData": {"ids": []},
    }


def build_instagram_payload(media_urls: list, legenda: str, publicar_em: str) -> dict:
    """Contrato da secao 7.2 da especificacao (Instagram, carrossel/card
    com URLs publicas), com `creationDate`/`saveExternalMediaFiles`
    adicionados pelo mesmo motivo do LinkedIn acima. IMPORTANTE:
    `media_urls` aqui devem ser as URLs JA NORMALIZADAS pelo Metricool
    (ver `normalize_media_url()`), nao as URLs originais do R2 — chame
    `normalize_media_urls()` antes de montar este payload em producao."""
    return {
        "autoPublish": True, "draft": False,
        "media": list(media_urls),
        "mediaAltText": ["" for _ in media_urls],
        "providers": [{"network": "instagram"}],
        "publicationDate": {"dateTime": publicar_em, "timezone": TIMEZONE},
        "creationDate": {"dateTime": _now_iso(), "timezone": TIMEZONE},
        "saveExternalMediaFiles": False,
        "text": legenda,
        "instagramData": {"type": "POST", "autoPublish": True},
        "descendants": [], "firstCommentText": "", "hasNotReadNotes": False,
        "shortener": False, "smartLinkData": {"ids": []},
    }


def _auth_headers() -> dict:
    """CONFIRMADO contra a doc oficial: o token vai no header X-Mc-Auth."""
    return {"X-Mc-Auth": os.environ.get("METRICOOL_USER_TOKEN", "")}


def _auth_query_params() -> dict:
    """CONFIRMADO contra a doc oficial: userId e blogId vao como query
    params em toda chamada (nao o userToken, que vai no header)."""
    return {
        "userId": os.environ.get("METRICOOL_USER_ID", ""),
        "blogId": os.environ.get("METRICOOL_BLOG_ID", ""),
    }


def normalize_media_url(media_url: str) -> Optional[str]:
    """PASSO CONFIRMADO na doc oficial, ausente da especificacao original:
    antes de referenciar uma URL de midia externa (nosso caso: PNG no R2)
    num post, e preciso chamar
    GET /api/actions/normalize/image/url?url=<media_url>&blogId&userId
    Isso copia a midia para os servidores do Metricool; a resposta traz a
    URL definitiva a usar no array `media` do payload de agendamento.
    Retorna None em caso de falha (o chamador decide como tratar)."""
    endpoint = f"{METRICOOL_API_BASE}/actions/normalize/image/url"
    params = {**_auth_query_params(), "url": media_url}
    resp = _request_with_retry("GET", endpoint, headers=_auth_headers(), params=params)
    if resp is None:
        return None
    try:
        data = resp.json()
    except ValueError:
        logger.warning("Resposta de normalize/image/url nao e JSON valido para %s", media_url)
        return None
    # Nome exato do campo de retorno NAO confirmado contra um payload real
    # — tentamos as chaves mais prováveis antes de desistir.
    return data.get("url") or data.get("normalizedUrl") or data.get("mediaUrl")


def normalize_media_urls(media_urls: list) -> list:
    """Normaliza uma lista de URLs de midia; em caso de falha para uma
    URL individual, mantem a URL original (best-effort) e loga aviso."""
    normalizadas = []
    for url in media_urls:
        nova = normalize_media_url(url)
        if nova:
            normalizadas.append(nova)
        else:
            logger.warning(
                "Nao foi possivel normalizar %s no Metricool — usando URL "
                "original do R2 (pode falhar no agendamento real).", url,
            )
            normalizadas.append(url)
    return normalizadas


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


def _post_with_retry(url: str, payload: dict, params: dict) -> Optional[dict]:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url, params=params, json=payload, headers=_auth_headers(),
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("Falha ao agendar no Metricool (tentativa %d/%d): %s",
                            attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    logger.error("Todas as tentativas de agendamento falharam: %s", last_exc)
    return None


def _build_payload_for_peca(peca: dict, media_urls: list) -> Optional[dict]:
    """PADRAO ATUAL: toda peca (canal='instagram', formato card/carrossel)
    e publicada em duplo-canal (Instagram + LinkedIn) no mesmo post via
    build_combined_payload() — ver docstring dessa funcao. Os ramos
    'linkedin' e 'instagram'-only abaixo sao mantidos apenas por
    compatibilidade com lotes antigos (pre-cadencia 2x/dia) que ainda
    tenham peca com canal='linkedin' ou sem campo 'legenda'."""
    if peca["canal"] == "linkedin":
        return build_linkedin_payload(peca["texto"], peca["publicar_em"])
    if peca["canal"] == "instagram":
        texto = peca.get("legenda") or peca.get("texto", "")
        return build_combined_payload(texto, media_urls, peca["publicar_em"])
    logger.warning("Peca %s com canal desconhecido: %s", peca.get("id"), peca.get("canal"))
    return None


def schedule_posts(lote: dict, media_por_peca: dict, dry_run: bool = False,
                    draft: bool = False) -> dict:
    """Agenda cada peca do lote no Metricool. Retorna
    {id_peca: {"payload": ..., "resultado": {...} | None, "status": str}}.

    - dry_run=True: NAO faz chamada real, apenas imprime/retorna o payload
      que seria enviado.
    - draft=True: agenda com draft:true (usado no teste de criterio de
      aceite #2, para nao publicar de verdade durante validacao).
    Falha de UMA peca nao aborta o lote inteiro."""
    resultado_geral = {}
    params = _auth_query_params()

    for peca in lote.get("pecas", []):
        peca_id = peca.get("id", "desconhecida")
        media_urls = media_por_peca.get(peca_id, [])

        if media_urls and peca.get("canal") == "instagram" and not dry_run:
            # Passo confirmado na doc oficial (normalize/image/url) —
            # ver docstring de normalize_media_url(). So roda fora de
            # dry-run porque exige credenciais reais e chamada de rede.
            media_urls = normalize_media_urls(media_urls)

        payload = _build_payload_for_peca(peca, media_urls)

        if payload is None:
            resultado_geral[peca_id] = {"payload": None, "resultado": None, "status": "erro_payload"}
            continue

        if draft:
            payload = dict(payload)
            payload["draft"] = True

        if dry_run:
            print(f"\n[DRY-RUN] Payload que seria enviado ao Metricool para peca '{peca_id}':")
            print(payload)
            resultado_geral[peca_id] = {"payload": payload, "resultado": None, "status": "dry_run"}
            continue

        endpoint = f"{METRICOOL_API_BASE}/v2/scheduler/posts"
        resposta = _post_with_retry(endpoint, payload, params)

        if resposta is None:
            resultado_geral[peca_id] = {"payload": payload, "resultado": None, "status": "falha"}
            logger.error("Falha ao agendar peca %s — pulando (lote segue).", peca_id)
            continue

        resultado_geral[peca_id] = {
            "payload": payload,
            "resultado": resposta,
            "status": "agendado",
            "metricool_id": resposta.get("id"),
            "uuid": resposta.get("uuid"),
            "url_planner": resposta.get("previewUrl") or resposta.get("url"),
        }

    return resultado_geral


def to_scheduled_state(resultado_geral: dict) -> dict:
    """Converte o retorno de schedule_posts() no formato persistido em
    state/scheduled.json: {id_peca: {metricool_id, uuid, url_planner}}."""
    scheduled = {}
    for peca_id, info in resultado_geral.items():
        if info.get("status") != "agendado":
            continue
        scheduled[peca_id] = {
            "metricool_id": info.get("metricool_id"),
            "uuid": info.get("uuid"),
            "url_planner": info.get("url_planner"),
        }
    return scheduled
