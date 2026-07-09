# Agente de Conteúdo — Gabriel Garcia / DC VTQ

Pipeline semanal 100% autônomo que lê métricas no Metricool, gera o lote de
conteúdo da semana (3 posts LinkedIn + 3 carrosséis Instagram + 2 cards
Instagram) via API do Claude, renderiza as artes em PNG (Pillow,
Navy/Gold), hospeda as imagens num bucket público (Cloudflare R2) e agenda
tudo no Metricool com `autoPublish: true`. Ao final de cada ciclo envia um
relatório por e-mail. Depois do setup inicial, roda sozinho via GitHub
Actions, toda segunda-feira às 05h (horário de Brasília).

Este projeto implementa a `Especificacao_Pipeline_Agente.md` (documento
mestre) e usa literalmente o "Prompt do Agente" da seção 3 do
`Agente_de_Conteudo_Playbook.md` como `system prompt` da chamada à API do
Claude.

## Pré-requisitos (contas necessárias)

| Serviço | Para quê | Link |
|---|---|---|
| Anthropic Console | chave de API do Claude (gera o lote semanal) | https://console.anthropic.com/ |
| Metricool (conta Advanced+) | agendamento/publicação em LinkedIn e Instagram | https://metricool.com/ |
| Cloudflare (R2) | hospedagem pública dos PNGs gerados | https://dash.cloudflare.com/ |
| Resend | envio do e-mail de relatório semanal | https://resend.com/ |
| GitHub | repositório + Actions como agendador (scheduler) | https://github.com/ |

## Passo a passo para obter cada chave

1. **Anthropic** — em https://console.anthropic.com/settings/keys crie uma
   API key. Copie para `ANTHROPIC_API_KEY`.
2. **Metricool** — na sua conta Advanced+, gere o `userToken` de API
   (Configurações > API, ou confirme o caminho atual na doc oficial —
   ver nota de atenção mais abaixo). `METRICOOL_USER_ID` e
   `METRICOOL_BLOG_ID` já vêm preenchidos no `.env.example` com os valores
   da especificação (5009746 / 6504655) — confirme se ainda são os
   corretos para a sua conta.
3. **Cloudflare R2** — em R2 > Create bucket, crie um bucket (ex:
   `agente-conteudo-dcvtq`). Em R2 > Manage R2 API Tokens, gere um token
   com permissão de leitura/escrita nesse bucket — isso gera
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`. Ative
   acesso público de leitura ao bucket (domínio `r2.dev` ou domínio
   customizado) para obter `R2_PUBLIC_BASE_URL`.
4. **Resend** — em https://resend.com/api-keys gere uma chave
   (`RESEND_API_KEY`). Em teste, pode usar o remetente
   `onboarding@resend.dev` (`REPORT_FROM_EMAIL`); em produção, verifique
   um domínio próprio no Resend.
5. **Onde colar cada chave:**
   - **Uso local (teste em dry-run):** copie `.env.example` para `.env`
     e preencha os valores. O `.env` nunca é commitado (está no
     `.gitignore`).
   - **Produção (GitHub Actions):** cadastre cada variável como
     *GitHub Secret* (Settings > Secrets and variables > Actions > New
     repository secret), usando exatamente os mesmos nomes do
     `.env.example`.

## Como rodar localmente em modo dry-run

```bash
cd agente-conteudo-dcvtq
python3 -m venv .venv && source .venv/bin/activate     # opcional, recomendado
pip install -r requirements.txt
python run.py --dry-run
```

Sem **nenhuma** variável de ambiente configurada, o `--dry-run` já
funciona: o `generator.py` cai em **modo mock** (gera um lote de exemplo
localmente, sem chamar a API do Claude), o `render.py` gera PNGs reais em
`output/{semana}/`, e o `storage.py`/`publisher.py`/`reporter.py` apenas
calculam e imprimem o que seria enviado, sem nenhuma chamada de rede real
a Metricool/R2/Resend. O plano completo (peças, horários, payloads) é
impresso no console ao final.

Com `ANTHROPIC_API_KEY` configurada, o `--dry-run` passa a gerar o lote de
verdade via Claude API, mas continua sem publicar/subir/enviar nada real.

## Como subir pro GitHub e ativar o Actions

```bash
cd agente-conteudo-dcvtq
git init
git add .
git commit -m "Setup inicial do Agente de Conteudo DC VTQ"
git branch -M main
git remote add origin https://github.com/<seu-usuario>/agente-conteudo-dcvtq.git
git push -u origin main
```

Depois:
1. Cadastre todos os secrets (ver tabela acima) em *Settings > Secrets and
   variables > Actions*.
2. O workflow `.github/workflows/agente.yml` já está configurado com
   `cron: "0 8 * * 1"` (08h UTC = 05h BRT, segundas) e
   `workflow_dispatch` com input opcional `dry_run` — use a aba *Actions*
   do GitHub para disparar manualmente um teste (com ou sem dry-run)
   antes de confiar no cron.
3. O job tem `permissions: contents: write` e faz commit automático de
   `state/history.json` e `state/scheduled.json` ao final de cada ciclo
   real (não em dry-run).

## Kill switch

Defina o secret/variável `KILL_SWITCH=true` (no `.env` local ou nos
GitHub Secrets) a qualquer momento. O `run.py` verifica essa variável
**antes de qualquer etapa** — se estiver `true`, o pipeline apenas loga e
encerra, sem tocar em Metricool, R2 ou Resend, sem gerar nada. Para
retomar, volte o valor para `false` (ou remova a variável).

## Critérios de aceite (seção 10 da especificação) — status neste build

| # | Critério | Status |
|---|---|---|
| 1 | Dry-run gera JSON + PNGs localmente, não publica, imprime o plano | **Validado localmente.** `python run.py --dry-run` sem nenhuma env var roda até o fim (exit code 0), gera PNGs reais 1080×1350 em `output/{semana}/` e imprime peças/horários/payloads no console. |
| 2 | Lote de teste com `draft:true` aparece no planner do Metricool (imagens visíveis no IG, texto correto no LinkedIn) | **Não validável neste build** — exige `METRICOOL_USER_TOKEN` real e conta Metricool Advanced+ do usuário. `src/publisher.py` já suporta `draft=True` para esse teste; falta rodar com credenciais reais. |
| 3 | Validador reprova peça-isca com "Casa Ativa" e "R$ 300 mil" | **Validado localmente.** `tests/test_validator.py::test_criterio_aceite_3_peca_isca_casa_ativa_r300mil` passa (`python3 -m unittest tests.test_validator -v`). |
| 4 | Overflow de texto reduz fonte sem estourar a arte (título de 120 chars) | **Validado localmente.** `tests/test_render.py` cobre título de 120+ caracteres: a fonte é reduzida (nunca abaixo de 32px) e, no limite, o texto é truncado com reticências — sem exceção, com PNG final íntegro (1080×1350). |
| 5 | Cron dispara e conclui em < 5 min; e-mail de relatório chega | **Não validável neste build** — depende do agendador real do GitHub Actions e de credenciais Resend reais. O workflow está configurado (`timeout-minutes: 15`, cron semanal) e `reporter.py` tem fallback silencioso testável localmente (sem crash quando `RESEND_API_KEY` está ausente). |
| 6 | `KILL_SWITCH` interrompe sem efeitos colaterais | **Validado localmente.** Com `KILL_SWITCH=true`, `run.py` loga e retorna antes de qualquer chamada de rede/render (verificado lendo o código de `check_kill_switch()` em `run.py`, chamado como primeira ação de `run()`). |

## Testes incluídos

```bash
pip install -r requirements.txt
python3 -m py_compile run.py src/*.py         # checagem de sintaxe
python3 -m unittest discover -s tests -v      # 11 testes (validator + render)
python3 run.py --dry-run                      # execução ponta a ponta
```

## Suposições e pontos a confirmar antes de publicar de verdade

A própria especificação (seção 7 e seção 11) pedia para **confirmar contra
a documentação oficial do Metricool** a autenticação e os endpoints exatos
antes de ir para produção. Isso já foi feito em 09/07/2026 (consultando o
PDF oficial `static.metricool.com/API+DOC/API+English.pdf` e o Help
Center do Metricool) e o código foi corrigido. Resumo do que mudou:

**Confirmado e corrigido no código:**
- Base URL `https://app.metricool.com/api`. O `userToken` vai no
  **header** `X-Mc-Auth` (não como query param, como o build inicial
  fazia) — corrigido em `_auth_headers()` nos dois módulos. `userId` e
  `blogId` continuam como query params.
- Endpoint de agendamento confirmado: `POST /v2/scheduler/posts`.
- **Passo que faltava por completo no build inicial**: para postar com
  uma URL de mídia externa (nosso caso, PNGs no R2), é preciso primeiro
  chamar `GET /api/actions/normalize/image/url?url=<url>` para que o
  Metricool copie a mídia para os servidores dele — só essa URL
  normalizada (não a URL crua do R2) pode entrar no array `media` do
  payload. Implementado em `normalize_media_url()`/`normalize_media_urls()`
  em `src/publisher.py`, chamado automaticamente por `schedule_posts()`
  antes de agendar peças do Instagram (fora de dry-run).
- Endpoint `GET /v2/analytics/reels/instagram?from&to` e o padrão
  `GET /stats/timeline/{metrica}` (ex. `igFollowers`) confirmados para
  leitura de métricas.

**Ainda não confirmado (best-effort — reveja com um teste real):**
- O endpoint exato para métricas *por post* do Instagram (usado para os
  top-3/bottom-3 no relatório semanal) — `src/metrics.py` assume
  `GET /v2/analytics/posts/instagram` por analogia com o padrão acima,
  mas isso não apareceu literalmente na documentação consultada. Confirme
  pelo inspector do navegador (Planning → Analytics, aba Network →
  Fetch/XHR) como a própria doc do Metricool recomenda para casos não
  documentados.
- Os nomes exatos dos campos na resposta do `POST /v2/scheduler/posts`
  (assumimos `id`, `uuid`, `previewUrl`/`url`) — confirme rodando um
  agendamento de teste com `draft: true` (critério de aceite #2) e olhando
  a resposta real.
- Os **payloads de LinkedIn e Instagram em `src/publisher.py`
  (`build_linkedin_payload` / `build_instagram_payload`) continuam sendo,
  na base, cópia literal dos contratos das seções 7.1 e 7.2 da
  especificação** (que a especificação afirma já terem sido validados em
  produção via MCP). Foram adicionados os campos `creationDate` e
  `saveExternalMediaFiles` que aparecem no exemplo oficial de payload da
  doc do Metricool mas não no exemplo da especificação — isso não deve
  quebrar nada, mas remova-os se o Metricool reclamar num teste real.

Fontes consultadas: [Metricool API — PDF oficial](https://static.metricool.com/API+DOC/API+English.pdf),
[Basic Guide for API Integration](https://help.metricool.com/en/article/basic-guide-for-api-integration-abukgf/),
[How to get an endpoint in Metricool](https://help.metricool.com/en/article/how-to-get-an-endpoint-in-metricool-to-make-api-calls-15xciw7/).
- O nome do modelo Claude (`claude-sonnet-4-6`) foi mantido exatamente
  como pedido na especificação, mas é configurável via `CLAUDE_MODEL` —
  confira a disponibilidade/nome atual em
  https://docs.claude.com/en/docs/about-claude/models antes de rodar em
  produção.
- `config/blocklist.txt` foi montado a partir dos exemplos citados
  explicitamente na especificação (Casa Ativa, Gasparin, Marçal, G4) e do
  playbook. **Mantenha essa lista viva**: adicione qualquer novo cliente,
  contato ou concorrente citado em conversas antes do próximo ciclo.
- `config/temas.json` contém 64 temas pré-aprovados extraídos dos ângulos
  já usados/planejados em `Legendas_Instagram_30_Dias_1.md` (nenhum texto
  de cliente foi copiado — apenas o ângulo/tese genérico), categorizados
  pelas 5 linhas editoriais do Playbook.
- O "modo mock" do `generator.py` (usado quando `ANTHROPIC_API_KEY` está
  ausente) sempre devolve o mesmo lote de exemplo — isso é suficiente para
  testar dry-run/render/validação/publicação simulada, mas **não** simula
  a variação real de conteúdo que a API do Claude produziria.
- A lógica de "regeneração pontual" de uma peça reprovada (1ª falha pede
  regeneração, 2ª falha descarta) está implementada em
  `run.py::revalidate_and_filter`. Em modo mock local ela reavalia a
  mesma peça (o mock não varia entre chamadas), então na prática ela só
  é testada de ponta a ponta com `ANTHROPIC_API_KEY` real, chamando o
  Cérebro novamente por peça — comportamento documentado no código.

## Estrutura do projeto

```
agente-conteudo-dcvtq/
├── run.py                      # orquestrador (9 etapas)
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/workflows/agente.yml
├── config/
│   ├── blocklist.txt
│   └── temas.json
├── src/
│   ├── state.py       # load_state()/save_state(), janela 45 dias
│   ├── metrics.py      # fetch_metrics() — cliente Metricool
│   ├── generator.py     # generate_batch() — API do Claude (+ modo mock)
│   ├── validator.py      # validate_batch() — validador de guarda
│   ├── render.py           # render_images() — Pillow, regra de overflow
│   ├── storage.py           # upload_images() — Cloudflare R2
│   ├── publisher.py          # schedule_posts() — Metricool
│   └── reporter.py            # send_report() — Resend
├── tests/
│   ├── test_validator.py       # critério de aceite #3
│   └── test_render.py           # critério de aceite #4
└── state/
    ├── history.json    # seed: []
    └── scheduled.json  # seed: {}
```
