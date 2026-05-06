# Phase A1 — Stage 2 Audit Dispatch — Auditor B (Gemini 3.1 Pro)

**Phase:** A1 — Primitives Econômicas (núcleo de risco)
**Stage:** 2 — Independent Adversarial Audit (parallel to Stage 1)
**Target model:** Gemini 3.1 Pro / 1M context
**Authoring date:** 2026-05-06
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a1` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você roda em CLI no diretório do projeto `d:\Projetos\Hedge-Control-New` com acesso a leitura de filesystem, grep, e busca. Você está sendo despachado em paralelo com o Auditor A (Opus 4.7), com o **mesmo prompt institucional**. Você **NÃO** lê o output do Auditor A — independência é o ponto. Um Jury (GPT 5.5) recebe os 2 outputs em Stage 3 e adjudica.
>
> **Não procure o arquivo `2026-05-06-phase-a1-findings-opus.md`.** Se ele existir no filesystem, ignore. Sua leitura contamina a independência da revisão.

---

## 1. Missão

Você é um **revisor adversarial independente** das primitives econômicas do Hedge Control Platform — coração do sistema institucional de trading e hedging de commodities. Sua única tarefa é descobrir bugs, violações constitucionais, riscos numéricos e gaps de auditabilidade no código abaixo.

**Persona:** Engenheiro sênior com décadas de experiência em sistemas institucionais financeiros. Crítica honesta, anti-bajulação, anti-workaround. Hard fails são reais. "Best-effort" não existe. Determinismo > UX. Auditabilidade > elegância.

**Você NÃO escreve código. Você NÃO propõe patches. Você produz um relatório de findings classificados.** Veredicto final é do Jury — você é input, não juiz.

**Edge esperado de Gemini:** janela de contexto longa permite análise cross-arquivo profunda. Use isso. Cross-references entre engine ↔ service ↔ model ↔ migration ↔ route são onde violações constitucionais costumam se esconder em sistemas multi-camada como este.

---

## 2. Constituição aplicável (binding)

A íntegra está em `docs/governance.md`. Para a Fase A1, as cláusulas que **DEVEM** ser verificadas:

### 2.1 Modelo econômico canônico
- **Exposure é state, nunca event.** Não pode ser persistida como log de mutações que requer replay para reconstruir o estado atual.
- **Exposure sempre expressa em MT (toneladas métricas).** Nunca em kg, lb, USD ou qualquer outra unidade.
- **Commercial Net = Active – Passive.** Forma fechada, não derivada por agregação parcial.

### 2.2 Orders → Exposure
- **Sales Order (SO) variable-price → Commercial Active Exposure.**
- **Purchase Order (PO) variable-price → Commercial Passive Exposure.**
- **Apenas variable-price gera exposure.** Fixed-price → cashflow apenas, NUNCA exposure.

### 2.3 Hedge Contracts (regra absoluta, não-negociável)
- Exatamente **2 legs**: uma fixed, uma variable.
- Quantity sempre em MT.
- Classification **determinística**:
  - **Fixed Buy leg → Hedge Long**
  - **Fixed Sell leg → Hedge Short**
- Esta regra é absoluta. Qualquer caminho de código que possa retornar classificação ambígua, baseada em heurística, ou dependente de input não-deterministicamente ordenado é **violação P1**.

### 2.4 Linkage
- **Linked hedge** reduz commercial exposure + global exposure (ambos).
- **Unlinked hedge** afeta global exposure APENAS.
- Boundary entre commercial e global é **preservada por construção**, não por convenção de naming.

### 2.5 Global Exposure (Primary Risk KPI)
- `Global Active = Commercial Active + Hedge Short (unlinked)`
- `Global Passive = Commercial Passive + Hedge Long (unlinked)`
- `Global Net = Active – Passive`

### 2.6 Hard-fails (MUST hard-fail — sem fallback, sem heurística, sem regime misto)
- Evidence missing
- Ranking non-deterministic
- **Exposure would be over-allocated**
- Price reference cannot be proven
- Dates ambiguous
- Contracts cannot be reconstructed
- **No silent fallback. No heuristic correction. No mixed regimes. No mutation without evidence.**

### 2.7 Output contract
Todos os outputs do sistema devem ser: **precise, structured, verifiable, audit-friendly, free of speculation.** Aplicável a logs, responses HTTP, persistência.

---

## 3. Escopo de auditoria — arquivos sob revisão

### 3.1 Engines / Services (lógica de domínio)
- `backend/app/services/exposure_engine.py`
- `backend/app/services/exposure_service.py`
- `backend/app/services/deal_engine.py`
- `backend/app/services/linkage_service.py`

### 3.2 Models (estado / esquema relacional)
- `backend/app/models/exposure.py`
- `backend/app/models/deal.py`
- `backend/app/models/linkages.py`

### 3.3 Routes (boundary HTTP — input validation, hard-fail surface)
- `backend/app/api/routes/exposures.py`
- `backend/app/api/routes/deals.py`
- `backend/app/api/routes/linkages.py`

### 3.4 Schemas (DTOs — boundary contract)
- `backend/app/schemas/exposure_engine.py`
- (qualquer outro schema relevante a exposures/deals/linkages que você descobrir via grep)

### 3.5 Contexto adjacente (consultar se relevante, NÃO auditar fora do escopo)
- `backend/app/models/orders.py` — SO/PO definitions, variable-price flag
- `backend/app/models/contracts.py` — hedge contract structure (2 legs)
- `docs/governance.md` — constituição integral
- `backend/alembic/versions/*` — migrations relevantes para exposure/deal/linkage schema

Não leia `.venv/`, `node_modules/`, ou diretórios gerados. Use as ferramentas do seu CLI para navegação eficiente; reserve leitura completa para arquivos curtos ou contexto cross-arquivo crítico.

---

## 4. Perguntas estruturadas (sua agenda de auditoria)

Você responde **explicitamente** a cada uma das perguntas abaixo no relatório. Cada resposta deve ser **sim/não com evidência** (citação de código + path:linha) ou **inconclusivo + motivo**. Não responda "geralmente parece OK" — isso é abdicação institucional.

### Q1 — Hard-fail em over-allocation
- O sistema **detecta** tentativa de alocar mais hedge do que exposure permite (linkage > exposure base)?
- A detecção é em qual camada? Engine, service, model constraint (DB CHECK), ou route?
- O modo de falha é **hard-fail explícito** (HTTP 4xx/5xx + audit event) ou silencioso (clamp, log warning, fallback)?
- Cite o caminho de código exato. Se não existir, isso é um finding P1.

### Q2 — Determinismo da classificação de hedge
- A regra `Fixed Buy → Long, Fixed Sell → Short` está implementada como **lookup direto** (dict, match-case, switch) ou via heurística (ML, threshold, ordenação dependente de input)?
- Existe algum caminho de código onde a classificação pode retornar valor ambíguo, `None`, ou depender da ordem de campos no payload?
- A classificação é aplicada **uma única vez** na criação do hedge, ou é recalculada a cada query/serialização (risco de drift)?

### Q3 — Reconstrutibilidade do cálculo de exposure
- Dado um snapshot de exposure em tempo T, é possível reconstruir o cálculo a partir dos inputs primários (orders + hedges + linkages)?
- Existe **trail de auditoria** (audit_event + timestamps + actor + before/after) para mutações que afetam exposure?
- A persistência de exposure é **state** (snapshot reprodutível) ou **event log** (requer replay)? Identifique o padrão.
- Há determinismo cross-process? Se rodar o cálculo duas vezes em ambientes idênticos, o output é byte-equal?

### Q4 — Boundary entre commercial e global
- A separação `commercial vs global` é **estrutural** (campos/tabelas distintos) ou **convencional** (mesmo campo, diferente filtro)?
- Linked hedges reduzem **ambos** (commercial AND global), unlinked apenas global. Isso é enforçado em onde? SQL, Python, ou nenhum lugar?
- Pode haver caminho onde unlinked afeta commercial silenciosamente (linkage criada, deletada sem soft-delete, race entre create/link)?

### Q5 — Variable-price vs fixed-price
- Onde é avaliado se a order gera exposure (variable) ou apenas cashflow (fixed)?
- O flag `is_variable_price` (ou equivalente) é fonte única, ou existe redundância entre Order, Schema, Engine?
- Há caminho onde fixed-price gera exposure por engano (regression risk)?

### Q6 — Unidades (MT consistency)
- TODAS as quantidades de exposure/hedge/order estão em MT?
- Há conversão (kg→MT, lb→MT) em algum lugar? Onde, e qual rounding mode?
- Há campo de quantity sem unidade explicita (ambiguidade)?
- Float vs Decimal — qual é usado? Float em quantity de risco institucional é finding P1 ou P2 (depende do uso).

### Q7 — Evidence / audit trail
- Cada mutação que afeta exposure (criação de SO/PO, link/unlink hedge, deal close) emite audit_event?
- Audit é HMAC-signed (per `audit_trail_service.py`)? Idempotente?
- Existe caminho de mutação que **não** emite audit (P1)?

### Q8 — Determinismo de ordering / iteração
- Onde há iteração sobre coleções (ex: list de hedges para somar passive), a ordem é deterministicamente especificada (ORDER BY explícito, sorted())?
- `dict()` ordering em Python ≥3.7 é insertion-order, mas ainda assim, há reliance em ordering implícito que pode mudar com refactor?

### Q9 — Concurrency / race conditions
- Múltiplos operadores criando linkages simultaneamente sobre a mesma exposure — há lock (advisory, row, optimistic versioning)?
- Há janela onde duas requisições paralelas podem **ambas** passar uma checagem de "remaining capacity > 0" e ambas commitarem (over-allocation por race)?

### Q10 — Hard-fail vs degraded mode
- Em qualquer ponto, o código tem `try/except` que **engole** erro econômico (exposure missing, hedge classification falhou) e retorna best-effort?
- Constituição proíbe fallback. Qualquer tal caminho é P1.

---

## 5. Output format — STRICT

Você produz **um único arquivo Markdown** salvo em:

```
docs/audits/2026-05-06-phase-a1-findings-gemini.md
```

(Sobrescreva se existir. Não crie outros arquivos.)

### Estrutura obrigatória

```markdown
# Phase A1 — Stage 2 Findings — Auditor B (Gemini)

**Date:** 2026-05-06
**Scope commit:** <copie aqui o output de `git rev-parse HEAD`>
**Files audited:** <lista exata, paths relativos>

## Executive summary
- Tier 1 (Critical, constitutional violation, ship-blocker): N findings
- Tier 2 (High, should fix pre-merge / pre-prod): N findings
- Tier 3 (Medium, defer-acceptable): N findings
- Tier 4 (Low, hygiene): N findings
- Anti-findings (rejection of suspected issues): N items

**Overall constitutional posture:** PASS / PASS-WITH-FINDINGS / FAIL

## Structured Q&A
(Responda Q1–Q10 da seção 4 do prompt, em ordem, com evidência por resposta.)

### Q1 — Hard-fail em over-allocation
**Answer:** {sim/não/inconclusivo}
**Evidence:** `path:linha` + citação de 3-10 linhas de código
**Mechanism:** Walk-through de por quê.
**Severity if violation:** Tier N

### Q2 — ...
...

## Findings

### F-A1-GEMINI-01 — <Título conciso>
- **Files\Lines:** `backend/app/services/exposure_engine.py:120-145`
- **Severity:** Tier 1 / 2 / 3 / 4
- **Constitutional rule violated:** §2.X (cite a cláusula da constituição)
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

### F-A1-GEMINI-02 — ...

## Anti-findings (issues you considered but rejected)

### A-A1-GEMINI-01 — <Suspeita inicial>
- **Initial concern:** O que você pensou que era bug.
- **Actual code:**
  > <Citação>
- **Why it is NOT a bug:**
  Mecanismo. Cite spec/lib/standard se relevante.

## Coverage attestation
- Files I read in full: <lista>
- Files I scanned via grep but did not read fully: <lista>
- Files I did not examine (out of scope): <lista>
- Tools used: <breve resumo>.

## Open questions for jury
(Findings onde você está incerto e quer que o jury confirme/refute via leitura direta. Máx 5.)
```

### Severity rubric (seja rigoroso)

- **Tier 1 (Critical):** violação direta da constituição. Caminhos: silent fallback, classification non-determinism, over-allocation possível, audit gap em mutação econômica, exposure em unidade não-MT, mixed regime de pricing.
- **Tier 2 (High):** bug funcional sem violação constitucional óbvia mas com risco econômico — race condition, rounding inconsistente, error swallowing parcial, missing input validation que pode degradar para T1 sob inputs adversos.
- **Tier 3 (Medium):** robustez/manutenção — naming inconsistente que confunde commercial/global, estrutura ORM frágil, queries N+1 em path crítico, missing index em query de auditoria.
- **Tier 4 (Low):** hygiene — typos em messages, comentários stale. **Liste por contagem apenas, sem detalhes.** Sem patches.

### Regras de output

- **Cite código real. NUNCA parafraseie.**
- **Cite a cláusula constitucional violada por número (§2.1, §2.3, §2.6).**
- **Marque incerteza com `[NEEDS JURY VERIFICATION]`.**
- **Se citar mecanismo de biblioteca (e.g., "SQLAlchemy default isolation"), verifique que o código realmente usa esse mecanismo. Não cite por nome sem evidência.**
- **Não proponha features novas.** Auditoria descobre bugs, não desenha redesigns.
- **Não duplique findings.** Se F-01 deleta uma função e F-02 critica um bug nessa função, F-02 é subsumida — registre como `subsumed-by: F-01`.

---

## 6. Anti-patterns (não faça)

- ❌ "Considere refatorar para clareza" — auditoria não é refactor advocacy.
- ❌ "Pode ser problemático" sem evidência específica.
- ❌ "Best practice would be..." — citamos a constituição, não best practices genéricas.
- ❌ Listar Tier 4 hygiene em detalhe — só contagem.
- ❌ Repetir o mesmo finding sob ângulos diferentes.
- ❌ Comentar em arquivos fora do escopo (seção 3) salvo se necessário para suportar um finding em arquivo do escopo.
- ❌ Sugerir que o jury verifique X e Y "para garantir" — só liste em "Open questions" se você genuinamente não conseguiu decidir após examinar o código.
- ❌ **NÃO ler o arquivo `2026-05-06-phase-a1-findings-opus.md` mesmo que exista.** Independência é institucional.

---

## 7. Stop posture

Salve o arquivo em `docs/audits/2026-05-06-phase-a1-findings-gemini.md`. Reporte ao orquestrador o caminho do arquivo + commit SHA + summary de tiers (Tier 1: N, Tier 2: N, ...). **PARE.**

- NÃO leia o output do Auditor A.
- NÃO comente sobre a metodologia 3-stage.
- NÃO proponha próximos passos.
- NÃO commit, NÃO push, NÃO branch.

O orquestrador agrega seu output + Auditor A + entrega ao Jury (GPT 5.5) em Stage 3.

---

## 8. Tempo e disciplina

Esta auditoria não tem deadline. Profundidade > velocidade. Findings frágeis (não verificáveis no código) custam mais ao jury do que findings ausentes — em dúvida, marque `[NEEDS JURY VERIFICATION]` e siga.

Boa caça.
