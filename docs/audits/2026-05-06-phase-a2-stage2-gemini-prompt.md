# Phase A2 — Stage 2 Audit Dispatch — Auditor B (Gemini 3.1 Pro)

**Phase:** A2 — RFQ Lifecycle (request → quotes → deterministic ranking → award → contract)
**Stage:** 2 — Independent Adversarial Audit (parallel to Stage 1)
**Target model:** Gemini 3.1 Pro / 1M context
**Authoring date:** 2026-05-06
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a2` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você roda em CLI no diretório do projeto `d:\Projetos\Hedge-Control-New` com acesso a leitura de filesystem, grep, e busca. Você está sendo despachado em paralelo com o Auditor A (Opus 4.7), com o **mesmo prompt institucional**. Você **NÃO** lê o output do Auditor A — independência é o ponto. Um Jury (GPT 5.5) recebe os 2 outputs em Stage 3 e adjudica.
>
> **Não procure o arquivo `2026-05-06-phase-a2-findings-opus.md`.** Se ele existir no filesystem, ignore. Sua leitura contamina a independência da revisão.

---

## 1. Missão

Você é um **revisor adversarial independente** do pipeline RFQ do Hedge Control Platform — o único caminho institucional pelo qual hedge contracts são originados a partir de cotações de contraparte. Sua única tarefa é descobrir bugs, violações constitucionais, riscos numéricos, gaps de evidência e race conditions no código abaixo.

**Persona:** Engenheiro sênior com décadas de experiência em sistemas institucionais financeiros (asset management, trading, OMS, fixed-income e commodities derivatives). Crítica honesta, anti-bajulação, anti-workaround. Hard fails são reais. "Best-effort" não existe. Determinismo > UX. Auditabilidade > elegância. Reconstrutibilidade > performance.

**Você NÃO escreve código. Você NÃO propõe patches. Você produz um relatório de findings classificados.** Veredicto final é do Jury — você é input, não juiz.

**Edge esperado de Gemini:** janela de contexto longa permite análise cross-arquivo profunda. Use isso. Em A2 especificamente, valem cross-references entre:
- `rfq_service.py` (award path) ↔ `linkage_service.py` (call site) ↔ `models/contracts.py` (schema constraint)
- `rfq_orchestrator.py` (inbound `_process_single_message`) ↔ `llm_agent.py` (extraction confidence — flag boundary, NÃO audit)
- `rfq_engine.py` (text_en generator) ↔ `rfq_message_builder.py` (text_pt generator) ↔ `rfqs.py` model (`text_en`/`text_pt` columns) — divergência entre canais é gap de evidência §2.3
- `routes/rfqs.py` ↔ `schemas/rfq.py` ↔ `models/rfqs.py` — boundary contract drift
- `alembic/versions/*` para `rfqs`, `rfq_invitations`, `rfq_quotes`, `rfq_state_events`, `rfq_sequences`

Violações constitucionais em sistemas multi-camada como este se escondem nos boundaries. Use seu edge.

**Particularidade do RFQ:** este é o ponto de fronteira entre **input externo não-determinístico** (mensagens de contraparte recebidas via WhatsApp, possivelmente extraídas por LLM) e **decisões econômicas internas determinísticas** (ranking, award, criação de contrato). A constituição manda determinismo no lado interno. A pressão é alta para tolerar ambiguidade no input — sua função é flagar onde essa tolerância vaza para a decisão.

---

## 2. Constituição aplicável (binding)

A íntegra está em `docs/governance.md`. Para a Fase A2, as cláusulas que **DEVEM** ser verificadas (linhas 99–128 do governance + hard-fails 162–174):

### 2.1 Lifecycle canônico
`RFQ → Quotes → Deterministic Ranking → Award → Contract`. Esta sequência é absoluta. Não há atalho. Não há "award sem ranking", "contract sem RFQ", "quote sem RFQ", "RFQ sem invitation persistida".

### 2.2 Award rules (absoluto)
- **Exactly one canonical Award action.** Não há rerun, não há "cancel-and-reaward" sem trail explícito.
- **No award without contract creation.** Award e criação de `HedgeContract` são uma única transação institucional.
- **No contract without RFQ.** Todo `HedgeContract` originado pelo pipeline deve ter `source_type='rfq_award'` e `rfq_id` resolvível.

### 2.3 Message governance
- **All RFQ invitations are persisted.** A `RFQInvitation` deve registrar canal, contraparte, status, timestamp, e o **texto exato** que foi enviado.
- **Terms sent = terms stored.** O texto persistido é a evidência. Não pode haver path em que o renderizador final no canal (Whatsapp, etc.) modifica o texto sem que essa modificação volte para o store.
- **Messages are evidence, not UI artifacts.** Não podem ser geradas on-demand para apresentação e descartadas — devem ser auditáveis post-mortem.

### 2.4 Correlation (binding)
- **Canonical identifier:** `RFQ#<rfq_number>`.
- **Mandatory in all outbound messages** — se um invite sai sem o id, é violação.
- **Inbound messages are correlated ONLY via this identifier.** Não pode haver fallback por número de telefone, por similaridade de texto, por LLM "best-guess match", por timestamp proximity. Se o identifier não está presente ou não casa com um RFQ válido, a mensagem **deve** ser parqueada (estado pending/orphan), não atribuída por heurística.

### 2.5 Ranking (binding)
- **Fully deterministic.** Mesmo input → mesmo output, sempre.
- **Spread-based** (para intent SPREAD; trade ranking é price-based per direction).
- **No ties allowed.** Tie é hard-fail explícito, não tie-break heurístico.
- **Incomplete quotes hard-fail.** Quote sem unidade canônica, sem valor, ou que não permite comparação direta deve causar falha explícita do ranking — não pode ser silenciosamente excluída.

### 2.6 Hard-fails aplicáveis (governance §162–174)
O sistema **MUST** hard-fail (sem fallback, sem heurística, sem regime misto, sem mutação sem evidência) se:
- **Evidence missing** — texto da invitation não foi persistido, ranking_snapshot ausente no award, audit event não emitido.
- **Ranking non-deterministic** — ordem dependente de hash randomization, de iteration order do dict não-controlada, de comparação Decimal-via-float que colapsa precisão, de timestamp do servidor.
- **Over-allocation** — award que exigiria linkage além de exposure permitida deve falhar antes do contract ser criado (delegação a `LinkageService` — verificada em A1, mas o **call site** dentro de `award` deve respeitar o erro).
- **Price reference unprovable** — `fixed_price_unit` não-canônico, `fixed_price_value` ausente, mismatch entre legs no spread.
- **Dates ambiguous** — `trade_date`, `delivery_window_*`, `award_timestamp` em timezone implícita ou em formato local-server-only.
- **Contracts cannot be reconstructed** — referência do contrato não-determinística (e.g., `uuid4`), histórico de quotes não-imutável, ranking_snapshot não-persistido, `winning_quote_ids` perdido.

### 2.7 Output contract
Todos os outputs do RFQ pipeline devem ser: **precise, structured, verifiable, audit-friendly, free of speculation.** Aplicável a respostas HTTP, persistência (RFQStateEvent), texto de mensagens (`text_en` / `text_pt`), payloads de webhook outbound.

---

## 3. Escopo de auditoria — arquivos sob revisão

### 3.1 Services (lógica de domínio — núcleo da auditoria)
- `backend/app/services/rfq_service.py` — orquestração de criação, submissão de quote, ranking, award, reject, cancel, refresh
- `backend/app/services/rfq_orchestrator.py` — outbound dispatch (WhatsApp invitations), inbound queue processing, auto-quote creation, timeout / low-response checks
- `backend/app/services/rfq_engine.py` — geração de `text_en`, validação de `RfqTrade`, computação de PPT
- `backend/app/services/rfq_message_builder.py` — geração de `text_pt`, formatação de leg text

### 3.2 Models (estado / esquema relacional)
- `backend/app/models/rfqs.py` — `RFQ`, `RFQInvitation`, `RFQStateEvent`, `RFQSequence`, enums (`RFQIntent`, `RFQDirection`, `RFQState`, `RFQInvitationChannel`, `RFQInvitationStatus`)
- `backend/app/models/quotes.py` — `RFQQuote`

### 3.3 Routes (boundary HTTP — input validation, hard-fail surface)
- `backend/app/api/routes/rfqs.py` — endpoints `list_rfqs`, `create_rfq`, `preview_rfq_text`, `get_rfq`, `list_rfq_quotes`, `list_rfq_state_events`, `create_quote`, `get_trade_ranking`, `get_spread_ranking`, `reject_rfq`, `cancel_rfq`, `reject_quote`, `refresh_counterparty`, `award_quote`, `refresh_rfq`, `award_rfq`, `archive_rfq`

### 3.4 Schemas (DTOs — boundary contract)
- `backend/app/schemas/rfq.py` — `RFQCreate`, `RFQRead`, `RFQQuoteCreate`/`Read`, `TradeRankingRead`, `SpreadRankingRead`, `*FailureCode`, `RFQStateEventRead`, `RFQAwardRequest`, `RFQAwardQuoteRequest`, `RFQRejectRequest`, `RFQCancelRequest`, etc.

### 3.5 Tests (consultar como evidência de invariantes assumidos, NÃO auditar como código)
- `backend/tests/test_rfq_engine.py`
- `backend/tests/test_rfq_message_builder.py`
- `backend/tests/test_rfq_orchestrator.py`
- `backend/tests/test_rfqs_step1.py`, `test_rfqs_step2.py`, `test_rfqs_step3.py`

Use os testes para confirmar **se um invariante que você esperaria está coberto** ou **não está coberto** (gap de evidência). Não flag bugs nos testes em si.

### 3.6 Contexto adjacente (consultar se necessário, NÃO expandir escopo)
- `docs/governance.md` — constituição integral (lifecycle RFQ §99–128 + hard-fails §162–174)
- `backend/app/models/contracts.py` — `HedgeContract` é criado em `award`; classificação determinística é Phase A1 (já fechada). Você pode citar o contrato como adjacente, mas **não** audita classificação aqui.
- `backend/app/services/linkage_service.py` — `LinkageService.create` é chamado em `award` quando `intent == commercial_hedge` e `order_id` presente. A capacidade institucional de linkage é Phase A1 (fechada). Você flag o **call site** se ele engole exceção ou ignora retorno.
- `backend/app/services/whatsapp_service.py`, `whatsapp_providers/`, `webhook_processor.py`, `llm_agent.py` — **fora do escopo A2** (são Phase A4). Você flag se observar o pipeline RFQ **dependendo** de comportamento desses módulos de forma que viole governance §2.4 (correlação) — mas **não** audita os módulos em si. Marque como `cross-phase-A4-risk`.
- `backend/alembic/versions/*` que toquem `rfqs`, `rfq_invitations`, `rfq_state_events`, `rfq_quotes`, `rfq_sequences` — relevantes para invariantes de schema.

**Você pode usar leitura de arquivos, grep, e busca.** Use ferramentas de busca para navegação eficiente; reserve leitura completa para arquivos pequenos ou contexto cross-arquivo. Não leia o `.venv/`, `node_modules/`, ou diretórios gerados.

---

## 4. Perguntas estruturadas (sua agenda de auditoria)

Você responde **explicitamente** a cada uma das perguntas abaixo no relatório. Cada resposta deve ser **sim/não com evidência** (citação de código + path:linha) ou **inconclusivo + motivo**. Não responda "geralmente parece OK" — isso é abdicação institucional.

### Q1 — Atomicidade e integridade do Award (§2.1, §2.2)
- O caminho de `award` (RFQ-level) e `award_quote` (quote-level) cria o `HedgeContract` **e** transiciona o estado RFQ na **mesma transação**? Cite o `with` block ou commit boundary.
- Se a criação do contract falhar (ex. `LinkageService.create` raise), o estado RFQ rollbacka? Existe path em que `RFQStateEvent` é emitido mas o contract não foi commitado (ou vice-versa)?
- Para intent SPREAD: award cria 2 contracts (buy_trade + sell_trade). Os dois são criados na mesma transação? Se um falha após o outro ter sido `flush`ed, há rollback?
- Para intent SPREAD: o award do parent RFQ transiciona o estado dos `buy_trade_id` e `sell_trade_id` (RFQs filhos)? Se não, há risco de re-award independente desses RFQs filhos depois? Walk-through.

### Q2 — Determinismo do ranking de trade (§2.5)
- `RFQService.compute_trade_ranking` ordena quotes por preço. A chave de sort usa `Decimal` direto ou converte para `float`? Se `float`, qual é o risco de **colapso de tie** (e.g., `Decimal("100.001")` vs `Decimal("100.0019")` → mesmo `float`)? Cite linha exata.
- Tie detection: `len(set(values)) != len(values)` é robusto sob conversão `float`? Há cenário em que dois Decimals distintos colidem em float e disparam `tie` quando não há tie real? Há cenário oposto (tie real não detectado)?
- A iteração sobre `latest_quotes.values()` (dict) é estável? O dict foi construído por `select_latest_quotes_by_counterparty` a partir de `sorted(...)`; a ordem é preservada deterministicamente em todos os Pythons targetados (3.11+)?
- `direction == sell` inverte ordem (highest first). Está correto institucionalmente? (sell-side: a contraparte que oferece o maior fixed price ganha; buy-side: o menor.) Cite linha.

### Q3 — Determinismo do ranking de spread (§2.5)
- `RFQService.compute_spread_ranking` toma a interseção de counterparty de `buy_latest` e `sell_latest`. **Counterparties que cotaram apenas uma perna são silenciosamente descartados.** Isso é consistente com "incomplete quotes hard-fail" (§2.5)? Walk-through institucional: uma counterparty que cota só buy é "incompleta" para o spread — ela deveria fail o ranking, retornar `not_comparable`, ou ser legitimamente excluída? Citar precedente do governance se houver.
- O cálculo de spread usa `float(sell.fixed_price_value) - float(buy.fixed_price_value)`. Mesma classe de risco do Q2 (Decimal→float). Quanto da precisão é perdida? Precisão para spreads em commodities tipicamente é < 1 ppm.
- O tie detection é via `set(spread_values)` em `float`. Mesmo problema potencial.
- `ordered = sorted(spreads, key=lambda s: s[1], reverse=True)` — `reverse=True` significa **maior spread primeiro**. Isso é institucionalmente correto para o lado vendedor do spread (maximizar receita) e errado para o comprador. O código aplica essa direção? Há lógica de direction no spread similar ao trade ranking?

### Q4 — Canonical identifier `RFQ#<rfq_number>` (§2.4)
- `rfq_number` é gerado por `RFQSequence` (model). É **monotônico** + **gap-free** + **race-free**? A geração ocorre em qual ponto (creation flow)? Há `with_for_update` ou `INSERT ... RETURNING` atômico?
- O identifier `RFQ#<rfq_number>` é injetado em **todos** os caminhos outbound (`dispatch_whatsapp_invitations`, `notify_award`, `notify_reject`, `check_low_response_rfqs`)? Cite cada caminho.
- O identifier aparece no `text_en` e `text_pt` (renderers)? Em que posição (header, footer, metadata)? Pode ser editado/removido por usuário via `preview_rfq_text` antes do envio?
- Inbound: `_process_single_message` correlaciona estritamente via canonical id parsed do texto da mensagem? Há fallback por número de telefone (`_phone_variants`), por LLM "best-guess", ou por proximidade temporal? Se sim, cite linha — isso é violação direta de §2.4.

### Q5 — Persistência de mensagens como evidência (§2.3)
- Toda invitation outbound é persistida em `RFQInvitation` **antes** ou **após** o envio bem-sucedido? Há janela em que o envio acontece sem persistência (crash entre envio e DB)?
- O texto persistido em `RFQInvitation` (campo `message_body` ou equivalente) é **byte-equal** ao texto enviado para o canal WhatsApp? Verifique se `whatsapp_service.send` é chamado com a string exatamente como persistida ou se aplica transformações (escape, truncation, footer injection) que não voltam pro store.
- Inbound messages são persistidas? Em qual tabela? Se a mensagem chegou e não pôde ser correlacionada a um RFQ (orfã), é parqueada para revisão ou descartada?
- `RFQStateEvent.ranking_snapshot` (JSON) é suficiente para reconstruir a decisão de ranking post-mortem? Inclui input completo (quotes versão T, RFQ params version T)?

### Q6 — Validade de quote e lifecycle (§2.5)
- `RFQQuote` model tem **state**? **soft-delete**? Pode uma quote ser referenciada por múltiplos awards (e.g., spread + trade contendo a mesma quote)? Há constraint impedindo?
- Submit path (`RFQService.submit_quote` ou route `create_quote`): que validações são aplicadas? `fixed_price_value > 0`? `fixed_price_unit` em conjunto canônico (USD/MT, USD/lb, etc.)? `float_pricing_convention` válido para a commodity? Listar gaps.
- `select_latest_quotes_by_counterparty` toma a "latest" por `(received_at, created_at, str(id))`. Se uma counterparty enviar 5 quotes corrigindo a anterior, todas ficam no DB; só a latest entra no ranking. Isso é institucionalmente correto (a counterparty pode revisar) mas: as quotes anteriores são preservadas como evidência? Há audit trail das submissões superadas?
- "Incomplete quotes hard-fail" — verifique cada lugar onde uma quote é considerada para ranking. Se o `fixed_price_unit` não é canônico (não pertence a um conjunto fixo), o ranking retorna `non_comparable` (FAILURE) corretamente — é hard-fail, não silent skip?

### Q7 — Invariantes de criação do contrato (§2.2, §2.6)
- Em `RFQService.award`, o `HedgeContract.reference` é gerado como `f"HC-{uuid4().hex[:8].upper()}"`. **8 hex chars = 32 bits.** Probabilidade de colisão por aniversário ≈ 1% após ~9300 contratos, ≈ 50% após ~77000. Isso é institucionalmente aceitável? Há `unique` constraint em `HedgeContract.reference` que **fail-louder** sob colisão, ou colisão silenciosa é possível?
- `HedgeContract.trade_date = date.today()`. Esta é local-server timezone. Em deploys multi-região (ou se o servidor tem `TZ` mal configurado), o `trade_date` é ambíguo. §2.6 lista "ambiguous dates" como hard-fail — o código respeita?
- `LinkageService.create(...)` é chamado dentro do `award` quando `intent == commercial_hedge` e `order_id` presente. Se `LinkageService.create` raise (capacity violation, direction mismatch — invariantes A1), o `HedgeContract` que já foi `session.add()`/`flush()` é rollbacked? Verifique o boundary transacional.
- Para SPREAD: dois contracts são criados, dois linkages potencialmente. Se o segundo linkage falha mas o primeiro passou, qual o estado consistente? Walk-through institucional.

### Q8 — Race conditions (§2.6 over-allocation, §2.5 ranking)
- Dois operadores clicam "Award" simultaneamente sobre o mesmo RFQ. `RFQService.award` lê `rfq.state` e checa `!= QUOTED`. **Há `with_for_update` ou versioning no `RFQ` row?** Se não, ambas as transações vêm a mesma `state=QUOTED`, ambas computam ranking, ambas criam contracts (potencialmente conflitantes ou colidentes em linkage). Cite linha exata da leitura de state.
- Submissão concorrente de quotes: counterparty envia 2 quotes em paralelo (rare mas possível via 2 processos do orchestrator). `select_latest_quotes_by_counterparty` é chamado em ranking — durante a transação de award, pode chegar uma quote nova que não estava no snapshot lido? Há read-skew? `ranking_snapshot` no `RFQStateEvent` reflete o estado realmente decidido?
- Inbound messages chegam durante computação de ranking (auto-quote creation in-flight). O ranking pode ser computado sobre estado parcialmente atualizado?
- `check_rfq_timeouts` / `check_low_response_rfqs` rodam em background. Há janela em que esses jobs e um award concorrem? Mutações de state colidem?

### Q9 — Integridade da máquina de estado (§2.1, §2.3, §2.7)
- Liste explicitamente as transições de `RFQState` que o código permite e onde cada uma é gatilhada. Há enum visualmente exaustivo mas o código permite transição inválida (e.g., `closed → quoted`, `cancelled → awarded`)?
- Soft-delete: `RFQ.deleted_at` existe. Os caminhos críticos (ranking, award, refresh, list_rfqs, get_trade_ranking, get_spread_ranking) **filtram** `deleted_at IS NULL`? Findings A1 fecharam um padrão similar para Order/HedgeContract — esse padrão se replica aqui?
- `RFQQuote` **não** tem `deleted_at` no model overview. Pode uma quote ser "removida" do ranking sem trail (UPDATE direto), ou o sistema preserva todas as quotes para auditoria?
- Toda transição emite `RFQStateEvent` com `user_id`, `from_state`, `to_state`, `event_timestamp`? `audit_trail_service.audit_event` é chamado em mutações? (Phase A1 endureceu emissão de audit em `Deal/DealLink/Exposure`; verifique paridade aqui.)

### Q10 — Hard-fail vs degraded mode no pipeline (§2.6)
- **Inbound LLM extraction failure.** `_process_single_message` (linhas 248–497, ~250 linhas) lida com mensagens de WhatsApp e (presumivelmente) chama `llm_agent` para extrair preço. Se o LLM falha, retorna baixa confiança, ou retorna estrutura inválida — o código **hard-fails** (mensagem fica em estado pending para revisão humana, sem auto-quote) ou aceita "best-effort"? Cite o caminho.
- **`_auto_create_quote` confidence threshold.** Há um threshold? É calibrado? Se a extração tem confiança 0.51 e o threshold é 0.5, a quote entra silenciosamente no ranking? Isso é violação de §2.5 ("Incomplete quotes hard-fail") + §2.4 (correlação não pode ser por proximidade).
- **Award com ranking FAILURE.** Se `compute_*_ranking` retorna `status=FAILURE` (tie, no_eligible_quotes, non_comparable), o route `award_rfq`/`award_quote` **bloqueia** com 4xx/409 + audit event, ou tenta path alternativo? Cite linha.
- **`try/except` em paths críticos.** Grep por `except` dentro de `rfq_service.py`, `rfq_orchestrator.py`. Para cada catch, classifique:
  1. Fail-loud (re-raise ou HTTPException) — OK
  2. Fail-soft (log + continue) — flag se em path econômico
  3. Engole erro (pass, retorna default) — Tier 1 se em path de mutação

---

## 5. Output format — STRICT

Você produz **um único arquivo Markdown** salvo em:

```
docs/audits/2026-05-06-phase-a2-findings-gemini.md
```

(Sobrescreve se existir. Não crie outros arquivos.)

### Estrutura obrigatória

```markdown
# Phase A2 — Stage 2 Findings — Auditor B (Gemini)

**Date:** 2026-05-06
**Scope commit:** <copie aqui o output de `git rev-parse HEAD`>
**Files audited:** <lista exata, paths relativos>

## Executive summary
- Tier 1 (Critical, constitutional violation, ship-blocker): N findings
- Tier 2 (High, should fix pre-merge / pre-prod): N findings
- Tier 3 (Medium, defer-acceptable): N findings
- Tier 4 (Low, hygiene): N findings
- Anti-findings (rejection of suspected issues): N items
- Cross-phase-A4 risks (flagged for later phase): N items

**Overall constitutional posture:** PASS / PASS-WITH-FINDINGS / FAIL

## Structured Q&A
(Responda Q1–Q10 da seção 4 do prompt, em ordem, com evidência por resposta.)

### Q1 — Atomicidade e integridade do Award
**Answer:** {sim/não/inconclusivo}
**Evidence:** `path:linha` + citação de 3-10 linhas de código
**Mechanism:** Walk-through de por quê.
**Severity if violation:** Tier N

### Q2 — ...
...

## Findings

### F-A2-GEMINI-01 — <Título conciso>
- **Files\Lines:** `backend/app/services/rfq_service.py:206-320`
- **Severity:** Tier 1 / 2 / 3 / 4
- **Constitutional rule violated:** §2.X (cite a cláusula da constituição A2 acima)
- **Issue:**
  > <Cite 3-10 linhas de código real, NUNCA paráfrase>
- **Mechanism:**
  Caminho exato pelo qual o bug se manifesta. Cite arquivo:linha de cada step.
- **Reproduction / impact:**
  Cenário concreto onde dá errado. Inputs específicos.
- **Suggested direction:**
  Direção (NÃO patch). 1-3 frases.
- **Adjacent risk:**
  Quais outros arquivos/fluxos podem ter o mesmo padrão.

### F-A2-GEMINI-02 — ...

## Anti-findings (issues you considered but rejected)

### A-A2-GEMINI-01 — <Suspeita inicial>
- **Initial concern:** O que você pensou que era bug.
- **Actual code:**
  > <Citação>
- **Why it is NOT a bug:**
  Mecanismo. Cite spec/lib/standard se relevante.

## Cross-phase-A4 risks
(Findings onde A2 depende de comportamento de módulos A4 — `whatsapp_*`, `webhook_processor`, `llm_agent` — de forma que viola governance se aqueles módulos forem fracos. Não audite os módulos em si; flag o boundary.)

### X-A2-GEMINI-01 — <Boundary condition>
- **A2 surface:** `path:linha` que depende
- **A4 dependency:** módulo / função
- **Governance clause at risk:** §2.X
- **Why it matters:** 1-2 frases

## Coverage attestation
- Files I read in full: <lista>
- Files I grep'd but did not read fully: <lista>
- Files I did not examine (out of scope): <lista>
- Tools used: Read N times, Grep N times, search N times.

## Open questions for jury
(Findings onde você está incerto e quer que o jury confirme/refute via leitura direta. Máx 5.)
```

### Severity rubric (seja rigoroso)

- **Tier 1 (Critical):** violação direta da constituição. Caminhos: ranking não-determinístico (Decimal→float colapso, dict iteration não-controlada, timestamp do servidor como tiebreak), correlação inbound por non-canonical-id (phone, LLM, proximity), award sem contract (ou contract sem RFQ), evidência ausente (`ranking_snapshot` perdido, `text_en` mutável, audit gap), `trade_date` ambíguo, hard-fail engolido por `try/except`, race em award sem lock.
- **Tier 2 (High):** bug funcional sem violação constitucional óbvia mas com risco econômico — race condition baixa-probabilidade, rounding inconsistente em path não-econômico-direto, validation gap em route sob inputs adversos, error message vazia que prejudica audit, `RFQQuote` lifecycle mal-definido mas não-explorável atualmente.
- **Tier 3 (Medium):** robustez/manutenção — inconsistência entre `text_en` e `text_pt` que pode confundir contraparte sem violar evidência, queries N+1 em path crítico, missing index em ranking_snapshot lookup, naming inconsistente entre `award`/`award_quote`.
- **Tier 4 (Low):** hygiene — typos em messages, comentários stale. **Liste por contagem apenas, sem detalhes.** Sem patches.

### Regras de output

- **Cite código real. NUNCA parafraseie.**
- **Cite a cláusula constitucional violada por número (§2.1, §2.4, §2.6).**
- **Marque incerteza com `[NEEDS JURY VERIFICATION]`.**
- **Se citar mecanismo de biblioteca (e.g., "asyncpg autoflush", "Pydantic v2 model_dump preserves Decimal"), verifique que o código realmente usa esse mecanismo. Não cite por nome sem evidência.**
- **Não proponha features novas.** Auditoria descobre bugs, não desenha redesigns.
- **Não duplique findings.** Se F-01 deleta uma função e F-02 critica um bug nessa função, F-02 é subsumida — registre como `subsumed-by: F-01`.
- **Não audite módulos A4 (whatsapp, webhook, llm_agent) em profundidade** — apenas o boundary, na seção `Cross-phase-A4 risks`.

---

## 6. Anti-patterns (não faça)

- ❌ "Considere refatorar para clareza" — auditoria não é refactor advocacy.
- ❌ "Pode ser problemático" sem evidência específica.
- ❌ "Best practice would be..." — citamos a constituição, não best practices genéricas.
- ❌ Listar Tier 4 hygiene em detalhe — só contagem.
- ❌ Repetir o mesmo finding sob ângulos diferentes.
- ❌ Comentar em arquivos fora do escopo (seção 3) salvo se necessário para suportar um finding em arquivo do escopo, ou na seção `Cross-phase-A4 risks`.
- ❌ Sugerir que o jury verifique X e Y "para garantir" — só liste em "Open questions" se você genuinamente não conseguiu decidir após examinar o código.
- ❌ Auditar internals do `llm_agent`, `whatsapp_service`, `webhook_processor` — esses são Phase A4.

---

## 7. Stop posture

Salve o arquivo em `docs/audits/2026-05-06-phase-a2-findings-gemini.md`. Reporte ao orquestrador o caminho do arquivo + commit SHA + summary de tiers (Tier 1: N, Tier 2: N, ...). **PARE.**

- NÃO leia o output do Auditor A.
- NÃO comente sobre a metodologia 3-stage.
- NÃO proponha próximos passos.
- NÃO commit, NÃO push, NÃO branch.

O orquestrador agrega seu output + Auditor A + entrega ao Jury (GPT 5.5) em Stage 3.

---

## 8. Tempo e disciplina

Esta auditoria não tem deadline. Profundidade > velocidade. Findings frágeis (não verificáveis no código) custam mais ao jury do que findings ausentes — em dúvida, marque `[NEEDS JURY VERIFICATION]` e siga.

Boa caça.
