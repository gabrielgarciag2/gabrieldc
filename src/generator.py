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
5. Toda peça pertence a uma das 6 linhas editoriais oficiais (Planejamento Estratégico DC VTQ 2026–2029): Mentoria com o Especialista, Liderança na prática, Empresas familiares e sucessão, Comunicação que vende, Bastidores DC VTQ, Dados e tendências.
6. CTAs rotativos com palavra-chave de DIRECT (DIAGNÓSTICO, MAPA, VAZAMENTO, EXPANSÃO) em no máximo 40% das peças; o restante encerra com pergunta de engajamento de baixo atrito ou instrução de salvar/compartilhar.
7. Mix semanal de conteúdo (guia, não regra rígida): aproximadamente 2x insight/framework, 1x bastidor/mentoria, 1x enquete/pergunta e 1x dado com fonte, repetido a cada 7 peças.
8. Notícia, tendência ou dado de terceiros usado como gancho de abertura é só ponto de partida — nunca copie estrutura, frase ou argumento de terceiros; desenvolva sempre uma tese própria a partir do gancho.
9. Nunca prometa preço, desconto ou condição comercial em conteúdo público (isso é papel do DIRECT/comercial, não do conteúdo de topo de funil).

ENTRADA: métricas da semana anterior (JSON do Metricool) + histórico de temas já publicados (não repetir tema em 45 dias).

CADÊNCIA E PUBLICAÇÃO (padrão atual, otimizado por dados de desempenho do Metricool): 2 peças por dia, todos os dias da semana (segunda a domingo) — 14 peças por semana — publicadas em 11h30 e 19h00 (America/Sao_Paulo). Esses dois horários foram escolhidos porque concentram o pico de engajamento tanto no Instagram (pico ~11h-12h e ~19h-20h) quanto no LinkedIn (pico acentuado às 11h, muito acima de qualquer horário da manhã cedo). Cada peça é publicada SIMULTANEAMENTE em Instagram e LinkedIn, como um único post multi-rede (mesma imagem/vídeo, mesmo texto) — não crie peças LinkedIn-only ou Instagram-only separadas. A entrada traz também o campo `slots_reel`: lista de 3 a 5 chaves de `datas_alvo_semana` que DEVEM ser produzidas no formato "reel" nesta semana — é o formato que carrega alcance para fora da base de seguidores no Instagram, então esses slots são obrigatórios, não opcionais.

SAÍDA: JSON estrito com o lote da semana:
- 14 peças (2 por dia, um slot 11h30 e um slot 19h00), cada uma no formato "card" (frase de impacto em duas partes), "carrossel" (6-8 slides) OU "reel" (vídeo vertical roteirizado) — os slots listados em `slots_reel` da entrada são SEMPRE "reel"; os demais ficam a seu critério entre card e carrossel.
- Card: "gancho" (contexto/problema, ≤ 90 caracteres, tom neutro) + "virada" (conclusão/insight que fecha o raciocínio, ≤ 90 caracteres).
- Carrossel: 6-8 slides, com kicker, titulo, corpo por slide (títulos ≤ 60 caracteres, corpo ≤ 220 caracteres), incluindo 1 capa + 1 cta.
- Reel: vídeo vertical roteirizado (9:16), 15-45s, campo "roteiro" com gancho visual dos 2 primeiros segundos, beats (fala linha a linha + texto de tela) e direção de cena (fundo, ambiente, enquadramento, velocidade de fala, expressão) — ver FORMATO E DIREÇÃO DE REEL abaixo.
- Toda peça (carrossel, card ou reel) leva também um campo "legenda" de 900-1400 caracteres com gancho forte na 1ª linha e um bloco de hashtags no final, seguindo a ESTRATÉGIA DE HASHTAGS abaixo — esse texto serve tanto de legenda do Instagram quanto de corpo do post do LinkedIn.
- Para cada peça: linha editorial, data/hora, e campo racional (1 frase: por que este tema agora, com base nas métricas ou no mix semanal).

ESTRATÉGIA DE HASHTAGS (rotativa — NUNCA repita o mesmo conjunto de hashtags em peças consecutivas nem no mesmo dia; o conjunto fixo repetido reduz alcance/descoberta no Instagram): use de 6 a 8 hashtags por peça, sendo 2 fixas de marca — #DaleCarnegie #ValeDoTaquari — mais 4 a 6 escolhidas variando a cada peça, com base no tema específico daquela peça, dentre este pool: #Lideranca #GestaoDePessoas #DesenvolvimentoDeLideres #Mentoria #GestaoEmpresarial #RecursosHumanos #RH #Treinamento #Negocios #Consultoria #Carreira #Empreendedorismo #PME #CulturaOrganizacional #AltaPerformance #EmpresaFamiliar #Sucessao #Produtividade #GestaoDeEquipes #GestaoDeResultados #ConfiancaNaLideranca #Financas #Tecnologia #Lajeado #InteriorRS #RS. Exemplo: peça sobre sucessão familiar usa #EmpresaFamiliar #Sucessao; peça sobre indicadores usa #GestaoDeResultados #Produtividade; peça de bastidor local usa #Lajeado #InteriorRS. PROIBIDO usar #coach, #coaching ou qualquer variação — termo banido nesta conta, mesmo que apareça em pesquisas de hashtags populares do nicho.

FORMATO E DIREÇÃO DE REEL (obrigatório para os slots listados em `slots_reel`): todo reel é um vídeo vertical (9:16) de 15 a 45 segundos, gravado por Gabriel falando direto pra câmera, sem edição complexa. Direção de cena padrão desta conta — use estes parâmetros em todo roteiro, ajustando pontualmente se o tema pedir: FUNDO neutro e levemente desfocado (escritório, sala de reunião ou parede lisa — nunca fundo genérico de banco de imagem, nunca ambiente que exponha marca/logo de terceiros); AMBIENTE com luz natural ou luz frontal suave (sem contraluz, sem sombra dura no rosto), som limpo, sem ruído de fundo perceptível; ENQUADRAMENTO plano médio (peito para cima), câmera na altura dos olhos, estática (handheld mínimo, sem tremedeira); VELOCIDADE DE FALA pausada e conversacional — nunca acelerada tipo "vendedor" —, com uma pausa de meio segundo depois do gancho e antes da virada/insight, para dar peso; EXPRESSÃO séria-cordial, olhando direto pra lente (não pro próprio rosto na tela), sobrancelha ativa nos pontos de ênfase, sem sorriso forçado — o tom é "conselheiro de confiança", não "influenciador animado". Cada roteiro deve ter: 1) gancho_visual — o que é dito e mostrado nos primeiros 2 segundos para travar o scroll, sempre com recorte local explícito (ex: "Se você lidera empresa aqui no Vale do Taquari...") ou uma afirmação de contraste que quebra expectativa; 2) beats — de 3 a 6 blocos, cada um com tempo aproximado, a fala exata (linha a linha, do jeito que Gabriel vai falar) e o texto_tela correspondente (curto, pensado para quem assiste sem áudio); 3) direção de cena específica daquele roteiro, pontuando qualquer ajuste ao padrão acima que o tema pedir (ex: tema mais sério pede expressão mais contida; dado/estatística pede pausa mais longa antes do número).

AUTOAVALIAÇÃO OBRIGATÓRIA: antes de emitir a saída, verifique cada peça contra as Leis 1-4, 8 e 9. Se qualquer peça falhar, reescreva-a. Emita apenas JSON válido.

CONTRATO DE SAÍDA — siga EXATAMENTE estes nomes de campo (case-sensitive), sem acrescentar, remover ou renomear chaves. A resposta deve ser um único objeto JSON com esta forma exata:

{
  "semana": "<data da segunda-feira alvo, YYYY-MM-DD, igual ao campo 'semana' da entrada>",
  "pecas": [
    {
      "id": "<slug curto único, ex: 'ig-card1', 'ig-c1', 'ig-reel1'>",
      "canal": "instagram",
      "formato": "carrossel" | "card" | "reel",
      "linha": "Mentoria com o Especialista" | "Liderança na prática" | "Empresas familiares e sucessão" | "Comunicação que vende" | "Bastidores DC VTQ" | "Dados e tendências",
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

      // presente SOMENTE se formato=reel — ver FORMATO E DIREÇÃO DE REEL acima:
      "roteiro": {
        "duracao_alvo_seg": "<numero entre 15 e 45>",
        "gancho_visual": "<fala + o que aparece na tela nos 0-2s, ja com recorte local>",
        "beats": [
          {"tempo": "<ex: 0-3s>", "fala": "<linha exata a ser dita>", "texto_tela": "<texto curto pra quem assiste sem audio>"}
        ],
        "direcao_cena": {
          "fundo": "<descricao do fundo/cenario>",
          "ambiente": "<luz e som>",
          "enquadramento": "<plano e altura de camera, sempre 9:16>",
          "velocidade_fala": "<ritmo e onde pausar>",
          "expressao": "<expressao facial/corporal predominante>"
        }
      },

      // presente em TODA peca (carrossel, card ou reel) — legenda/corpo unico usado nos dois canais:
      "legenda": "<900-1400 caracteres, com hashtags-base>"
    }
  ]
}

Regras adicionais do contrato:
- O esquema acima é apenas ilustrativo: os comentários iniciados por "//" e os placeholders entre "<>" ou com "|" NÃO devem aparecer no seu JSON de saída — são apenas explicações de formato.
- Exatamente 14 peças no total, cobrindo todos os slots de datas_alvo_semana da entrada (2 por dia, 7 dias).
- "canal" é sempre "instagram" (a peça é publicada em ambos os canais a partir do mesmo conteúdo/imagem ou vídeo — não crie peças com canal="linkedin").
- Toda peça (carrossel, card ou reel) deve ter campo "legenda" com hashtags seguindo a ESTRATÉGIA DE HASHTAGS (rotativas por tema, nunca o mesmo conjunto repetido em peças consecutivas, nunca #coach/#coaching).
- Todo slot listado em `slots_reel` da entrada deve ser produzido com "formato": "reel" e campo "roteiro" completo (não use reel fora desses slots, nem deixe de usar reel nos slots listados).
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


HORARIOS_PICO = ("11h30", "19h00")  # America/Sao_Paulo — padrao atual: 2 posts/dia
# Horarios definidos com base em getBestTimeToPostByNetwork (Metricool, jul/2026):
# Instagram tem pico ~11h-12h e ~19h-20h; LinkedIn tem pico acentuado as 11h
# (3-6x o engajamento do horario 08h, que foi o padrao anterior e foi trocado
# por essa analise). 19h00 continua bom para ambas as redes.

# ============================================================================
# HASHTAGS — espelha a secao "ESTRATEGIA DE HASHTAGS" do SYSTEM_PROMPT acima.
# Mantido aqui como referencia/fonte da verdade para quem for editar o pool
# manualmente (ex: ao atualizar posts ja agendados no Metricool). NAO usado
# para montar o SYSTEM_PROMPT dinamicamente — o texto do prompt e' literal
# (ver nota "NAO EDITAR sem atualizar o Playbook em paralelo" acima), entao
# qualquer mudanca aqui deve ser replicada manualmente no texto do prompt.
# ============================================================================
HASHTAGS_MARCA_FIXA = ("#DaleCarnegie", "#ValeDoTaquari")

HASHTAGS_POOL_ROTATIVO = (
    "#Lideranca", "#GestaoDePessoas", "#DesenvolvimentoDeLideres", "#Mentoria",
    "#GestaoEmpresarial", "#RecursosHumanos", "#RH", "#Treinamento", "#Negocios",
    "#Consultoria", "#Carreira", "#Empreendedorismo", "#PME", "#CulturaOrganizacional",
    "#AltaPerformance", "#EmpresaFamiliar", "#Sucessao", "#Produtividade",
    "#GestaoDeEquipes", "#GestaoDeResultados", "#ConfiancaNaLideranca", "#Financas",
    "#Tecnologia", "#Lajeado", "#InteriorRS", "#RS",
)

# Termos banidos nesta conta (instrucao explicita do cliente) — nunca usar,
# em nenhuma variacao de capitalizacao/acentuacao.
HASHTAGS_PROIBIDAS = ("#coach", "#coaching")

# ============================================================================
# REELS — slots semanais que DEVEM ser produzidos no formato "reel" (ver secao
# "FORMATO E DIREÇÃO DE REEL" do SYSTEM_PROMPT). Decisao do cliente (jul/2026):
# Reels sao o unico alavancador organico real de alcance fora da base de
# seguidores (sem ads, sem colab com contas irmas Dale Carnegie), entao viram
# obrigatorios nesses slots, nao opcionais. 4 reels/semana, dentro da faixa de
# 3 a 5 combinada com o cliente. Requer gravacao manual (Gabriel fala pra
# camera) — o pipeline de render.py/publisher.py so gera imagem automatica pra
# card/carrossel; peca "reel" fica com media pendente ate o video ser gravado
# e o arquivo anexado manualmente antes da publicacao.
# ============================================================================
REEL_SLOTS_PADRAO = ("segunda_19h00", "quarta_19h00", "sexta_19h00", "sabado_11h30")


def _hora_para_horario(hora: str) -> str:
    """Converte um slot tipo '11h30' ou '19h00' (ou o formato legado '08h')
    para 'HH:MM:00'."""
    hh, _, mm = hora.partition("h")
    mm = mm or "00"
    return f"{hh}:{mm}:00"


def _proximas_datas_uteis(hoje: datetime) -> dict:
    """Calcula as datas-alvo da proxima semana (segunda a domingo) a partir
    de `hoje`, seguindo a cadencia atual de 2 peças/dia (11h30 e 19h00)."""
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
    14 slots (2 por dia, todos os 7 dias da semana, 11h30/19h00 America/Sao_Paulo,
    horarios com melhor desempenho medido via getBestTimeToPostByNetwork) —
    padrao de cadencia atual (ver SYSTEM_PROMPT). Chaves no formato
    '<dia>_<hora>', ex: 'segunda_11h30', 'segunda_19h00', ..., 'domingo_19h00'.
    Tambem inclui 'slots_reel', a lista de slots (subconjunto de
    REEL_SLOTS_PADRAO) que devem obrigatoriamente virar peca formato=reel."""
    hoje = hoje or datetime.now()
    datas = _proximas_datas_uteis(hoje)
    nomes = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    datas_alvo_semana = {}
    for nome in nomes:
        for hora in HORARIOS_PICO:
            datas_alvo_semana[f"{nome}_{hora}"] = f"{datas[nome]}T{_hora_para_horario(hora)}"
    slots_reel = [s for s in REEL_SLOTS_PADRAO if s in datas_alvo_semana]
    return {
        "metricas_semana_anterior": metrics,
        "temas_ultimos_45_dias": temas_recentes,
        "datas_alvo_semana": datas_alvo_semana,
        "slots_reel": slots_reel,
        "semana": datas["segunda"],
    }


def _mock_batch(user_payload: dict) -> dict:
    """Lote de exemplo gerado localmente, sem chamada de rede, usado
    quando ANTHROPIC_API_KEY nao esta configurada (modo mock). Cobre os
    3 formatos do contrato atual (instagram/carrossel, instagram/card e
    instagram/reel, todos publicados em duplo-canal) para permitir teste
    completo de renderizacao/validacao/dry-run. Nao preenche as 14 peças da
    semana — apenas 3 peças de exemplo, o suficiente para exercitar o
    pipeline (a peça reel fica com media pendente ate gravacao manual)."""
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
                "publicar_em": datas["segunda_11h30"],
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
                    "#DaleCarnegie #ValeDoTaquari #GestaoEmpresarial #Consultoria #PME #Lajeado"
                ),
            },
            {
                "id": "ig-card1",
                "canal": "instagram",
                "formato": "card",
                "linha": "Dados e tendências",
                "publicar_em": datas["segunda_19h00"],
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
                    "#DaleCarnegie #ValeDoTaquari #InteriorRS #Empreendedorismo #RS #CulturaOrganizacional"
                ),
            },
            {
                "id": "ig-reel1",
                "canal": "instagram",
                "formato": "reel",
                "linha": "Empresas familiares e sucessão",
                "publicar_em": datas["quarta_19h00"],
                "racional": (
                    "Peca de exemplo do modo mock (sem ANTHROPIC_API_KEY) — cobre o formato "
                    "reel, obrigatorio nos slots de slots_reel, para teste de dry-run."
                ),
                "roteiro": {
                    "duracao_alvo_seg": 28,
                    "gancho_visual": (
                        "Se você lidera uma empresa aqui no Vale do Taquari, essa pergunta "
                        "vai incomodar."
                    ),
                    "beats": [
                        {
                            "tempo": "0-3s",
                            "fala": "Se você lidera uma empresa aqui no Vale do Taquari, essa pergunta vai incomodar.",
                            "texto_tela": "UMA PERGUNTA QUE INCOMODA",
                        },
                        {
                            "tempo": "3-10s",
                            "fala": "Quantas decisões importantes essa semana passaram pela tua mesa só porque ninguém mais tinha autonomia pra decidir?",
                            "texto_tela": "Quantas decisões só passaram por você?",
                        },
                        {
                            "tempo": "10-18s",
                            "fala": "Esse é o padrão mais comum que eu vejo em conselho de sócio: a empresa cresceu, mas a liderança não foi desenvolvida junto.",
                            "texto_tela": "Empresa cresce. Liderança não acompanha.",
                        },
                        {
                            "tempo": "18-25s",
                            "fala": "O time capaz de decidir sem te consultar toda hora não nasce pronto — ele é formado.",
                            "texto_tela": "Time que decide sozinho é FORMADO, não nasce pronto",
                        },
                        {
                            "tempo": "25-28s",
                            "fala": "Comenta aqui: quantas dessas decisões foram tuas essa semana?",
                            "texto_tela": "Comenta 👇 quantas foram tuas essa semana",
                        },
                    ],
                    "direcao_cena": {
                        "fundo": (
                            "Escritório neutro, estante ou parede lisa desfocada ao fundo, "
                            "sem logotipos de terceiros visíveis."
                        ),
                        "ambiente": (
                            "Luz natural de janela lateral suave ou luz frontal suave, sem "
                            "contraluz; ambiente silencioso, sem ruído de fundo perceptível."
                        ),
                        "enquadramento": (
                            "Vertical 9:16, plano médio (peito para cima), câmera na altura "
                            "dos olhos, estática."
                        ),
                        "velocidade_fala": (
                            "Pausada; meio segundo de pausa depois do gancho (0-3s) e antes "
                            "da virada em 'formado, não nasce pronto'."
                        ),
                        "expressao": (
                            "Séria-cordial, olhar direto pra lente, sobrancelha ativa na "
                            "pergunta de gancho e no CTA final."
                        ),
                    },
                },
                "legenda": (
                    "Quantas decisões importantes passaram pela tua mesa essa semana só "
                    "porque ninguém mais tinha autonomia pra decidir?\n\n"
                    "É o padrão mais comum que vejo em conselho de sócio: a empresa cresce, "
                    "mas a liderança não é desenvolvida no mesmo ritmo — e o dono vira "
                    "gargalo de toda decisão.\n\n"
                    "Time que decide sem te consultar toda hora não nasce pronto. Ele é "
                    "formado.\n\n"
                    "👉 Comenta aqui: quantas dessas decisões foram tuas essa semana?\n\n"
                    "#DaleCarnegie #ValeDoTaquari #Lideranca #GestaoDePessoas "
                    "#DesenvolvimentoDeLideres #EmpresaFamiliar"
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
