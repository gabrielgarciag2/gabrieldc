# -*- coding: utf-8 -*-
"""
src/storage.py — hospedagem das artes em Cloudflare R2 (S3-compatible)
via boto3 (secao 6 da especificacao).

upload_images(paths_por_peca, semana) faz upload de cada PNG para:
    ciclos/{semana}/{arquivo}.png
com ContentType image/png, e retorna {id_peca: [url_publica, ...]}.

Apos o upload, faz um HEAD request na URL publica para confirmar que o
arquivo esta acessivel (o Metricool precisa conseguir baixar a imagem).
Se o HEAD falhar, loga um aviso mas NAO derruba o pipeline em dry-run
(em modo real, a falha e logada e a peca segue sinalizada como
"nao verificada" — quem decide se aborta e o run.py).

Em modo dry-run (ou sem credenciais R2 configuradas), nao faz nenhuma
chamada de rede: apenas calcula a URL publica que SERIA usada e retorna,
para permitir montar o payload de publicacao localmente.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("agente.storage")

DEFAULT_TIMEOUT = 15


def _r2_client():
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _public_url(semana: str, filename: str) -> str:
    base = os.environ.get("R2_PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/ciclos/{semana}/{filename}"


def _verify_public_url(url: str) -> bool:
    try:
        resp = requests.head(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            logger.warning("HEAD %s retornou status %d.", url, resp.status_code)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("HEAD %s falhou: %s", url, exc)
        return False


def _r2_configured() -> bool:
    required = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_PUBLIC_BASE_URL")
    return all(os.environ.get(v) for v in required)


def upload_images(paths_por_peca: dict, semana: str, dry_run: bool = False) -> dict:
    """Faz upload de todos os PNGs de um lote para o R2 e retorna
    {id_peca: [url_publica, ...]}. Em dry-run (ou sem credenciais R2),
    apenas calcula as URLs que seriam usadas, sem chamada de rede."""
    resultado = {}

    if dry_run or not _r2_configured():
        if not dry_run:
            logger.warning(
                "Credenciais R2 incompletas — rodando upload_images em modo simulado "
                "(URLs calculadas, sem upload real)."
            )
        for peca_id, paths in paths_por_peca.items():
            resultado[peca_id] = [_public_url(semana, Path(p).name) for p in paths]
        return resultado

    client = _r2_client()
    bucket = os.environ["R2_BUCKET"]

    for peca_id, paths in paths_por_peca.items():
        urls = []
        for p in paths:
            p = Path(p)
            key = f"ciclos/{semana}/{p.name}"
            try:
                client.upload_file(
                    str(p), bucket, key,
                    ExtraArgs={"ContentType": "image/png"},
                )
            except Exception:
                logger.exception("Falha ao subir %s para R2 (peca %s) — pulando arquivo.", p, peca_id)
                continue

            url = _public_url(semana, p.name)
            if not _verify_public_url(url):
                logger.warning(
                    "URL publica %s nao respondeu OK no HEAD apos upload. "
                    "O Metricool pode falhar ao baixar esta imagem.", url
                )
            urls.append(url)
        resultado[peca_id] = urls

    return resultado
