# -*- coding: utf-8 -*-
"""
src/generator.py — "Cerebro" do agente: chama a API do Claude para gerar
o lote semanal de conteudo.

- Usa o SDK oficial `anthropic`.
- Modelo default: claude-sonnet-4-6 (configuravel via env var CLAUDE_MODEL —
  confira o nome exato/disponibilidade em
  https://docs.claude.com/en/docs/about-claude/models antes de producao).
- system = Prompt do Agente (copiado literalmente da secao 3 do Playbook).
- user = JSON com metricas da semana anterior, temas dos ultimos 45 dias e
  datas-alvo da semana.
- Resposta parseada como JSON estrito, com fallback de strip de cercas
  ```json ... ```.
- Se ANTHROPIC_API_KEY nao estiver setada, cai em MODO MOCK: gera um lote
  de exemplo localmente (sem chamada de rede), permitindo `--dry-run` sem
  nenhuma credencial. Isso e intencional para o teste do build.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta

logger = logging.getLogger("agente.generator")

DEFAULT_MODEL = "claude-sonnet-4-6"

# ============================================================================
# PROMPT DO AGENTE — copiado literalmente da secao 3 do
# Agente_de_Conteudo_Playbook.md (Playbook v2). NAO EDITAR sem atualizar o
# Playbook em paralelo — este texto e a "constituicao editorial" do agente.
# ============================================================================
SYSTEM_PROMPT = """Você é o Agente de Conteúdo de Gabriel Garcia (@gabrielgarciadc), consultor de gestão e CEO da Dale Carnegie Vale do Taquari (Lajeado/RS). Você opera de forma totalmente autônoma: nenhum humano revisará sua saída antes da publicação. Por isso, siga as regras abaixo como leis absolutas.

MISSÃO: construir, via LinkedIn e Instagram, a posição de referência em gestão empresarial para PMEs do interior do RS (Vale do Taquari), gerando autoridade e conversas comerciais qualificadas via DIRECT.

LEIS ABSOLUTAS (violação = falha crítica):
1. NUNCA use dados reais de clientes: nenhum número, nome, setor+cidade combinados ou detalhe que permita identificação, mesmo anonimizado. Todo caso é padrão de mercado ou cenário composto ("o padrão que encontro é...", "já vi operação perder...").
2. NUNCA produza conteúdo motivacional genérico, promessa de enriquecimento, crítica nominal a pessoas, empresas ou entidades, opinião política/religiosa, ou qualquer afirmação factual sobre terceiros que você não possa sustentar.
3. NUNCA invente estatísticas. Dados de mercado só com fonte pública verificável; na dúvida, use formulação qualitativa.
4. Tom: direto, experiente, pé no chão de fábrica, português do RS ("tu/teu" no Instagram, neutro no LinkedIn). Zero jargão de coach.
5. Toda peça pertence a uma das 5 linhas: Mentoria com o Especialista, Framework Próprio, Dilema de Sócio, Liderança (Dale Carnegie), Tese Regional.
6. CTAs rotativos com palavra-chave de DIRECT (DIAGNÓSTICO, MAPA, VAZAMENTO, EXPANSÃO) em no máximo 40% das peças; o restante encerra com pergunta de engajamento ou instrução de salvar/compartilhar.

ENTRADA: métricas da semana anterior (JSON do Metricool) + histórico de temas já publicados (não repetir tema em 45 dias).

SAÍDA: JSON estrito com o lote da semana:
- 3 posts LinkedIn (ter/qui/sex 08h): texto completo, 900-1400 caracteres, gancho forte na 1ª linha, 3-4 hashtags.
- 3 carrosséis IG (seg/qua/sex 11h30): 6-8 slides cada, com kicker, titulo, corpo por slide (títulos ≤ 60 caracteres, corpo ≤ 220), + legenda completa com hashtags.
- 2 cards IG (ter/sáb 07h30): 1 frase de impacto ≤ 90 caracteres + legenda.
- Para cada peça: linha editorial, data/hora, e campo racional (1 frase: por que este tema agora, com base nas métricas).

AUTOAVALIAÇÃO OBRIGATÓRIA: antes de emitir a saída, verifique cada peça contra as Leis 1-3. Se qualquer peça falhar, reescreva-a. Emita apenas JSON válido."""


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _proximas_datas_uteis(hoje: datetime) -> dict:
    """Calcula as datas-alvo da proxima semana (segunda a sabado) a partir
    de `hoje`, seguindo a cadencia da secao 4 do Playbook."""
    dias_ate_segunda = (7 - hoje.weekday()) % 7
    dias_ate_segunda = dias_ate_segunda or 7
    proxima_segunda = hoje + timedelta(days=dias_ate_segunda)
    dias = {}
    nomes = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    for i, nome in enumerate(nomes):
        dias[nome] = (proxima_segunda + timedelta(days=i)).strftime("%Y-%m-%d")
    return dias


def _build_user_payload(metrics: dict, temas_recentes: list, hoje: datetime = None) -> dict:
    hoje = hoje or datetime.now()
    datas = _proximas_datas_uteis(hoje)
    return {
        "metricas_semana_anterior": metrics,
        "temas_ultimos_45_dias": temas_recentes,
        "datas_alvo_semana": {
            "carrossel_seg_11h30": f"{datas['segunda']}T11:30:00",
            "card_ter_07h30": f"{datas['terca']}T07:30:00",
            "linkedin_ter_08h": f"{datas['terca']}T08:00:00",
            "carrossel_qua_11h30": f"{datas['quarta']}T11:30:00",
            "linkedin_qui_08h": f"{datas['quinta']}T08:00:00",
            "linkedin_sex_08h": f"{datas['sexta']}T08:00:00",
            "carrossel_sex_11h30": f"{datas['sexta']}T11:30:00",
            "card_sab_07h30": f"{datas['sabado']}T07:30:00",
        },
        "semana": datas["segunda"],
    }


def _mock_batch(user_payload: dict) -> dict:
    """Lote de exemplo gerado localmente, sem chamada de rede, usado
    quando ANTHROPIC_API_KEY nao esta configurada (modo mock). Cobre os
    3 formatos do contrato (linkedin/carrossel/card) para permitir teste
    completo de renderizacao/validacao/dry-run."""
    datas = user_payload["datas_alvo_semana"]
    semana = user_payload["semana"]
    logger.warning(
        "ANTHROPIC_API_KEY nao configurada — usando MODO MOCK do generator "
        "(lote de exemplo gerado localmente, sem chamada a API do Claude)."
    )
    return {
        "semana": semana,
        "pecas": [
            {
                "id": "li-1",
                "canal": "linkedin",
                "formato": "texto",
                "linha": "Framework Próprio",
                "publicar_em": datas["linkedin_ter_08h"],
                "texto": (
                    "Você é dono da empresa ou é o funcionário mais caro dela? "
                    "Essa pergunta incomoda, mas vale a pena responder com a agenda na mão.\n\n"
                    "A Regra 70/30 é simples de enunciar e difícil de aplicar: 70% do tempo do "
                    "dono deveria estar em decisões que só o dono pode tomar — estratégia, "
                    "pessoas-chave, grandes clientes, estrutura. No máximo 30% em operação do "
                    "dia a dia.\n\n"
                    "Na maioria das empresas que acompanho, essa proporção está invertida. O "
                    "dono aprova nota fiscal, resolve reclamação de cliente pequeno, apaga "
                    "incêndio operacional — e a estratégia vai ficando pra quando sobrar tempo. "
                    "Só que nunca sobra.\n\n"
                    "O teste é rápido: pegue a agenda da última semana e classifique cada bloco "
                    "de tempo como DONO ou OPERADOR. O número que aparecer não mente, e "
                    "geralmente é desconfortável.\n\n"
                    "Virar esse jogo passa por três frentes: delegação estruturada com padrão "
                    "de entrega definido (não apenas confiança), rituais de gestão que rodam "
                    "sem a presença do fundador, e um segundo nível de liderança preparado para "
                    "decidir — não só para executar.\n\n"
                    "Nenhuma dessas três coisas acontece sozinha. Elas são construídas, com "
                    "método, ao longo de meses — não em uma reunião de planejamento de fim de "
                    "ano.\n\n"
                    "Qual foi a proporção da sua última semana?"
                    "\n\n#gestao #lideranca #empresafamiliar #consultoria"
                ),
                "racional": (
                    "Peca de exemplo do modo mock (sem ANTHROPIC_API_KEY) — cobre o formato "
                    "linkedin/texto do contrato para teste de dry-run."
                ),
            },
            {
                "id": "ig-c1",
                "canal": "instagram",
                "formato": "carrossel",
                "linha": "Mentoria com o Especialista",
                "publicar_em": datas["carrossel_seg_11h30"],
                "slides": [
                    {
                        "tipo": "capa",
                        "kicker": "MENTORIA COM O ESPECIALISTA",
                        "titulo": "O vazamento de margem que ninguém está olhando",
                        "subtitulo": None,
                    },
                    {
                        "tipo": "conteudo",
                        "numero": "1",
                        "titulo": "O sintoma",
                        "corpo": (
                            "A empresa fatura mais que no ano passado, mas a margem não "
                            "acompanhou. E ninguém consegue explicar exatamente por quê."
                        ),
                    },
                    {
                        "tipo": "conteudo",
                        "numero": "2",
                        "titulo": "Onde costuma estar",
                        "corpo": (
                            "Devolução por erro interno, retrabalho entre áreas, estoque "
                            "parado. Não aparece como linha isolada — aparece diluído."
                        ),
                    },
                    {
                        "tipo": "conteudo",
                        "numero": "3",
                        "titulo": "Por que passa despercebido",
                        "corpo": (
                            "Cada área olha só o próprio indicador. O vazamento vive "
                            "exatamente na costura entre elas, que ninguém audita."
                        ),
                    },
                    {
                        "tipo": "conteudo",
                        "numero": "4",
                        "titulo": "Como eu encontro isso",
                        "corpo": (
                            "Separando causa raiz por tipo, com dono e medição semanal. "
                            "O número vira visível — e visível, ele para de sangrar."
                        ),
                    },
                    {
                        "tipo": "cta",
                        "titulo": "Sua margem tem um vazamento assim?",
                        "corpo": "Salva este carrossel e revisa teu indicador de margem esta semana.",
                    },
                ],
                "legenda": (
                    "Faturamento sobe, margem não acompanha, e ninguém sabe exatamente por "
                    "quê. Esse é um dos padrões mais comuns que encontro em empresas do "
                    "interior que cresceram rápido.\n\n"
                    "Desliza pra entender onde esse vazamento costuma se esconder — e como eu "
                    "encontro esse número na prática.\n\n"
                    "👉 Salva este post pra revisar teu indicador de margem esta semana.\n\n"
                    "#gestao #consultoriaempresarial #valedotaquari #lajeado #pme"
                ),
            },
            {
                "id": "ig-card1",
                "canal": "instagram",
                "formato": "card",
                "linha": "Tese Regional",
                "publicar_em": datas["card_ter_07h30"],
                "frase": "O interior do RS é uma potência empresarial invisível.",
                "legenda": (
                    "Tem empresa no Vale do Taquari crescendo em ritmo de dois dígitos, e "
                    "você nunca ouviu falar dela. O interior gaúcho tem uma força empresarial "
                    "que raramente aparece no radar de fora.\n\n"
                    "👉 Marca um empresário da região nos comentários.\n\n"
                    "#valedotaquari #lajeado #interiorgaucho #empreendedorismo #rs"
                ),
            },
        ],
    }


def generate_batch(metrics: dict, temas_recentes: list, hoje: datetime = None) -> dict:
    """Gera o lote semanal via API do Claude (ou modo mock). Retorna o
    dict do contrato de saida (secao 4.1 da especificacao)."""
    user_payload = _build_user_payload(metrics, temas_recentes, hoje)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return _mock_batch(user_payload)

    try:
        import anthropic
    except ImportError:
        logger.error("SDK 'anthropic' nao instalado. Rode: pip install anthropic. Usando modo mock.")
        return _mock_batch(user_payload)

    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=api_key)

    max_retries = 3
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                temperature=0.7,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Gere o lote semanal seguindo estritamente o contrato JSON abaixo. "
                            "Responda APENAS com o JSON, sem texto adicional.\n\n"
                            f"{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
                        ),
                    }
                ],
            )
            raw_text = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
            cleaned = _strip_code_fences(raw_text)
            lote = json.loads(cleaned)
            return lote
        except json.JSONDecodeError as exc:
            last_exc = exc
            logger.error("Resposta do Claude nao e JSON valido (tentativa %d/%d): %s",
                          attempt, max_retries, exc)
        except Exception as exc:  # erros de rede/API
            last_exc = exc
            logger.error("Falha ao chamar API do Claude (tentativa %d/%d): %s",
                          attempt, max_retries, exc)
        if attempt < max_retries:
            time.sleep(2 ** attempt)

    logger.error("Todas as tentativas de geracao via Claude API falharam (%s). "
                 "Caindo para modo mock para nao interromper o pipeline.", last_exc)
    return _mock_batch(user_payload)
