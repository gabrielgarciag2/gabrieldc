# -*- coding: utf-8 -*-
"""
src/reporter.py — Relatorio semanal por e-mail (Resend), secao 8 da
especificacao.

send_report() monta e envia um e-mail com:
  - pecas agendadas nesta semana (data + titulo/resumo + link do planner)
  - metricas do ciclo anterior
  - avisos gerados pelo validador (pecas reprovadas/regeneradas)
  - reels com midia pendente de gravacao manual (roteiro completo: gancho,
    beats, direcao de cena, legenda) — nunca sao auto-publicados pelo
    publisher.py (ver guarda em schedule_posts()), entao esta secao e a
    unica lista de "o que gravar essa semana" que existe no fluxo

Assunto: "Agente de Conteúdo · semana {data} · {n} peças no ar"

Fallback silencioso: se RESEND_API_KEY nao estiver configurada, loga e
segue sem quebrar o pipeline (nem em dry-run, nem em producao — falha de
e-mail nunca deve derrubar o resto do ciclo).
"""
from __future__ import annotations

import logging
import os
import traceback
from typing import Optional

logger = logging.getLogger("agente.reporter")


def _resend_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY")) and bool(os.environ.get("REPORT_EMAIL"))


def _peca_titulo(peca: dict) -> str:
    if peca.get("canal") == "linkedin":
        texto = peca.get("texto", "")
        return (texto[:80] + "…") if len(texto) > 80 else texto
    if peca.get("formato") == "carrossel":
        for slide in peca.get("slides", []):
            if slide.get("tipo") == "capa":
                return slide.get("titulo", peca.get("id", ""))
        return peca.get("id", "")
    if peca.get("formato") == "card":
        return peca.get("frase", peca.get("id", ""))
    if peca.get("formato") == "reel":
        roteiro = peca.get("roteiro") or {}
        return roteiro.get("gancho_visual") or peca.get("linha", peca.get("id", ""))
    return peca.get("id", "")


def _build_reel_html(reel: dict) -> str:
    roteiro = reel.get("roteiro") or {}
    direcao = roteiro.get("direcao_cena") or {}
    beats = roteiro.get("beats") or []

    linhas_beats = "".join(
        f"<tr><td>{b.get('tempo', '')}</td><td>{b.get('fala', '')}</td>"
        f"<td>{b.get('texto_tela', '')}</td></tr>"
        for b in beats
    ) or "<tr><td colspan='3'>(sem beats)</td></tr>"

    return f"""
    <li style="margin-bottom:18px;">
      <strong>{reel.get('publicar_em', '')}</strong> — {reel.get('linha', '')}
      <br/><em>{roteiro.get('gancho_visual', '')}</em>
      ({roteiro.get('duracao_alvo_seg', '?')}s)
      <table border="1" cellpadding="6" cellspacing="0" style="margin-top:6px;border-collapse:collapse;">
        <tr><th>tempo</th><th>fala</th><th>texto na tela</th></tr>
        {linhas_beats}
      </table>
      <ul>
        <li>fundo: {direcao.get('fundo', '')}</li>
        <li>ambiente: {direcao.get('ambiente', '')}</li>
        <li>enquadramento: {direcao.get('enquadramento', '')}</li>
        <li>velocidade de fala: {direcao.get('velocidade_fala', '')}</li>
        <li>expressao: {direcao.get('expressao', '')}</li>
      </ul>
      <small>legenda: {reel.get('legenda', '')}</small>
    </li>
    """


def _build_html(lote: dict, resultado_publicacao: dict, metrics: dict, avisos_validador: list,
                 reels_pendentes: Optional[list] = None) -> str:
    n = len(lote.get("pecas", []))
    semana = lote.get("semana", "")

    linhas_pecas = []
    for peca in lote.get("pecas", []):
        info = resultado_publicacao.get(peca.get("id"), {})
        url = info.get("url_planner") or "(sem link — dry-run ou falha de agendamento)"
        linhas_pecas.append(
            f"<li><strong>{peca.get('publicar_em', '')}</strong> — "
            f"[{peca.get('canal')}/{peca.get('formato')}] "
            f"{_peca_titulo(peca)}<br/>"
            f"<small>linha editorial: {peca.get('linha', '')} · status: {info.get('status', 'desconhecido')} "
            f"· {url}</small></li>"
        )

    linhas_metricas = f"""
        <li>Alcance total (ciclo anterior): {metrics.get('alcance_total')}</li>
        <li>Interações totais (ciclo anterior): {metrics.get('interacoes_total')}</li>
        <li>Seguidores: {metrics.get('seguidores')}</li>
        <li>Fonte dos dados: {metrics.get('fonte')}</li>
    """

    linhas_avisos = "".join(f"<li>{a}</li>" for a in avisos_validador) or "<li>Nenhum aviso.</li>"

    reels_pendentes = reels_pendentes or []
    if reels_pendentes:
        bloco_reels = f"""
    <h3>🎥 Reels pendentes de gravação ({len(reels_pendentes)})</h3>
    <p><small>Estes NÃO foram enviados ao Metricool — grave o vídeo seguindo o roteiro
    abaixo e suba manualmente antes do horário de publicação.</small></p>
    <ul>{''.join(_build_reel_html(r) for r in reels_pendentes)}</ul>
    """
    else:
        bloco_reels = ""

    return f"""
    <h2>Agente de Conteúdo · semana {semana} · {n} peças no ar</h2>
    <h3>Peças agendadas</h3>
    <ul>{''.join(linhas_pecas)}</ul>
    {bloco_reels}
    <h3>Métricas do ciclo anterior</h3>
    <ul>{linhas_metricas}</ul>
    <h3>Avisos do validador</h3>
    <ul>{linhas_avisos}</ul>
    <p><small>Este e-mail e gerado automaticamente pelo pipeline agente-conteudo-dcvtq.
    Kill switch: defina KILL_SWITCH=true nos secrets do GitHub para pausar o agente a qualquer momento.</small></p>
    """


def send_report(lote: dict, resultado_publicacao: dict, metrics: dict,
                 avisos_validador: Optional[list] = None,
                 reels_pendentes: Optional[list] = None) -> bool:
    """Envia o relatorio semanal por e-mail via Resend. Retorna True se
    enviado com sucesso, False em qualquer outra situacao (sem
    credenciais, erro de rede etc — nunca levanta excecao para o
    chamador)."""
    avisos_validador = avisos_validador or []
    n = len(lote.get("pecas", []))
    semana = lote.get("semana", "")
    assunto = f"Agente de Conteúdo · semana {semana} · {n} peças no ar"

    if not _resend_configured():
        logger.warning(
            "RESEND_API_KEY ou REPORT_EMAIL nao configurados — relatorio NAO enviado "
            "(fallback silencioso). Assunto que seria usado: '%s'", assunto
        )
        return False

    try:
        import resend

        resend.api_key = os.environ["RESEND_API_KEY"]
        html = _build_html(lote, resultado_publicacao, metrics, avisos_validador, reels_pendentes)
        resend.Emails.send({
            "from": os.environ.get("REPORT_FROM_EMAIL", "onboarding@resend.dev"),
            "to": [os.environ["REPORT_EMAIL"]],
            "subject": assunto,
            "html": html,
        })
        logger.info("Relatorio semanal enviado para %s.", os.environ["REPORT_EMAIL"])
        return True
    except Exception:
        logger.error("Falha ao enviar relatorio via Resend (fallback silencioso):\n%s",
                      traceback.format_exc())
        return False


def send_alert(assunto: str, mensagem: str) -> bool:
    """Envia um e-mail de alerta best-effort (ex: falha total do lote).
    Nunca levanta excecao — se Resend nao estiver configurado, apenas
    loga e retorna False."""
    if not _resend_configured():
        logger.error("ALERTA (Resend nao configurado, apenas log): %s\n%s", assunto, mensagem)
        return False
    try:
        import resend

        resend.api_key = os.environ["RESEND_API_KEY"]
        resend.Emails.send({
            "from": os.environ.get("REPORT_FROM_EMAIL", "onboarding@resend.dev"),
            "to": [os.environ["REPORT_EMAIL"]],
            "subject": f"[ALERTA] {assunto}",
            "html": f"<pre>{mensagem}</pre>",
        })
        return True
    except Exception:
        logger.error("Falha ao enviar e-mail de alerta (fallback silencioso):\n%s",
                      traceback.format_exc())
        return False
