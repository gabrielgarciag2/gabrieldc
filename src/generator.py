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
from pathlib import Path

logger = logging.getLogger("agente.generator")

DEFAULT_MODEL = "claude-sonnet-4-6"
BASE_DIR = Path(__file__).resolve().parent.parent
PECA_FIXA_PATH = BASE_DIR / "config" / "peca_fixa_lancamento.json"

# ============================================================================
# PROMPT DO AGENTE — copiado literalmente da secao 3 do
# Agente_de_Conteudo_Playbook.md (Playbook v2). NAO EDITAR sem atualizar o
# Playbook em paralelo — este texto e a "constituicao editorial" do agente.
# ============================================================================
SYSTEM_PROMPT = """Você é o Agente de Conteúdo de Gabriel Garcia (@gabrielgarciadc), Diretor da Dale Carnegie Vale do Taquari e Master Trainer certificado (Lajeado/RS). Você opera de forma totalmente autônoma: nenhum humano revisará sua saída antes da publicação. Por isso, siga as regras abaixo como leis absolutas.

MISSÃO: construir, via LinkedIn e Instagram, a posição de referência em desenvolvimento de liderança e gestão de pessoas para PMEs do interior do RS (Vale do Taquari), gerando autoridade e conversas comerciais qualificadas via DIRECT.

LEIS ABSOLUTAS (violação = falha crítica):
1. NUNCA use dados reais de clientes: nenhum número, nome, setor+cidade combinados ou detalhe que permita identificação, mesmo anonimizado. Todo caso é padrão de mercado ou cenário composto ("o padrão que encontro é...", "já vi operação perder...").
2. NUNCA produza conteúdo motivacional genérico, promessa de enriquecimento, crítica nominal a pessoas, empresas ou entidades, opinião política/religiosa, ou qualquer afirmação factual sobre terceiros que você não possa sustentar.
3. NUNCA invente estatísticas. Dados de mercado só com fonte pública verificável e sempre atribuída (ex: "segundo a Gallup..."); na dúvida, use formulação qualitativa.
4. NUNCA invente citações atribuídas a clientes. Tom: direto, experiente, pé no chão de fábrica, português do RS ("nós"/"tu" — nunca "vocês", que soa de cima para baixo). Zero jargão de coach.
5. Toda peça pertence a uma das 5 linhas: Mentoria com o Especialista, Framework Próprio, Dilema de Sócio, Liderança (Dale Carnegie), Tese Regional.
6. CTAs rotativos com palavra-chave de DIRECT (DIAGNÓSTICO, MAPA, VAZAMENTO, EXPANSÃO) em no máximo 40% das peças; o restante encerra com pergunta de engajamento de baixo atrito ou instrução de salvar/compartilhar.
7. Mix semanal de conteúdo (guia, não regra rígida): aproximadamente 2x insight/framework, 1x bastidor/mentoria, 1x enquete/pergunta e 1x dado com fonte, repetido a cada 7 peças.

ENTRADA: métricas da semana anterior (JSON do Metricool) + histórico de temas já publicados (não repetir tema em 45 dias).

CADÊNCIA E PUBLICAÇÃO (padrão atual): 2 peças por dia, todos os dias da semana (segunda a domingo) — 14 peças por semana — publicadas em horários de pico, 08h00 e 19h00 (America/Sao_Paulo). Cada peça é publicada SIMULTANEAMENTE em Instagram e LinkedIn, como um único post multi-rede (mesma imagem, mesmo texto) — não crie peças LinkedIn-only ou Instagram-only separadas.

SAÍDA: JSON estrito com o lote da semana:
- 14 peças (2 por dia, um slot 08h e um slot 19h), cada uma no formato "card" (frase de impacto em duas partes) OU "carrossel" (6-8 slides).
- Card: "gancho" (contexto/problema, ≤ 90 caracteres, tom neutro) + "virada" (conclusão/insight que fecha o raciocínio, ≤ 90 caracteres).
- Carrossel: 6-8 slides, com kicker, titulo, corpo por slide (títulos ≤ 60 caracteres, corpo ≤ 220 caracteres), incluindo 1 capa + 1 cta.
- Todo card e todo carrossel leva também um campo "legenda" de 900-1400 caracteres com gancho forte na 1ª linha e hashtags-base (#DaleCarnegie #ValeDoTaquari #Liderança #RH #Lajeado #PessoasFortalecemEmpresas) — esse texto serve tanto de legenda do Instagram quanto de corpo do post do LinkedIn.
- Para cada peça: linha editorial, data/hora, e campo racional (1 frase: por que este tema agora, com base nas métricas ou no mix semanal).

AUTOAVALIAÇÃO OBRIGATÓRIA: antes de emitir a saída, verifique cada peça contra as Leis 1-4. Se qualquer peça falhar, reescreva-a. Emita apenas JSON válido.

CONTRATO DE SAÍDA — siga EXATAMENTE estes nomes de campo (case-sensitive), sem acrescentar, remover ou renomear chaves. A resposta deve ser um único objeto JSON com esta forma exata:

{
  "semana": "<data da segunda-feira alvo, YYYY-MM-DD, igual ao campo 'semana' da entrada>",
  "pecas": [
    {
      "id": "<slug curto único, ex: 'ig-card1', 'ig-c1'>",
      "canal": "instagram",
      "formato": "carrossel" | "card",
      "linha": "Mentoria com o Especialista" | "Framework Próprio" | "Dilema de Sócio" | "Liderança (Dale Carnegie)" | "Tese Regional",
      "publicar_em": "<um dos valores de datas_alvo_semana da entrada, formato YYYY-MM-DDTHH:MM:SS>",
      "racional": "<1 frase: por que este tema agora>",

      // presente SOMENTE se formato=carrossel:
      "slides": [
        {"tipo": "capa", "kicker": "<linha editorial em maiusculas>", "titulo": "<=60 chars>", "subtitulo": null},
        {"tipo": "conteudo", "numero": "1", "titulo": "<=60 chars>", "corpo": "<=220 chars>"},
        {"tipo": "conteudo", "numero": "2", "titulo": "<=60 chars>", "corpo": "<=220 chars>"},
        {"tipo": "cta", "titulo": "<=60 chars>", "corpo": "<=220 chars>"}
      ],

      // presente SOMENTE se formato=card:
      "gancho": "<=90 caracteres, frase de contexto/problema (1a parte, tom neutro)",
      "virada": "<=90 caracteres, frase de conclusao/insight (2a parte, o giro do pensamento)",

      // presente em TODA peca (carrossel ou card) — legenda/corpo unico usado nos dois canais:
      "legenda": "<900-1400 caracteres, com hashtags-base>"
    }
  ]
}

Regras adicionais do contrato:
- O esquema acima é apenas ilustrativo: os comentários iniciados por "//" e os placeholders entre "<>" ou com "|" NÃO devem aparecer no seu JSON de saída — são apenas explicações de formato.
- Exatamente 14 peças no total, cobrindo todos os slots de datas_alvo_semana da entrada (2 por dia, 7 dias).
- "canal" é sempre "instagram" (a peça é publicada em ambos os canais a partir do mesmo conteúdo/imagem — não crie peças com canal="linkedin").
- Todo carrossel e todo card devem ter campo "legenda" com hashtags.
- Nunca omita "pecas" nem devolva lista vazia — isso é tratado como falha total do lote.
- Sua resposta inteira deve ser um único objeto JSON válido (RFC 8259), sem comentários, sem texto antes/depois, sem cercas de código ```."""


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


HORARIOS_PICO = ("08h", "19h")  # America/Sao_Paulo — padrao atual: 2 posts/dia


def _proximas_datas_uteis(hoje: datetime) -> dict:
    """Calcula as datas-alvo da proxima semana (segunda a domingo) a partir
    de `hoje`, seguindo a cadencia atual de 2 peças/dia (08h e 19h)."""
    dias_ate_segunda = (7 - hoje.weekday()) % 7
    dias_ate_segunda = dias_ate_segunda or 7
    proxima_segunda = hoje + timedelta(days=dias_ate_segunda)
    dias = {}
    nomes = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    for i, nome in enumerate(nomes):
        dias[nome] = (proxima_segunda + timedelta(days=i)).strftime("%Y-%m-%d")
    return dias


def _build_user_payload(metrics: dict, temas_recentes: list, hoje: datetime = None) -> dict:
    """Monta o payload de entrada do Cerebro. `datas_alvo_semana` agora tem
    14 slots (2 por dia, todos os 7 dias da semana, 08h/19h America/Sao_Paulo)
    — padrao de cadencia atual (ver SYSTEM_PROMPT). Chaves no formato
    '<dia>_<hora>', ex: 'segunda_08h', 'segunda_19h', ..., 'domingo_19h'."""
    hoje = hoje or datetime.now()
    datas = _proximas_datas_uteis(hoje)
    nomes = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    datas_alvo_semana = {}
    for nome in nomes:
        for hora in HORARIOS_PICO:
            datas_alvo_semana[f"{nome}_{hora}"] = f"{datas[nome]}T{hora[:2]}:00:00"
    return {
        "metricas_semana_anterior": metrics,
        "temas_ultimos_45_dias": temas_recentes,
        "datas_alvo_semana": datas_alvo_semana,
        "semana": datas["segunda"],
    }


def _mock_batch(user_payload: dict) -> dict:
    """Lote de exemplo gerado localmente, sem chamada de rede, usado
    quando ANTHROPIC_API_KEY nao esta configurada (modo mock). Cobre os
    2 formatos do contrato atual (instagram/carrossel e instagram/card,
    ambos publicados em duplo-canal) para permitir teste completo de
    renderizacao/validacao/dry-run. Nao preenche as 14 peças da semana —
    apenas 2 peças de exemplo, o suficiente para exercitar o pipeline."""
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
                "id": "ig-c1",
                "canal": "instagram",
                "formato": "carrossel",
                "linha": "Mentoria com o Especialista",
                "publicar_em": datas["segunda_08h"],
                "racional": (
                    "Peca de exemplo do modo mock (sem ANTHROPIC_API_KEY) — cobre o formato "
                    "carrossel do contrato atual (dual-canal) para teste de dry-run."
                ),
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
                "publicar_em": datas["segunda_19h"],
                "racional": (
                    "Peca de exemplo do modo mock (sem ANTHROPIC_API_KEY) — cobre o formato "
                    "card do contrato atual (dual-canal) para teste de dry-run."
                ),
                "gancho": "O interior do RS parece pequeno no mapa.",
                "virada": "Mas é uma potência empresarial invisível de fora.",
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


def _aplicar_peca_fixa(lote: dict, user_payload: dict) -> dict:
    """Injeta peca(s) fixas pre-escritas (config/peca_fixa_lancamento.json)
    no lote gerado, substituindo a peca do LLM/mock que ocupa o mesmo slot
    de datas_alvo_semana (mantendo a cadencia de exatamente 8 pecas). O
    arquivo e consumido uma unica vez: apos aplicar, e renomeado com sufixo
    '_usada' para nao repetir em semanas seguintes. Se o arquivo nao
    existir (ja consumido ou nunca criado), o lote volta inalterado."""
    if not PECA_FIXA_PATH.exists():
        return lote

    try:
        dados = json.loads(PECA_FIXA_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Falha ao ler %s — peca fixa ignorada nesta rodada.", PECA_FIXA_PATH)
        return lote

    datas = user_payload.get("datas_alvo_semana", {})
    pecas_fixas = dados.get("pecas", [])
    if not pecas_fixas:
        return lote

    for peca_fixa in pecas_fixas:
        peca_fixa = dict(peca_fixa)  # nao mutar o dict original
        slot = peca_fixa.pop("slot", None)
        publicar_em = datas.get(slot)
        if not publicar_em:
            logger.warning("Peca fixa com slot desconhecido/ausente (%s) — pulando.", slot)
            continue
        peca_fixa["publicar_em"] = publicar_em
        # Remove qualquer peca do lote (LLM/mock) que caia no mesmo slot,
        # para evitar duplicar horario e manter o total de 14 pecas/semana.
        lote["pecas"] = [p for p in lote.get("pecas", []) if p.get("publicar_em") != publicar_em]
        lote["pecas"].append(peca_fixa)
        logger.info("Peca fixa '%s' injetada no slot '%s' (%s).", peca_fixa.get("id"), slot, publicar_em)

    try:
        usada_path = PECA_FIXA_PATH.with_name(PECA_FIXA_PATH.stem + "_usada.json")
        PECA_FIXA_PATH.rename(usada_path)
        logger.info("Peca fixa consumida — arquivada em %s (nao sera reaplicada).", usada_path)
    except Exception:
        logger.exception(
            "Falha ao arquivar %s apos uso — risco de reaplicar na proxima semana; "
            "verificar/renomear manualmente.", PECA_FIXA_PATH,
        )

    return lote


def generate_batch(metrics: dict, temas_recentes: list, hoje: datetime = None) -> dict:
    """Gera o lote semanal via API do Claude (ou modo mock). Retorna o
    dict do contrato de saida (secao 4.1 da especificacao)."""
    user_payload = _build_user_payload(metrics, temas_recentes, hoje)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return _aplicar_peca_fixa(_mock_batch(user_payload), user_payload)

    try:
        import anthropic
    except ImportError:
        logger.error("SDK 'anthropic' nao instalado. Rode: pip install anthropic. Usando modo mock.")
        return _aplicar_peca_fixa(_mock_batch(user_payload), user_payload)

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
            return _aplicar_peca_fixa(lote, user_payload)
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
    return _aplicar_peca_fixa(_mock_batch(user_payload), user_payload)
